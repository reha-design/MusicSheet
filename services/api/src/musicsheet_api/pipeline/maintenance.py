"""Operator-selected stale-job scan and guarded recovery command."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any, Literal

import asyncpg
import redis.asyncio as aioredis
from musicsheet_common import JobProgressEvent, JobStatus, PipelineStage

from musicsheet_api.config import Settings
from musicsheet_api.jobs.events import JobEventStore
from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.jobs.repository import _COLUMNS, _record, advisory_lock_key


logger = logging.getLogger(__name__)
_NONTERMINAL = (
    JobStatus.PENDING, JobStatus.RUNNING, JobStatus.RETRYING,
    JobStatus.CANCEL_REQUESTED,
)
_FAILURE_MESSAGE = "Workflow could not be recovered"
_CANCEL_MESSAGE = "Job canceled"


class _RecoveryCASMiss(Exception):
    """Abort attempt updates if the guarded job update unexpectedly misses."""


@dataclass(frozen=True, slots=True)
class AttemptSummary:
    stage: PipelineStage
    attempt: int
    status: str
    error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "attempt": self.attempt,
            "status": self.status,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class StalledJob:
    job_id: str
    status: JobStatus
    current_stage: PipelineStage
    updated_at: datetime
    start_job_attempts: int
    latest_attempt: AttemptSummary | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "current_stage": self.current_stage.value,
            "updated_at": self.updated_at.isoformat(),
            "start_job_attempts": self.start_job_attempts,
            "latest_attempt": (
                self.latest_attempt.to_dict() if self.latest_attempt is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    changed: bool
    job: JobRecord | None
    reason: Literal[
        "NOT_FOUND", "LOCK_HELD", "OBSERVATION_CHANGED", "NOT_STALE", "NOT_ELIGIBLE"
    ] | None = None


class JobMaintenance:
    """Run a bounded scan and a stale compare-and-set over one DB session."""

    def __init__(self, connection: Any, events: JobEventStore | None, *, visibility_timeout: int) -> None:
        if type(visibility_timeout) is not int or visibility_timeout <= 0:
            raise ValueError("visibility_timeout must be a positive integer")
        self._connection = connection
        self._events = events
        self._visibility_timeout = visibility_timeout
        self._stale_seconds = visibility_timeout * 2

    async def scan(self) -> tuple[StalledJob, ...]:
        """Return stale nonterminal rows without source or driver details."""
        cutoff = await self._connection.fetchval(
            "SELECT CURRENT_TIMESTAMP - ($1::DOUBLE PRECISION * INTERVAL '1 second')",
            self._stale_seconds,
        )
        rows = await self._connection.fetch(
            "SELECT j.id, j.status, j.current_stage, j.updated_at, j.start_job_attempts, "
            "a.stage AS latest_attempt_stage, a.attempt AS latest_attempt_number, "
            "a.status AS latest_attempt_status, a.error_code AS latest_attempt_error_code "
            "FROM jobs AS j LEFT JOIN LATERAL ("
            "SELECT stage, attempt, status, error_code FROM stage_attempts "
            "WHERE job_id = j.id ORDER BY started_at DESC NULLS LAST, id DESC LIMIT 1"
            ") AS a ON TRUE WHERE j.status = ANY($2::VARCHAR[]) "
            "AND j.updated_at IS NOT NULL AND j.updated_at <= $1 "
            "ORDER BY j.updated_at ASC, j.id ASC",
            cutoff,
            [status.value for status in _NONTERMINAL],
        )
        result: list[StalledJob] = []
        for row in rows:
            latest = None
            if row["latest_attempt_number"] is not None:
                latest = AttemptSummary(
                    stage=PipelineStage(row["latest_attempt_stage"]),
                    attempt=row["latest_attempt_number"],
                    status=row["latest_attempt_status"],
                    error_code=row["latest_attempt_error_code"],
                )
            result.append(StalledJob(
                job_id=row["id"],
                status=JobStatus(row["status"]),
                current_stage=PipelineStage(row["current_stage"]),
                updated_at=row["updated_at"],
                start_job_attempts=row["start_job_attempts"],
                latest_attempt=latest,
            ))
        return tuple(result)

    async def fail_stalled(
        self,
        job_id: str,
        observed_updated_at: datetime,
        observed_status: JobStatus | str,
    ) -> RecoveryResult:
        """Recover only the exact stale row selected by an operator's scan."""
        if not isinstance(job_id, str) or not job_id or len(job_id) > 36:
            raise ValueError("job_id must be a non-empty job identifier")
        if not isinstance(observed_updated_at, datetime) or observed_updated_at.tzinfo is None:
            raise ValueError("observed_updated_at must include a timezone")
        try:
            status = observed_status if isinstance(observed_status, JobStatus) else JobStatus(observed_status)
        except (TypeError, ValueError):
            raise ValueError("observed_status must be a valid job status") from None
        if status not in _NONTERMINAL:
            return RecoveryResult(False, None, "NOT_ELIGIBLE")

        observed = await self._connection.fetchrow(
            "SELECT current_stage FROM jobs WHERE id = $1", job_id,
        )
        if observed is None:
            return RecoveryResult(False, None, "NOT_FOUND")
        stage = PipelineStage(observed["current_stage"])
        lock_keys = tuple(dict.fromkeys((
            advisory_lock_key(job_id, "START_JOB"),
            advisory_lock_key(job_id, stage.value),
        )))
        acquired: list[int] = []
        result: RecoveryResult
        try:
            for key in lock_keys:
                locked = await self._connection.fetchval(
                    "SELECT pg_try_advisory_lock($1)", key,
                )
                if not locked:
                    return RecoveryResult(False, None, "LOCK_HELD")
                acquired.append(key)

            try:
                async with self._connection.transaction():
                    row = await self._connection.fetchrow(
                        f"SELECT {_COLUMNS} FROM jobs WHERE id = $1 FOR UPDATE", job_id,
                    )
                    if row is None:
                        result = RecoveryResult(False, None, "NOT_FOUND")
                    elif (
                        row["updated_at"] != observed_updated_at
                        or row["status"] != status.value
                        or row["current_stage"] != stage.value
                    ):
                        result = RecoveryResult(False, _record(row), "OBSERVATION_CHANGED")
                    elif status not in _NONTERMINAL:
                        result = RecoveryResult(False, _record(row), "NOT_ELIGIBLE")
                    else:
                        cutoff = await self._connection.fetchval(
                            "SELECT CURRENT_TIMESTAMP - ($1::DOUBLE PRECISION * INTERVAL '1 second')",
                            self._stale_seconds,
                        )
                        if row["updated_at"] is None or row["updated_at"] > cutoff:
                            result = RecoveryResult(False, _record(row), "NOT_STALE")
                        else:
                            cancel_won = status is JobStatus.CANCEL_REQUESTED
                            attempt_code = "CANCELED" if cancel_won else "WORKER_LOST"
                            await self._connection.execute(
                                "UPDATE stage_attempts SET status = 'FAILED', "
                                "completed_at = CURRENT_TIMESTAMP, "
                                "duration_ms = LEAST(2147483647, GREATEST(0, "
                                "(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - "
                                "COALESCE(started_at, CURRENT_TIMESTAMP))) * 1000)::BIGINT)), "
                                "error_code = $2, error_detail = NULL "
                                "WHERE job_id = $1 AND status = 'RUNNING'",
                                job_id, attempt_code,
                            )
                            next_status = JobStatus.CANCELED if cancel_won else JobStatus.FAILED
                            next_code = "CANCELED" if cancel_won else "WORKER_PRECLAIM_STALLED"
                            next_message = _CANCEL_MESSAGE if cancel_won else _FAILURE_MESSAGE
                            changed = await self._connection.fetchrow(
                                "UPDATE jobs SET status = $2, error_code = $3, error_message = $4, "
                                "updated_at = CURRENT_TIMESTAMP, completed_at = CURRENT_TIMESTAMP "
                                "WHERE id = $1 AND status = $5 AND updated_at = $6 "
                                f"RETURNING {_COLUMNS}",
                                job_id, next_status.value, next_code, next_message,
                                status.value, observed_updated_at,
                            )
                            if changed is None:
                                raise _RecoveryCASMiss()
                            result = RecoveryResult(True, _record(changed))
            except _RecoveryCASMiss:
                result = RecoveryResult(False, None, "OBSERVATION_CHANGED")

            if result.changed and result.job is not None:
                await self._publish_terminal(result.job)
            return result
        finally:
            for key in reversed(acquired):
                try:
                    await self._connection.execute("SELECT pg_advisory_unlock($1)", key)
                except Exception:
                    logger.warning("Job maintenance advisory lock release failed")

    async def _publish_terminal(self, job: JobRecord) -> None:
        if self._events is None:
            return
        message = _CANCEL_MESSAGE if job.status is JobStatus.CANCELED else _FAILURE_MESSAGE
        try:
            await self._events.publish(JobProgressEvent(
                job_id=job.id,
                status=job.status,
                stage=job.current_stage,
                stage_progress=job.stage_progress if job.stage_progress is not None else 0,
                overall_progress=job.overall_progress if job.overall_progress is not None else 0,
                message=message,
            ))
        except Exception:
            logger.warning("Stalled-job terminal event publication failed")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError("timestamp must be an ISO-8601 value") from None
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="musicsheet-orchestration-maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="list jobs stale for twice the broker visibility timeout")
    recover = commands.add_parser("fail-stalled", help="guardedly fail or cancel one scanned job")
    recover.add_argument("--job-id", required=True)
    recover.add_argument("--observed-updated-at", type=_parse_timestamp, required=True)
    recover.add_argument(
        "--observed-status", choices=[status.value for status in _NONTERMINAL], required=True,
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if not settings.database_url:
        print("Maintenance requires DATABASE_URL.", file=sys.stderr)
        return 2
    connection = await asyncpg.connect(settings.database_url, timeout=2)
    redis_client = None
    try:
        events = None
        if args.command == "fail-stalled":
            redis_client = aioredis.Redis.from_url(
                settings.redis_url or "redis://localhost:6379/2",
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            events = JobEventStore(redis_client)
        maintenance = JobMaintenance(
            connection, events, visibility_timeout=settings.celery_visibility_timeout,
        )
        if args.command == "scan":
            rows = await maintenance.scan()
            print(json.dumps([row.to_dict() for row in rows], ensure_ascii=False))
            return 0

        result = await maintenance.fail_stalled(
            args.job_id, args.observed_updated_at, args.observed_status,
        )
        print(json.dumps({
            "changed": result.changed,
            "job_id": args.job_id,
            "status": result.job.status.value if result.job is not None else None,
            "reason": result.reason,
            "next_step": None if result.changed else "rescan and verify the worker is inactive",
        }, ensure_ascii=False))
        return 0 if result.changed else 3
    finally:
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                logger.warning("Job maintenance Redis client close failed")
        try:
            await connection.close()
        except Exception:
            logger.warning("Job maintenance PostgreSQL session close failed")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = create_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception:
        logger.error("Job maintenance operation failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
