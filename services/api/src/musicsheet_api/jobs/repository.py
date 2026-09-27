"""Bound SQL operations for the canonical jobs table."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import asyncpg
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.models import JobRecord


_COLUMNS = (
    "id, user_id, source_type, source_url, target_instrument, status, "
    "current_stage, stage_progress, overall_progress, error_code, error_message, "
    "created_at, updated_at, completed_at"
)


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


class JobRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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
