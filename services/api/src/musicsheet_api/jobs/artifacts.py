"""Bound SQL operations for artifact metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
from musicsheet_common import ArtifactRef, ArtifactRole


_COLUMNS = (
    "id, job_id, role, filename, uri, mime_type, size_bytes, sha256, "
    "producer, producer_version, created_at"
)


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    job_id: str
    role: ArtifactRole
    filename: str
    uri: str
    mime_type: str
    size_bytes: int
    sha256: str
    producer: str | None
    producer_version: str | None
    created_at: datetime | None


def _record(row: Mapping[str, Any]) -> ArtifactRecord:
        return ArtifactRecord(
        id=row["id"],
        job_id=row["job_id"],
        role=ArtifactRole(row["role"]),
        filename=row["filename"],
        uri=row["uri"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        producer=row["producer"],
        producer_version=row["producer_version"],
        created_at=row["created_at"],
    )

class ArtifactRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add(
        self,
        artifact: ArtifactRef,
        *,
        connection: asyncpg.Connection | None = None,
    ) -> ArtifactRecord:
        values = (
            artifact.id,
            artifact.job_id,
            artifact.role.value,
            artifact.filename,
            artifact.uri,
            artifact.mime_type,
            artifact.size_bytes,
            artifact.sha256,
            artifact.producer,
            artifact.producer_version,
        )
        query = (
            "INSERT INTO artifacts (id, job_id, role, filename, uri, mime_type, "
            "size_bytes, sha256, producer, producer_version) "
            f"VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING {_COLUMNS}"
        )
        if connection is None:
            async with self._pool.acquire() as acquired_connection:
                row = await acquired_connection.fetchrow(query, *values)
        else:
            row = await connection.fetchrow(query, *values)
        return _record(row)

    async def list_for_job(self, job_id: str) -> list[ArtifactRecord]:
        query = (
            f"SELECT {_COLUMNS} FROM artifacts "
            "WHERE job_id = $1 ORDER BY created_at, id"
        )
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(query, job_id)
        return [_record(row) for row in rows]

    async def get_for_job(
        self,
        job_id: str,
        artifact_id: str,
    ) -> ArtifactRecord | None:
        query = (
            f"SELECT {_COLUMNS} FROM artifacts "
            "WHERE job_id = $1 AND id = $2"
        )
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(query, job_id, artifact_id)
        return _record(row) if row is not None else None
