"""API dispatch boundaries and broker/worker races."""

import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from musicsheet_api.app import create_app
from musicsheet_api.config import Settings


NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
URL = "https://youtu.be/A9x7du4921A"


class Connection:
    def __init__(self, *, fail_insert: bool = False, fail_failure_write: bool = False) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: list[str] = []
        self.fail_insert = fail_insert
        self.fail_failure_write = fail_failure_write

    def transaction(self) -> "Transaction":
        return Transaction(self)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if query.startswith("INSERT INTO jobs"):
            if self.fail_insert:
                raise RuntimeError("private database credentials")
            row = dict(id=args[0], user_id=None, source_type=args[2], source_url=args[3],
                       target_instrument=args[4], status="PENDING", current_stage="DOWNLOAD",
                       stage_progress=0, overall_progress=0, error_code=None,
                       error_message=None, created_at=NOW, updated_at=NOW, completed_at=None)
            self.jobs[args[0]] = row
            self.events.append("job_insert")
            return row.copy()
        if query.startswith("INSERT INTO artifacts"):
            assert args[1] in self.jobs
            self.events.append("artifact_insert")
            return dict(id=args[0], job_id=args[1], role=args[2], filename=args[3],
                        uri=args[4], mime_type=args[5], size_bytes=args[6], sha256=args[7],
                        producer=args[8], producer_version=args[9], created_at=NOW)
        if query.startswith("UPDATE jobs") and "DISPATCH_FAILED" in query:
            if self.fail_failure_write:
                raise RuntimeError("private write failure")
            assert "status = 'PENDING'" in query
            row = self.jobs[args[0]]
            self.events.append("dispatch_cas")
            if row["status"] != "PENDING":
                return None
            row.update(status="FAILED", error_code="DISPATCH_FAILED", completed_at=NOW)
            return row.copy()
        if query.startswith("SELECT") and "FROM jobs" in query:
            self.events.append("snapshot_read")
            row = self.jobs.get(args[0])
            return row.copy() if row else None
        raise AssertionError(f"unexpected SQL: {query}")


class Transaction:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.events.append("begin")

    async def __aexit__(self, error_type: object, *_: object) -> None:
        self.connection.events.append("rollback" if error_type else "commit")


class Acquire:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(self, *_: object) -> None:
        self.connection.events.append("release")


class Pool:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def acquire(self) -> Acquire:
        return Acquire(self.connection)


class Dispatcher:
    def __init__(self, connection: Connection, on_submit: Callable[[str], None] | None = None) -> None:
        self.connection = connection
        self.on_submit = on_submit
        self.ids: list[str] = []
        self.thread_ids: list[int] = []

    def submit(self, job_id: str) -> None:
        self.ids.append(job_id)
        self.thread_ids.append(threading.get_ident())
        self.connection.events.append("publish")
        if self.on_submit:
            self.on_submit(job_id)


def app_for(tmp_path: Path, dispatcher: Dispatcher):
    settings = Settings.from_env({"LOCAL_STORAGE_DIR": str(tmp_path / "outputs")})
    app = create_app(settings=settings, dispatcher=dispatcher)
    app.state.db_pool = Pool(dispatcher.connection)
    return app


def test_default_dispatcher_uses_app_factory_settings(tmp_path: Path) -> None:
    settings = Settings.from_env({
        "CELERY_BROKER_URL": "memory://",
        "CELERY_RESULT_BACKEND": "cache+memory://",
        "CELERY_VISIBILITY_TIMEOUT": "7200",
        "LOCAL_STORAGE_DIR": str(tmp_path / "outputs"),
    })

    app = create_app(settings=settings)

    producer_app = app.state.dispatcher._app
    assert producer_app.conf.broker_url == "memory://"
    assert producer_app.conf.result_backend == "cache+memory://"
    assert producer_app.conf.broker_transport_options["visibility_timeout"] == 7200


def register(client: TestClient, upload: bool):
    if upload:
        return client.post("/api/v1/jobs/upload", files={"file": ("piece.wav", b"audio", "audio/wav")})
    return client.post("/api/v1/jobs", json={"source_url": URL})


@pytest.mark.parametrize("upload", [False, True])
def test_register_dispatches_only_after_committed_metadata(tmp_path: Path, upload: bool) -> None:
    connection = Connection()

    def committed(job_id: str) -> None:
        assert job_id in connection.jobs
        if upload:
            assert connection.events.index("artifact_insert") < connection.events.index("commit")
            assert connection.events.index("commit") < connection.events.index("publish")
            assert (tmp_path / "outputs" / job_id / "source_original.wav").is_file()
        else:
            assert connection.events.index("job_insert") < connection.events.index("release")
            assert connection.events.index("release") < connection.events.index("publish")

    dispatcher = Dispatcher(connection, committed)
    app = app_for(tmp_path, dispatcher)
    with TestClient(app) as client:
        app.state.db_pool = Pool(connection)
        response = register(client, upload)
    assert response.status_code == 201, response.text
    assert dispatcher.ids == [response.json()["id"]]
    assert response.json()["status"] == "PENDING"


@pytest.mark.parametrize("upload", [False, True])
def test_dispatch_exception_returns_persisted_sanitized_failure(tmp_path: Path, upload: bool) -> None:
    connection = Connection()

    def broken(_job_id: str) -> None:
        raise RuntimeError("redis://private:password@broker")

    dispatcher = Dispatcher(connection, broken)
    app = app_for(tmp_path, dispatcher)
    with TestClient(app) as client:
        app.state.db_pool = Pool(connection)
        response = register(client, upload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == dispatcher.ids[0]
    assert body["status"] == "FAILED"
    assert body["error_code"] == "DISPATCH_FAILED"
    assert "password" not in response.text
    assert connection.events.index("publish") < connection.events.index("dispatch_cas")


@pytest.mark.parametrize("status", ["RUNNING", "CANCEL_REQUESTED", "COMPLETED", "FAILED", "CANCELED"])
def test_accepted_then_error_returns_current_snapshot(tmp_path: Path, status: str) -> None:
    connection = Connection()

    def accepted_then_error(job_id: str) -> None:
        connection.jobs[job_id]["status"] = status
        raise RuntimeError("private producer error")

    dispatcher = Dispatcher(connection, accepted_then_error)
    app = app_for(tmp_path, dispatcher)
    with TestClient(app) as client:
        app.state.db_pool = Pool(connection)
        response = register(client, False)
    assert response.status_code == 201
    assert response.json()["status"] == status
    assert response.json()["error_code"] is None
    assert connection.jobs[dispatcher.ids[0]]["status"] == status


@pytest.mark.parametrize("upload", [False, True])
def test_database_failure_does_not_publish(tmp_path: Path, upload: bool) -> None:
    connection = Connection(fail_insert=True)
    dispatcher = Dispatcher(connection)
    app = app_for(tmp_path, dispatcher)
    with TestClient(app) as client:
        app.state.db_pool = Pool(connection)
        response = register(client, upload)
    assert response.status_code == 503
    assert dispatcher.ids == []


def test_failed_dispatch_status_write_returns_sanitized_503_with_id(tmp_path: Path) -> None:
    connection = Connection(fail_failure_write=True)
    dispatcher = Dispatcher(connection, lambda _: (_ for _ in ()).throw(RuntimeError("secret broker")))
    app = app_for(tmp_path, dispatcher)
    with TestClient(app) as client:
        app.state.db_pool = Pool(connection)
        response = register(client, False)
    assert response.status_code == 503
    assert dispatcher.ids[0] in response.text
    assert "secret" not in response.text


def test_slow_sync_publish_does_not_block_other_async_requests(tmp_path: Path) -> None:
    connection = Connection()
    publish_started = threading.Event()
    release_publish = threading.Event()

    def slow(_job_id: str) -> None:
        publish_started.set()
        assert release_publish.wait(timeout=5)

    dispatcher = Dispatcher(connection, slow)
    app = app_for(tmp_path, dispatcher)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            submit = asyncio.create_task(client.post("/api/v1/jobs", json={"source_url": URL}))
            assert await asyncio.to_thread(publish_started.wait, 3)
            try:
                live = await asyncio.wait_for(client.get("/health/live"), timeout=0.5)
                assert live.status_code == 200
            finally:
                release_publish.set()
            assert (await submit).status_code == 201

    asyncio.run(scenario())
    assert dispatcher.thread_ids[0] != threading.get_ident()
