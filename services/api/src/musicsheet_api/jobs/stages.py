"""Guarded, transactional stage execution attempts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import asyncpg
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.jobs.repository import JobRepository, _COLUMNS, _record, advisory_lock_key


_ATTEMPT_COLUMNS = (
    "id, job_id, stage, attempt, status, provider, model_version, "
    "started_at, completed_at, duration_ms, error_code, error_detail"
)
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_STAGES = tuple(PipelineStage)


@dataclass(frozen=True)
class StageAttemptRecord:
    id: str
    job_id: str
    stage: PipelineStage
    attempt: int
    status: Literal["RUNNING", "COMPLETED", "FAILED"]
    provider: str | None
    model_version: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_detail: str | None


@dataclass(frozen=True)
class StageBeginResult:
    action: Literal["RUN", "CONTINUE", "CANCELED", "FAILED", "NOOP"]
    job: JobRecord | None
    attempt: StageAttemptRecord | None = None


@dataclass(frozen=True)
class StageFinishResult:
    action: Literal["UPDATED", "NOOP"]
    job: JobRecord | None
    attempt: StageAttemptRecord | None = None


def _attempt_record(row: Mapping[str, Any]) -> StageAttemptRecord:
    return StageAttemptRecord(
        id=row["id"], job_id=row["job_id"], stage=PipelineStage(row["stage"]),
        attempt=row["attempt"], status=row["status"], provider=row["provider"],
        model_version=row["model_version"], started_at=row["started_at"],
        completed_at=row["completed_at"], duration_ms=row["duration_ms"],
        error_code=row["error_code"], error_detail=row["error_detail"],
    )


class StageAttemptRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._jobs = JobRepository(pool)

    async def acquire_stage_lock(
        self, job_id: str, stage: PipelineStage, connection: asyncpg.Connection
    ) -> None:
        """Block until the job/stage lock is free on a dedicated live session."""
        await connection.execute("SELECT pg_advisory_lock($1)", advisory_lock_key(job_id, stage.value))

    async def release_stage_lock(
        self, job_id: str, stage: PipelineStage, connection: asyncpg.Connection
    ) -> None:
        await connection.execute("SELECT pg_advisory_unlock($1)", advisory_lock_key(job_id, stage.value))

    async def begin_attempt(
        self, job_id: str, stage: PipelineStage, *,
        provider: str | None = None, model_version: str | None = None,
    ) -> StageBeginResult:
        """Claim one execution while holding the owning job row lock."""
        if provider is not None and len(provider) > 64:
            raise ValueError("provider is too long")
        if model_version is not None and len(model_version) > 32:
            raise ValueError("model_version is too long")
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS}, start_job_attempts FROM jobs WHERE id = $1 FOR UPDATE", job_id
            )
            if row is None:
                return StageBeginResult("NOOP", None)
            job = _record(row)
            active_statuses = (
                JobStatus.RUNNING, JobStatus.RETRYING, JobStatus.CANCEL_REQUESTED
            )
            if job.status not in active_statuses:
                return StageBeginResult("NOOP", job)

            if job.current_stage is not stage:
                # The stage transaction may have committed before Celery published
                # its chain-success callback. Prove that this delivery completed
                # an earlier stage before returning normally to Celery.
                if _STAGES.index(stage) >= _STAGES.index(job.current_stage):
                    return StageBeginResult("NOOP", job)
                previous = await connection.fetchrow(
                    f"SELECT {_ATTEMPT_COLUMNS} FROM stage_attempts "
                    "WHERE job_id = $1 AND stage = $2 ORDER BY attempt DESC LIMIT 1",
                    job_id, stage.value,
                )
                if previous is not None and previous["stage"] == stage.value \
                        and previous["status"] == "COMPLETED":
                    return StageBeginResult("CONTINUE", job, _attempt_record(previous))
                return StageBeginResult("NOOP", job)

            previous = await connection.fetchrow(
                f"SELECT {_ATTEMPT_COLUMNS} FROM stage_attempts "
                "WHERE job_id = $1 AND stage = $2 ORDER BY attempt DESC LIMIT 1",
                job_id, stage.value,
            )
            if previous is not None and previous["status"] == "COMPLETED":
                # A completed attempt at the current stage contradicts the
                # atomic finish transition and is not safe to execute again.
                return StageBeginResult("NOOP", job)
            was_lost = previous is not None and previous["status"] == "RUNNING"
            if was_lost:
                code = "CANCELED" if job.status is JobStatus.CANCEL_REQUESTED else "WORKER_LOST"
                previous = await connection.fetchrow(
                    "UPDATE stage_attempts SET status = 'FAILED', completed_at = CURRENT_TIMESTAMP, "
                    "duration_ms = LEAST(2147483647, GREATEST(0, "
                    "(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000)::BIGINT)), "
                    "error_code = $2, error_detail = NULL "
                    "WHERE id = $1 AND status = 'RUNNING' "
                    f"RETURNING {_ATTEMPT_COLUMNS}", previous["id"], code,
                )
                if previous is None:
                    raise RuntimeError("stage attempt changed during locked claim")

            if job.status is JobStatus.CANCEL_REQUESTED:
                changed = await self._jobs.transition_job(
                    job_id, expected_stage=stage,
                    from_statuses=(JobStatus.CANCEL_REQUESTED,),
                    to_status=JobStatus.CANCELED,
                    stage_progress=job.stage_progress or 0,
                    overall_progress=job.overall_progress or 0,
                    error_code="CANCELED", error_message="Job canceled",
                    connection=connection,
                )
                if changed is None:
                    raise RuntimeError("cancellation changed during locked claim")
                return StageBeginResult("CANCELED", changed)

            next_number = 1 if previous is None else previous["attempt"] + 1
            if next_number > 4:
                code = "WORKER_LOST" if was_lost else "RETRY_EXHAUSTED"
                changed = await self._jobs.transition_job(
                    job_id, expected_stage=stage,
                    from_statuses=(JobStatus.RUNNING, JobStatus.RETRYING),
                    to_status=JobStatus.FAILED,
                    stage_progress=job.stage_progress or 0,
                    overall_progress=job.overall_progress or 0,
                    error_code=code, error_message="Stage failed",
                    connection=connection,
                )
                if changed is None:
                    raise RuntimeError("job changed during locked attempt exhaustion")
                return StageBeginResult("FAILED", changed)

            attempt_row = await connection.fetchrow(
                "INSERT INTO stage_attempts "
                "(id, job_id, stage, attempt, status, provider, model_version) "
                "VALUES ($1, $2, $3, $4, 'RUNNING', $5, $6) "
                f"RETURNING {_ATTEMPT_COLUMNS}",
                str(uuid4()), job_id, stage.value, next_number, provider, model_version,
            )
            changed = await self._jobs.transition_job(
                job_id, expected_stage=stage,
                from_statuses=(JobStatus.RUNNING, JobStatus.RETRYING),
                to_status=JobStatus.RUNNING,
                stage_progress=0, overall_progress=job.overall_progress or 0,
                connection=connection,
            )
            if changed is None:
                raise RuntimeError("job changed during locked attempt claim")
            return StageBeginResult("RUN", changed, _attempt_record(attempt_row))

    async def finish_attempt(
        self, job_id: str, stage: PipelineStage, attempt_id: str, *,
        outcome: Literal["COMPLETED", "RETRYING", "FAILED", "CANCELED"],
        stage_progress: int, overall_progress: int,
        next_stage: PipelineStage | None = None,
        error_code: str | None = None,
    ) -> StageFinishResult:
        """Close one attempt and compare-and-set its job in one transaction."""
        if outcome not in ("COMPLETED", "RETRYING", "FAILED", "CANCELED"):
            raise ValueError("invalid stage outcome")
        if error_code is not None and not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a stable uppercase identifier")
        if outcome in ("RETRYING", "FAILED") and error_code is None:
            raise ValueError("failed attempt needs an error_code")
        if outcome != "COMPLETED" and next_stage is not None:
            raise ValueError("only a completed attempt may advance stage")
        if outcome == "COMPLETED" and error_code is not None:
            raise ValueError("completed attempt cannot have an error_code")
        if outcome == "COMPLETED":
            index = _STAGES.index(stage)
            if index == len(_STAGES) - 1:
                if next_stage is not None or stage_progress != 100 or overall_progress != 100:
                    raise ValueError("final stage must finish at 100 percent")
            elif next_stage is not _STAGES[index + 1]:
                raise ValueError("completed stage must advance to its immediate successor")
        for name, value in (("stage_progress", stage_progress), ("overall_progress", overall_progress)):
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an integer from 0 to 100")

        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS} FROM jobs WHERE id = $1 FOR UPDATE", job_id
            )
            if row is None:
                return StageFinishResult("NOOP", None)
            job = _record(row)
            if job.current_stage is not stage or job.status not in (
                JobStatus.RUNNING, JobStatus.RETRYING, JobStatus.CANCEL_REQUESTED
            ):
                return StageFinishResult("NOOP", job)
            attempt_row = await connection.fetchrow(
                f"SELECT {_ATTEMPT_COLUMNS} FROM stage_attempts "
                "WHERE id = $1 AND job_id = $2 AND stage = $3 FOR UPDATE",
                attempt_id, job_id, stage.value,
            )
            if attempt_row is None or attempt_row["status"] != "RUNNING":
                return StageFinishResult("NOOP", job)

            cancel = job.status is JobStatus.CANCEL_REQUESTED or outcome == "CANCELED"
            attempt_status = "COMPLETED" if outcome == "COMPLETED" and not cancel else "FAILED"
            final_code = "CANCELED" if cancel else error_code
            closed = await connection.fetchrow(
                "UPDATE stage_attempts SET status = $2, completed_at = CURRENT_TIMESTAMP, "
                "duration_ms = LEAST(2147483647, GREATEST(0, "
                "(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) * 1000)::BIGINT)), "
                "error_code = $3, error_detail = NULL "
                "WHERE id = $1 AND status = 'RUNNING' "
                f"RETURNING {_ATTEMPT_COLUMNS}", attempt_id, attempt_status, final_code,
            )
            if closed is None:
                raise RuntimeError("stage attempt changed during locked completion")
            final_status = (
                JobStatus.CANCELED if cancel else
                JobStatus.FAILED if outcome == "RETRYING" and attempt_row["attempt"] >= 4 else
                JobStatus.RETRYING if outcome == "RETRYING" else
                JobStatus.FAILED if outcome == "FAILED" else
                JobStatus.COMPLETED if stage is PipelineStage.RENDER else
                JobStatus.RUNNING
            )
            source_statuses = (
                (JobStatus.CANCEL_REQUESTED,) if job.status is JobStatus.CANCEL_REQUESTED
                else (JobStatus.RUNNING, JobStatus.RETRYING)
            )
            if job.status is JobStatus.CANCEL_REQUESTED:
                stage_progress = job.stage_progress or 0
                overall_progress = job.overall_progress or 0
            changed = await self._jobs.transition_job(
                job_id, expected_stage=stage, from_statuses=source_statuses,
                to_status=final_status,
                next_stage=next_stage if final_status is JobStatus.RUNNING else None,
                stage_progress=stage_progress, overall_progress=overall_progress,
                error_code=("RETRY_EXHAUSTED" if outcome == "RETRYING" and final_status is JobStatus.FAILED else final_code),
                error_message=("Job canceled" if cancel else "Stage failed" if final_code else None),
                connection=connection,
            )
            if changed is None:
                raise RuntimeError("job changed during locked attempt completion")
            return StageFinishResult("UPDATED", changed, _attempt_record(closed))
