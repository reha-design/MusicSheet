"""Bound-parameter tests for artifact metadata persistence."""

import asyncio
from datetime import datetime, timezone

from musicsheet_common import ArtifactRef, ArtifactRole

from musicsheet_api.jobs.artifacts import ArtifactRepository


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
ARTIFACT = ArtifactRef(
    id="artifact-001",
    job_id="job-001",
    role=ArtifactRole.SOURCE_ORIGINAL,
    filename="source_original.wav",
    uri="file:///storage/job-001/source_original.wav",
    mime_type="audio/wav",
    size_bytes=12,
    sha256="a" * 64,
    producer="musicsheet-api",
    producer_version="0.1.0",
)


class FakeConnection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.rows = list(rows or [])

    async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
        self.calls.append((query, args))
        if not query.startswith("INSERT INTO artifacts"):
            return self.rows.pop(0)
        return {
            "id": args[0],
            "job_id": args[1],
            "role": args[2],
            "filename": args[3],
            "uri": args[4],
            "mime_type": args[5],
            "size_bytes": args[6],
            "sha256": args[7],
            "producer": args[8],
            "producer_version": args[9],
            "created_at": NOW,
        }

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.calls.append((query, args))
        return self.rows


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


def test_artifact_insert_binds_all_metadata() -> None:
    connection = FakeConnection()
    repository = ArtifactRepository(FakePool(connection))

    record = asyncio.run(repository.add(ARTIFACT))

    assert record.id == ARTIFACT.id
    assert record.job_id == ARTIFACT.job_id
    assert record.role is ArtifactRole.SOURCE_ORIGINAL
    assert record.uri == ARTIFACT.uri
    assert record.created_at == NOW
    query, args = connection.calls[0]
    assert query.startswith("INSERT INTO artifacts")
    assert ARTIFACT.uri not in query
    assert args == (
        ARTIFACT.id,
        ARTIFACT.job_id,
        ARTIFACT.role.value,
        ARTIFACT.filename,
        ARTIFACT.uri,
        ARTIFACT.mime_type,
        ARTIFACT.size_bytes,
        ARTIFACT.sha256,
        ARTIFACT.producer,
        ARTIFACT.producer_version,
    )


def test_artifact_list_binds_job_id_and_maps_rows() -> None:
    row = {
        "id": "artifact-001",
        "job_id": "job-001",
        "role": "SOURCE_ORIGINAL",
        "filename": "source_original.wav",
        "uri": "file:///storage/job-001/source_original.wav",
        "mime_type": "audio/wav",
        "size_bytes": 12,
        "sha256": "a" * 64,
        "producer": None,
        "producer_version": None,
        "created_at": NOW,
    }
    connection = FakeConnection([row])
    repository = ArtifactRepository(FakePool(connection))

    records = asyncio.run(repository.list_for_job("job-001"))

    assert len(records) == 1
    assert records[0].id == "artifact-001"
    assert records[0].producer is None
    assert connection.calls[0][1] == ("job-001",)
    assert "WHERE job_id = $1" in connection.calls[0][0]


def test_artifact_get_binds_job_and_artifact_ids() -> None:
    row = {
        "id": "artifact-001",
        "job_id": "job-001",
        "role": "SOURCE_ORIGINAL",
        "filename": "source_original.wav",
        "uri": "file:///storage/job-001/source_original.wav",
        "mime_type": "audio/wav",
        "size_bytes": 12,
        "sha256": "a" * 64,
        "producer": "musicsheet-api",
        "producer_version": "0.1.0",
        "created_at": NOW,
    }
    connection = FakeConnection([row])
    repository = ArtifactRepository(FakePool(connection))

    record = asyncio.run(repository.get_for_job("job-001", "artifact-001"))

    assert record is not None and record.job_id == "job-001"
    assert connection.calls[0][1] == ("job-001", "artifact-001")
    assert "WHERE job_id = $1 AND id = $2" in connection.calls[0][0]
