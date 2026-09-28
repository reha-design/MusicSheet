"""HTTP contract tests for the initial job routes."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from musicsheet_api.app import create_app
from musicsheet_api.config import Settings
from musicsheet_api.jobs.events import JobEventStore, StoredJobEvent
from musicsheet_api.jobs.router import (
    _parse_last_event_id,
    get_job_events,
    stream_job_events,
)
from musicsheet_common import JobProgressEvent, JobStatus, PipelineStage


JOB_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_URL = "https://www.youtube.com/watch?v=A9x7du4921A"
NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def job_row(**overrides: Any) -> dict[str, Any]:
    return {
        "id": JOB_ID,
        "user_id": None,
        "source_type": "YOUTUBE",
        "source_url": SOURCE_URL,
        "target_instrument": "piano",
        "status": "PENDING",
        "current_stage": "DOWNLOAD",
        "stage_progress": 0,
        "overall_progress": 0,
        "error_code": None,
        "error_message": None,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": None,
        **overrides,
    }


def api_app():
    settings = Settings.from_env({"LOCAL_STORAGE_DIR": "outputs"})
    return create_app(settings=settings, health_checks=ReadyChecks())


class FakeConnection:
    def __init__(
        self,
        *,
        insert_error: Exception | None = None,
        cancel_row: dict[str, Any] | None = None,
        lookup_row: dict[str, Any] | None = None,
        lookup_missing: bool = False,
    ) -> None:
        self.insert_error = insert_error
        self.cancel_row = cancel_row
        self.lookup_row = None if lookup_missing else (lookup_row or job_row())
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        self.calls.append((query, args))
        if query.startswith("INSERT INTO jobs"):
            if self.insert_error is not None:
                raise self.insert_error
            return job_row(id=args[0], source_type=args[2], source_url=args[3])
        if query.startswith("UPDATE jobs"):
            return self.cancel_row
        if query.startswith("SELECT") and args[0] == JOB_ID:
            return self.lookup_row
        return None


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


class ReadyChecks:
    async def readiness(self) -> dict[str, str]:
        return {"postgres": "ok", "redis": "ok", "storage": "ok"}


def test_youtube_registration_passes_canonical_test_url_to_repository() -> None:
    connection = FakeConnection()
    app = api_app()

    with TestClient(app) as client:
        app.state.db_pool = FakePool(connection)
        response = client.post(
            "/api/v1/jobs",
            json={"source_url": "https://youtu.be/A9x7du4921A"},
        )

    assert response.status_code == 201
    query, args = connection.calls[0]
    assert query.startswith("INSERT INTO jobs")
    assert args[2:5] == ("YOUTUBE", SOURCE_URL, "piano")


def test_registration_returns_pending_download_job() -> None:
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(FakeConnection())
        response = client.post(
            "/api/v1/jobs",
            json={"source_url": "https://youtu.be/A9x7du4921A"},
        )

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"]).version == 4
    assert body["source_type"] == "YOUTUBE"
    assert body["source_url"] == SOURCE_URL
    assert body["target_instrument"] == "piano"
    assert body["status"] == "PENDING"
    assert body["current_stage"] == "DOWNLOAD"
    assert body["stage_progress"] == 0
    assert body["overall_progress"] == 0
    assert "user_id" not in body
    assert "error_message" not in body


def test_get_job_returns_snapshot_or_404() -> None:
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(FakeConnection())
        found = client.get(f"/api/v1/jobs/{JOB_ID}")
        missing = client.get("/api/v1/jobs/22222222-2222-4222-8222-222222222222")

    assert found.status_code == 200
    assert found.json()["id"] == JOB_ID
    assert missing.status_code == 404


def test_cancel_pending_job_sets_cancel_requested() -> None:
    connection = FakeConnection(cancel_row=job_row(status="CANCEL_REQUESTED"))
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(connection)
        response = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"
    assert connection.calls[0][0].startswith("UPDATE jobs")


@pytest.mark.parametrize("source_status", ["RUNNING", "RETRYING"])
def test_cancel_running_and_retrying_jobs_is_allowed(source_status: str) -> None:
    connection = FakeConnection(cancel_row=job_row(status="CANCEL_REQUESTED"))
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(connection)
        response = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"
    assert source_status in connection.calls[0][1][2]


def test_cancel_request_is_idempotent() -> None:
    connection = FakeConnection(lookup_row=job_row(status="CANCEL_REQUESTED"))
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(connection)
        response = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 202
    assert response.json()["status"] == "CANCEL_REQUESTED"
    assert len(connection.calls) == 2


@pytest.mark.parametrize("terminal_status", ["COMPLETED", "FAILED", "CANCELED"])
def test_cancel_terminal_job_returns_conflict(terminal_status: str) -> None:
    connection = FakeConnection(lookup_row=job_row(status=terminal_status))
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(connection)
        response = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 409
    assert response.json() == {"detail": "Job is already terminal"}


def test_cancel_unknown_job_returns_404() -> None:
    connection = FakeConnection(lookup_missing=True)
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(connection)
        response = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_job_routes_return_503_when_database_pool_is_absent() -> None:
    app = api_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/jobs",
            json={"source_url": "https://youtu.be/A9x7du4921A"},
        )
        missing_job = client.get(f"/api/v1/jobs/{JOB_ID}")
        cancel_without_pool = client.delete(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Job database is unavailable"}
    assert missing_job.status_code == 503
    assert missing_job.json() == {"detail": "Job database is unavailable"}
    assert cancel_without_pool.status_code == 503
    assert cancel_without_pool.json() == {"detail": "Job database is unavailable"}


def test_job_route_errors_are_sanitized() -> None:
    secret = "postgresql://user:password@db.internal/music: driver failure"
    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(FakeConnection(insert_error=RuntimeError(secret)))
        response = client.post(
            "/api/v1/jobs",
            json={"source_url": "https://youtu.be/A9x7du4921A"},
        )

    assert response.status_code == 503
    assert "password" not in response.text
    assert "db.internal" not in response.text
    assert "driver failure" not in response.text

    bad_url = "https://evil.example/watch?v=A9x7du4921A"
    with TestClient(api_app()) as client:
        invalid = client.post("/api/v1/jobs", json={"source_url": bad_url})
        too_long_url = "https://youtu.be/" + ("x" * 2048)
        oversized = client.post("/api/v1/jobs", json={"source_url": too_long_url})
        unexpected_user = client.post(
            "/api/v1/jobs",
            json={"source_url": "https://youtu.be/A9x7du4921A", "user_id": "private-user"},
        )
    assert invalid.status_code == 422
    assert bad_url not in invalid.text
    assert oversized.status_code == 422
    assert too_long_url not in oversized.text
    assert unexpected_user.status_code == 422
    assert "private-user" not in unexpected_user.text


def progress_event(message: str) -> JobProgressEvent:
    return JobProgressEvent(
        job_id=JOB_ID,
        status=JobStatus.RUNNING,
        stage=PipelineStage.SEPARATE,
        stage_progress=40,
        overall_progress=20,
        message=message,
        timestamp=NOW,
    )


class SequenceEventStore:
    def __init__(self, batches: list[list[StoredJobEvent]]) -> None:
        self.batches = list(batches)
        self.calls: list[tuple[str, int]] = []

    async def read_after(
        self,
        job_id: str,
        last_id: str,
        *,
        block_ms: int,
    ) -> list[StoredJobEvent]:
        assert job_id == JOB_ID
        self.calls.append((last_id, block_ms))
        if self.batches:
            return self.batches.pop(0)
        return []


class DisconnectAfterChecks:
    def __init__(self, disconnect_after: int) -> None:
        self.disconnect_after = disconnect_after
        self.checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self.disconnect_after


def collect_stream(request: Any, event_store: Any, *, last_id: str) -> list[str]:
    async def collect() -> list[str]:
        return [
            frame
            async for frame in stream_job_events(
                request=request,
                event_store=event_store,
                job_id=JOB_ID,
                last_id=last_id,
            )
        ]

    return asyncio.run(collect())


def test_job_events_replay_from_start_and_follow_new_entries() -> None:
    first = StoredJobEvent(stream_id="1-0", event=progress_event("Started"))
    second = StoredJobEvent(stream_id="2-0", event=progress_event("Separating"))
    store = SequenceEventStore([[first], [second]])
    request = DisconnectAfterChecks(disconnect_after=4)

    frames = collect_stream(request, store, last_id="0-0")

    assert store.calls == [("0-0", 1_000), ("1-0", 1_000)]
    assert frames == [
        f"id: 1-0\ndata: {first.event.model_dump_json()}\n\n",
        f"id: 2-0\ndata: {second.event.model_dump_json()}\n\n",
    ]


def test_job_events_resume_after_last_event_id() -> None:
    entry = StoredJobEvent(stream_id="3-0", event=progress_event("Resumed"))
    store = SequenceEventStore([[entry]])
    request = DisconnectAfterChecks(disconnect_after=2)

    frames = collect_stream(request, store, last_id="2-0")

    assert store.calls == [("2-0", 1_000)]
    assert frames == [f"id: 3-0\ndata: {entry.event.model_dump_json()}\n\n"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "0-0"),
        ("0-0", "0-0"),
        (
            "18446744073709551615-18446744073709551615",
            "18446744073709551615-18446744073709551615",
        ),
        ("18446744073709551616-0", None),
        ("0-18446744073709551616", None),
        ("١-0", None),
        ("1--2", None),
        ("1" * 21 + "-0", None),
    ],
)
def test_job_events_validate_last_event_id_boundaries(
    value: str | None,
    expected: str | None,
) -> None:
    assert _parse_last_event_id(value) == expected


def test_job_events_unknown_job_returns_404_before_redis_access() -> None:
    app = api_app()
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))

    with TestClient(app) as client:
        app.state.db_pool = FakePool(FakeConnection(lookup_missing=True))
        app.state.redis_client = redis
        response = client.get(f"/api/v1/jobs/{JOB_ID}/events")

    assert response.status_code == 404
    redis.ping.assert_not_awaited()


def test_job_events_missing_or_unavailable_dependencies_return_503() -> None:
    with TestClient(api_app()) as client:
        no_database = client.get(f"/api/v1/jobs/{JOB_ID}/events")
    assert no_database.status_code == 503
    assert no_database.json() == {"detail": "Job database is unavailable"}

    app = api_app()
    redis = SimpleNamespace(ping=AsyncMock(side_effect=RuntimeError("redis secret")))
    with TestClient(app) as client:
        app.state.db_pool = FakePool(FakeConnection())
        app.state.redis_client = redis
        unavailable_redis = client.get(f"/api/v1/jobs/{JOB_ID}/events")

    assert unavailable_redis.status_code == 503
    assert unavailable_redis.json() == {"detail": "Job event stream is unavailable"}
    assert "redis secret" not in unavailable_redis.text

    class FailingLookupConnection:
        async def fetchrow(self, query: str, *args: object) -> None:
            raise RuntimeError("postgres secret endpoint")

    app = api_app()
    with TestClient(app) as client:
        app.state.db_pool = FakePool(FailingLookupConnection())  # type: ignore[arg-type]
        unavailable_database = client.get(f"/api/v1/jobs/{JOB_ID}/events")
    assert unavailable_database.status_code == 503
    assert "postgres secret" not in unavailable_database.text


def test_job_events_malformed_header_returns_400() -> None:
    with TestClient(api_app()) as client:
        response = client.get(
            f"/api/v1/jobs/{JOB_ID}/events",
            headers={"Last-Event-ID": "1--2"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Last-Event-ID"}


def test_job_events_emit_exact_heartbeat_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    import musicsheet_api.jobs.router as jobs_router

    store = SequenceEventStore([[]])
    request = DisconnectAfterChecks(disconnect_after=2)
    ticks = iter([0.0, 15.0])
    monkeypatch.setattr(jobs_router, "_monotonic", lambda: next(ticks))

    frames = collect_stream(request, store, last_id="0-0")

    assert frames == [": keep-alive\n\n"]


def test_job_events_disconnect_during_bounded_read_does_not_close_shared_redis_client() -> None:
    async def slow_xread(**kwargs: Any) -> None:
        await asyncio.sleep(0)

    redis = SimpleNamespace(
        xread=AsyncMock(side_effect=slow_xread),
        aclose=AsyncMock(),
    )
    store = JobEventStore(redis)  # type: ignore[arg-type]
    request = DisconnectAfterChecks(disconnect_after=1)

    frames = collect_stream(request, store, last_id="0-0")

    assert frames == []
    redis.xread.assert_awaited_once_with(
        streams={f"job:{JOB_ID}:events": "0-0"},
        count=100,
        block=1_000,
    )
    redis.aclose.assert_not_awaited()


def test_job_events_midstream_redis_failure_closes_stream_safely(caplog) -> None:
    redis = SimpleNamespace(
        xread=AsyncMock(side_effect=RuntimeError("redis secret endpoint")),
        aclose=AsyncMock(),
    )
    store = JobEventStore(redis)  # type: ignore[arg-type]
    request = DisconnectAfterChecks(disconnect_after=2)

    frames = collect_stream(request, store, last_id="0-0")

    assert frames == []
    assert "Job event stream read failed" in caplog.text
    assert "redis secret endpoint" not in caplog.text
    redis.aclose.assert_not_awaited()


def test_job_events_success_response_has_sse_headers() -> None:
    app = api_app()
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))
    app.state.db_pool = FakePool(FakeConnection())
    app.state.redis_client = redis
    request = SimpleNamespace(app=app)

    response = asyncio.run(get_job_events(JOB_ID, request, None))

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
