"""Bound SQL operations for the canonical jobs table."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

import asyncpg
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.models import JobRecord


_COLUMNS = (
    "id, user_id, source_type, source_url, target_instrument, status, "
    "current_stage, stage_progress, overall_progress, error_code, error_message, "
    "created_at, updated_at, completed_at"
)
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


def advisory_lock_key(job_id: str, scope: str) -> int:
    """Stable signed bigint for one worker-lifetime PostgreSQL session lock."""
    digest = sha256(f"musicsheet:workflow:{job_id}:{scope}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@dataclass(frozen=True)
class StartClaimResult:
    action: Literal["PUBLISH", "CANCELED", "FAILED", "NOOP"]
    job: JobRecord | None
    attempts: int = 0


def _record(row: Mapping[str, Any]) -> JobRecord:
    return JobRecord(
        id=row["id"],
        user_id=row["user_id"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        target_instrument=row["target_instrument"],
        status=JobStatus(row["status"]),
        current_stage=PipelineStage(row["current_stage"]),
        stage_progress=row["stage_progress"],
        overall_progress=row["overall_progress"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


async def _cancel_locked_job(connection: asyncpg.Connection, job_id: str) -> JobRecord:
    """Close open attempts and the cancellation-requested job in one transaction."""
    await connection.execute(
        "UPDATE stage_attempts SET status = 'FAILED', error_code = $2, "
        "error_detail = NULL, completed_at = CURRENT_TIMESTAMP, "
        "duration_ms = LEAST(2147483647, GREATEST(0, "
        "(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - "
        "COALESCE(started_at, CURRENT_TIMESTAMP))) * 1000)::BIGINT)) "
        "WHERE job_id = $1 AND status = 'RUNNING'",
        job_id, "CANCELED",
    )
    changed = await connection.fetchrow(
        "UPDATE jobs SET status = 'CANCELED', updated_at = CURRENT_TIMESTAMP, "
        "completed_at = CURRENT_TIMESTAMP WHERE id = $1 AND status = 'CANCEL_REQUESTED' "
        f"RETURNING {_COLUMNS}", job_id
    )
    if changed is None:
        raise RuntimeError("cancellation changed during locked transition")
    return _record(changed)


class JobRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def acquire_start_lock(self, job_id: str, connection: asyncpg.Connection) -> None:
        await connection.execute("SELECT pg_advisory_lock($1)", advisory_lock_key(job_id, "START_JOB"))

    async def release_start_lock(self, job_id: str, connection: asyncpg.Connection) -> None:
        await connection.execute("SELECT pg_advisory_unlock($1)", advisory_lock_key(job_id, "START_JOB"))

    async def claim_start_job(self, job_id: str) -> StartClaimResult:
        """Commit the bounded publish claim before the caller sends a chain."""
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS}, start_job_attempts, workflow_dispatched_at "
                "FROM jobs WHERE id = $1 FOR UPDATE", job_id
            )
            if row is None:
                return StartClaimResult("NOOP", None)
            job = _record(row)
            attempts = row["start_job_attempts"]
            if job.status is JobStatus.CANCEL_REQUESTED:
                changed = await _cancel_locked_job(connection, job_id)
                return StartClaimResult("CANCELED", changed, attempts)
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING) or row["workflow_dispatched_at"] is not None:
                return StartClaimResult("NOOP", job, attempts)
            started = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM stage_attempts WHERE job_id = $1)", job_id
            )
            if started:
                return StartClaimResult("NOOP", job, attempts)
            if attempts >= 4:
                changed = await connection.fetchrow(
                    "UPDATE jobs SET status = 'FAILED', error_code = 'WORKFLOW_WORKER_LOST', "
                    "error_message = 'Workflow could not be started', "
                    "updated_at = CURRENT_TIMESTAMP, completed_at = CURRENT_TIMESTAMP "
                    "WHERE id = $1 AND status IN ('PENDING', 'RUNNING') "
                    f"RETURNING {_COLUMNS}", job_id
                )
                return StartClaimResult("FAILED", _record(changed), attempts)
            changed = await connection.fetchrow(
                "UPDATE jobs SET status = 'RUNNING', start_job_attempts = start_job_attempts + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = $1 AND status IN ('PENDING', 'RUNNING') "
                f"RETURNING {_COLUMNS}, start_job_attempts", job_id
            )
            return StartClaimResult("PUBLISH", _record(changed), changed["start_job_attempts"])

    async def mark_workflow_dispatched(self, job_id: str) -> JobRecord | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "UPDATE jobs SET workflow_dispatched_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = $1 AND status = 'RUNNING' "
                "AND start_job_attempts > 0 AND workflow_dispatched_at IS NULL "
                f"RETURNING {_COLUMNS}", job_id
            )
        return _record(row) if row is not None else None

    async def fail_workflow_dispatch(self, job_id: str) -> JobRecord | None:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS}, start_job_attempts, workflow_dispatched_at "
                "FROM jobs WHERE id = $1 FOR UPDATE", job_id
            )
            if row is None:
                return None
            job = _record(row)
            if job.status is JobStatus.CANCEL_REQUESTED:
                return await _cancel_locked_job(connection, job_id)
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING) or row["workflow_dispatched_at"] is not None:
                return job
            started = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM stage_attempts WHERE job_id = $1)", job_id
            )
            if started:
                return job
            changed = await connection.fetchrow(
                "UPDATE jobs SET status = 'FAILED', error_code = 'WORKFLOW_DISPATCH_FAILED', "
                "error_message = 'Workflow could not be started', updated_at = CURRENT_TIMESTAMP, "
                "completed_at = CURRENT_TIMESTAMP WHERE id = $1 AND status IN ('PENDING', 'RUNNING') "
                f"RETURNING {_COLUMNS}", job_id
            )
            return _record(changed)

    async def transition_job(
        self, job_id: str, *, expected_stage: PipelineStage,
        from_statuses: tuple[JobStatus, ...], to_status: JobStatus,
        stage_progress: int, overall_progress: int,
        next_stage: PipelineStage | None = None,
        error_code: str | None = None, error_message: str | None = None,
        connection: asyncpg.Connection | None = None,
    ) -> JobRecord | None:
        """Compare-and-set status and stage without changing a concurrent cancel."""
        for name, value in (("stage_progress", stage_progress), ("overall_progress", overall_progress)):
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an integer from 0 to 100")
        if not from_statuses or any(status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED) for status in from_statuses):
            raise ValueError("from_statuses must contain nonterminal statuses")
        if JobStatus.CANCEL_REQUESTED in from_statuses and to_status is not JobStatus.CANCELED:
            raise ValueError("a committed cancellation may only become CANCELED")
        if error_code is not None and (
            not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code)
        ):
            raise ValueError("error_code must be a stable uppercase identifier")
        query = (
            "UPDATE jobs SET status = $4, current_stage = $5, stage_progress = $6, "
            "overall_progress = $7, error_code = $8, error_message = $9, "
            "updated_at = CURRENT_TIMESTAMP, completed_at = CASE WHEN $4::VARCHAR(20) "
            "IN ('COMPLETED', 'FAILED', 'CANCELED') THEN CURRENT_TIMESTAMP ELSE NULL END "
            "WHERE id = $1 AND current_stage = $2 AND status = ANY($3::VARCHAR[]) "
            f"RETURNING {_COLUMNS}"
        )
        args = (
            job_id, expected_stage.value, [status.value for status in from_statuses],
            to_status.value, (next_stage or expected_stage).value,
            stage_progress, overall_progress, error_code, error_message,
        )
        if connection is not None:
            row = await connection.fetchrow(query, *args)
        else:
            async with self._pool.acquire() as acquired:
                row = await acquired.fetchrow(query, *args)
        return _record(row) if row is not None else None

    async def create_job(
        self,
        *,
        source_type: str,
        source_url: str | None,
        user_id: str | None = None,
        target_instrument: str | None = "piano",
        job_id: str | None = None,
        connection: asyncpg.Connection | None = None,
    ) -> JobRecord:
        if source_type not in ("YOUTUBE", "UPLOAD"):
            raise ValueError("source_type must be YOUTUBE or UPLOAD")
        values = (
            job_id or str(uuid4()),
            user_id,
            source_type,
            source_url,
            target_instrument,
        )
        query = (
            f"INSERT INTO jobs (id, user_id, source_type, source_url, target_instrument) "
            f"VALUES ($1, $2, $3, $4, $5) RETURNING {_COLUMNS}"
        )
        if connection is None:
            async with self._pool.acquire() as acquired_connection:
                row = await acquired_connection.fetchrow(query, *values)
        else:
            row = await connection.fetchrow(query, *values)
        return _record(row)

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_COLUMNS} FROM jobs WHERE id = $1",
                job_id,
            )
        return _record(row) if row is not None else None

    async def request_cancel(self, job_id: str) -> JobRecord | None:
        """Atomically request cancellation without changing a terminal job."""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "UPDATE jobs SET status = $2, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = $1 AND status = ANY($3::VARCHAR[]) "
                f"RETURNING {_COLUMNS}",
                job_id,
                JobStatus.CANCEL_REQUESTED.value,
                [
                    JobStatus.PENDING.value,
                    JobStatus.RUNNING.value,
                    JobStatus.RETRYING.value,
                ],
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT {_COLUMNS} FROM jobs WHERE id = $1",
                    job_id,
                )
        return _record(row) if row is not None else None

    async def update_progress(
        self,
        *,
        job_id: str,
        status: JobStatus,
        current_stage: PipelineStage,
        stage_progress: int,
        overall_progress: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobRecord | None:
        for name, value in (("stage_progress", stage_progress), ("overall_progress", overall_progress)):
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(f"{name} must be an integer from 0 to 100")
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "UPDATE jobs SET status = $2, current_stage = $3, "
                "stage_progress = $4, overall_progress = $5, "
                "error_code = $6, error_message = $7, "
                "updated_at = CURRENT_TIMESTAMP, "
                "completed_at = CASE WHEN $2::VARCHAR(20) IN ('COMPLETED', 'FAILED', 'CANCELED') "
                "THEN CURRENT_TIMESTAMP ELSE NULL END "
                f"WHERE id = $1 RETURNING {_COLUMNS}",
                job_id,
                status.value,
                current_stage.value,
                stage_progress,
                overall_progress,
                error_code,
                error_message,
            )
        return _record(row) if row is not None else None
