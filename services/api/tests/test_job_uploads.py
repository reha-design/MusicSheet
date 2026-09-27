"""Upload route, transaction, and request-body-bound tests."""

import asyncio
import io
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from musicsheet_api.app import create_app
from musicsheet_api.config import Settings
from musicsheet_api.jobs.uploads import create_upload_job
from musicsheet_storage import LocalStorage


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
UPLOAD_PATH = "/api/v1/jobs/upload"


class FakeTransaction:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.transaction_events.append("begin")

    async def __aexit__(self, error_type: object, error: object, tb: object) -> bool:
        self.connection.transaction_events.append(
            "rollback" if error_type is not None else "commit"
        )
        return False


class FakeConnection:
    def __init__(
        self,
        *,
        fail_on_artifact_insert: bool = False,
        cancel_on_artifact_insert: bool = False,
    ) -> None:
        self.fail_on_artifact_insert = fail_on_artifact_insert
        self.cancel_on_artifact_insert = cancel_on_artifact_insert
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_events: list[str] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any]:
        self.calls.append((query, args))
        if query.startswith("INSERT INTO jobs"):
            return {
                "id": args[0],
                "user_id": None,
                "source_type": args[2],
                "source_url": args[3],
                "target_instrument": args[4],
                "status": "PENDING",
                "current_stage": "DOWNLOAD",
                "stage_progress": 0,
                "overall_progress": 0,
                "error_code": None,
                "error_message": None,
                "created_at": NOW,
                "updated_at": NOW,
                "completed_at": None,
            }
        if query.startswith("INSERT INTO artifacts"):
            if self.cancel_on_artifact_insert:
                raise asyncio.CancelledError
            if self.fail_on_artifact_insert:
                raise RuntimeError("private database failure")
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
        raise AssertionError(f"unexpected SQL: {query}")


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
        self.acquire_calls = 0

    def acquire(self) -> FakeAcquire:
        self.acquire_calls += 1
        return FakeAcquire(self.connection)


class ReadyChecks:
    async def readiness(self) -> dict[str, str]:
        return {"postgres": "ok", "redis": "ok", "storage": "ok"}


def make_app(
    tmp_path: Path,
    *,
    connection: FakeConnection | None = None,
    max_upload_bytes: int = 104_857_600,
):
    settings = Settings.from_env(
        {
            "LOCAL_STORAGE_DIR": str(tmp_path / "outputs"),
            "MAX_UPLOAD_BYTES": str(max_upload_bytes),
        },
        working_directory=tmp_path,
    )
    app = create_app(settings=settings, health_checks=ReadyChecks())
    pool = FakePool(connection or FakeConnection())
    storage = LocalStorage(tmp_path / "outputs")
    return app, pool, storage


def post_file(
    client: TestClient,
    *,
    filename: str = "piece.wav",
    payload: bytes = b"audio",
    content_type: str = "audio/wav",
    fields: dict[str, str] | None = None,
):
    return client.post(
        UPLOAD_PATH,
        data=fields or {},
        files={"file": (filename, payload, content_type)},
    )


def test_upload_registers_job_and_source_artifact(tmp_path: Path) -> None:
    connection = FakeConnection()
    app, pool, storage = make_app(tmp_path, connection=connection)

    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client)

    assert response.status_code == 201
    assert response.json()["source_type"] == "UPLOAD"
    assert response.json()["source_url"] is None
    assert response.json()["status"] == "PENDING"
    assert [query.split("(")[0] for query, _ in connection.calls] == [
        "INSERT INTO jobs ",
        "INSERT INTO artifacts ",
    ]
    assert connection.transaction_events == ["begin", "commit"]
    artifact_args = connection.calls[1][1]
    assert artifact_args[2] == "SOURCE_ORIGINAL"
    assert artifact_args[3] == "source_original.wav"
    assert artifact_args[6] == len(b"audio")
    stored_file = tmp_path / "outputs" / artifact_args[1] / artifact_args[3]
    assert stored_file.read_bytes() == b"audio"


def test_upload_uses_generated_filename_not_client_path(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client, filename="..\\private\\recording.wav")

    assert response.status_code == 201
    filename = pool.connection.calls[1][1][3]
    assert filename == "source_original.wav"
    assert (tmp_path / "outputs" / pool.connection.calls[1][1][1] / filename).is_file()


def test_upload_ignores_client_content_type(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(
            client,
            filename="piece.mp3",
            content_type="application/x-untrusted",
        )

    assert response.status_code == 201
    assert pool.connection.calls[1][1][5] == "audio/mpeg"


@pytest.mark.parametrize(
    ("suffix", "mime_type"),
    [
        (".wav", "audio/wav"),
        (".mp3", "audio/mpeg"),
        (".m4a", "audio/mp4"),
        (".flac", "audio/flac"),
        (".ogg", "audio/ogg"),
    ],
)
def test_upload_accepts_supported_audio_extensions(
    tmp_path: Path,
    suffix: str,
    mime_type: str,
) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client, filename=f"piece{suffix}")

    assert response.status_code == 201
    artifact_args = pool.connection.calls[1][1]
    assert artifact_args[3] == f"source_original{suffix}"
    assert artifact_args[5] == mime_type


def test_upload_rejects_unsupported_extension(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client, filename="payload.exe")

    assert response.status_code == 422
    assert pool.connection.calls == []
    assert not (tmp_path / "outputs").exists()


def test_upload_rejects_unexpected_multipart_field(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = client.post(
            UPLOAD_PATH,
            data={"unexpected": "value"},
            files={"file": ("piece.wav", b"audio", "audio/wav")},
        )

    assert response.status_code == 422
    assert pool.connection.calls == []


def test_upload_rejects_duplicate_multipart_fields(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        boundary = b"duplicate-boundary"
        body = b"".join(
            [
                b"--" + boundary + b"\r\nContent-Disposition: form-data; "
                b'name="target_instrument"\r\n\r\npiano\r\n',
                b"--" + boundary + b"\r\nContent-Disposition: form-data; "
                b'name="target_instrument"\r\n\r\npiano\r\n',
                b"--" + boundary + b"\r\nContent-Disposition: form-data; "
                b'name="file"; filename="piece.wav"\r\n'
                b"Content-Type: audio/wav\r\n\r\naudio\r\n",
                b"--" + boundary + b"--\r\n",
            ]
        )
        response = client.post(
            UPLOAD_PATH,
            content=body,
            headers={
                "content-type": f"multipart/form-data; boundary={boundary.decode()}"
            },
        )

    assert response.status_code == 422
    assert pool.connection.calls == []


def test_upload_rejects_file_field_as_text(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = client.post(UPLOAD_PATH, data={"file": "piece.wav"})

    assert response.status_code == 422
    assert pool.connection.calls == []


def test_upload_rejects_invalid_target_instrument(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client, fields={"target_instrument": "guitar"})

    assert response.status_code == 422
    assert pool.connection.calls == []


def test_upload_rejects_more_than_configured_limit(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path, max_upload_bytes=4)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client, payload=b"12345")

    assert response.status_code == 413
    assert pool.connection.calls == []


def invoke_asgi(
    app: Any,
    *,
    body: bytes,
    content_length: str | None,
    chunk_size: int = 0,
    content_type: str = "multipart/form-data; boundary=bound",
) -> tuple[int, bool]:
    headers = [(b"content-type", content_type.encode("ascii"))]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": UPLOAD_PATH,
        "raw_path": UPLOAD_PATH.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }
    messages: list[dict[str, Any]] = []
    receive_count = 0
    offset = 0

    async def receive() -> dict[str, Any]:
        nonlocal offset, receive_count
        receive_count += 1
        if offset >= len(body):
            return {"type": "http.disconnect"}
        end = len(body) if chunk_size <= 0 else min(len(body), offset + chunk_size)
        chunk = body[offset:end]
        offset = end
        return {"type": "http.request", "body": chunk, "more_body": offset < len(body)}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    return start["status"], receive_count > 0


def oversized_multipart_body() -> bytes:
    return (
        b'--bound\r\nContent-Disposition: form-data; name="file"; '
        b'filename="piece.wav"\r\nContent-Type: audio/wav\r\n\r\n'
        + b"x" * 70_000
        + b"\r\n--bound--\r\n"
    )


def test_upload_rejects_declared_length_over_limit_before_reading(tmp_path: Path) -> None:
    app, _, _ = make_app(tmp_path, max_upload_bytes=4)
    status_code, body_read = invoke_asgi(
        app,
        body=b"",
        content_length=str(4 + 64 * 1024 + 1),
    )

    assert status_code == 413
    assert body_read is False


def test_upload_rejects_body_larger_than_declared_content_length(tmp_path: Path) -> None:
    app, pool, _ = make_app(tmp_path, max_upload_bytes=4)
    app.state.db_pool = pool
    status_code, _ = invoke_asgi(
        app,
        body=oversized_multipart_body(),
        content_length="1",
    )

    assert status_code == 413
    assert pool.acquire_calls == 0


def test_upload_rejects_chunked_body_over_limit_before_form_spooling(tmp_path: Path) -> None:
    app, pool, _ = make_app(tmp_path, max_upload_bytes=4)
    app.state.db_pool = pool
    status_code, _ = invoke_asgi(
        app,
        body=oversized_multipart_body(),
        content_length=None,
        chunk_size=8192,
    )

    assert status_code == 413
    assert pool.acquire_calls == 0


@pytest.mark.parametrize("content_length", [None, "1"])
def test_upload_rejects_oversized_body_for_unsupported_content_type(
    tmp_path: Path,
    content_length: str | None,
) -> None:
    app, pool, _ = make_app(tmp_path, max_upload_bytes=4)
    app.state.db_pool = pool
    status_code, body_read = invoke_asgi(
        app,
        body=b"x" * (4 + 64 * 1024 + 1),
        content_length=content_length,
        chunk_size=8192,
        content_type="application/json",
    )

    assert status_code == 413
    assert body_read
    assert pool.acquire_calls == 0


def test_upload_rolls_back_metadata_and_deletes_file_on_db_failure(tmp_path: Path) -> None:
    connection = FakeConnection(fail_on_artifact_insert=True)
    app, pool, storage = make_app(tmp_path, connection=connection)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Upload storage is unavailable"}
    assert connection.transaction_events == ["begin", "rollback"]
    assert connection.calls[0][0].startswith("INSERT INTO jobs")
    assert connection.calls[1][0].startswith("INSERT INTO artifacts")
    assert not list((tmp_path / "outputs").glob("**/*.*"))


def test_upload_cancellation_attempts_file_cleanup(tmp_path: Path) -> None:
    connection = FakeConnection(cancel_on_artifact_insert=True)
    pool = FakePool(connection)
    storage = LocalStorage(tmp_path / "outputs")

    async def run_upload() -> None:
        await create_upload_job(
            file=io.BytesIO(b"audio"),
            original_filename="piece.wav",
            target_instrument="piano",
            pool=pool,
            storage=storage,
            max_upload_bytes=100,
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_upload())

    assert connection.transaction_events == ["begin", "rollback"]
    assert not list((tmp_path / "outputs").glob("**/*.*"))


def test_upload_cancellation_during_commit_preserves_committed_artifact(
    tmp_path: Path,
) -> None:
    class CommitBlockingTransaction(FakeTransaction):
        async def __aexit__(self, error_type: object, error: object, tb: object) -> bool:
            if error_type is None:
                self.connection.commit_started.set()
                await asyncio.to_thread(self.connection.allow_commit.wait, 2)
            return await super().__aexit__(error_type, error, tb)

    class CommitBlockingConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.commit_started = threading.Event()
            self.allow_commit = threading.Event()

        def transaction(self) -> FakeTransaction:
            return CommitBlockingTransaction(self)

    connection = CommitBlockingConnection()
    pool = FakePool(connection)
    storage = LocalStorage(tmp_path / "outputs")

    async def run_upload() -> None:
        task = asyncio.create_task(
            create_upload_job(
                file=io.BytesIO(b"audio"),
                original_filename="piece.wav",
                target_instrument="piano",
                pool=pool,
                storage=storage,
                max_upload_bytes=100,
            )
        )
        assert await asyncio.to_thread(connection.commit_started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        connection.allow_commit.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=4)

    asyncio.run(run_upload())

    assert connection.transaction_events == ["begin", "commit"]
    job_id = connection.calls[1][1][1]
    assert (tmp_path / "outputs" / job_id / "source_original.wav").is_file()


def test_upload_cancellation_during_storage_write_cleans_file(tmp_path: Path) -> None:
    class BlockingStorage(LocalStorage):
        def __init__(self, base_dir: Path) -> None:
            super().__init__(base_dir)
            self.put_started = threading.Event()
            self.allow_put_to_finish = threading.Event()

        def put(self, *args: Any, **kwargs: Any):
            self.put_started.set()
            if not self.allow_put_to_finish.wait(timeout=3):
                raise TimeoutError("test storage release was not signalled")
            return super().put(*args, **kwargs)

    storage = BlockingStorage(tmp_path / "outputs")
    pool = FakePool(FakeConnection())

    async def run_upload() -> None:
        task = asyncio.create_task(
            create_upload_job(
                file=io.BytesIO(b"audio"),
                original_filename="piece.wav",
                target_instrument="piano",
                pool=pool,
                storage=storage,
                max_upload_bytes=100,
            )
        )
        loop = asyncio.get_running_loop()
        cancellation_delivered = threading.Event()

        def deliver_cancellation() -> None:
            task.cancel()
            cancellation_delivered.set()

        def cancel_while_put_is_blocked() -> None:
            if storage.put_started.wait(timeout=2):
                loop.call_soon_threadsafe(deliver_cancellation)
                cancellation_delivered.wait(timeout=1)
                storage.allow_put_to_finish.set()

        watcher = threading.Thread(target=cancel_while_put_is_blocked)
        watcher.start()
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=4)
        finally:
            storage.allow_put_to_finish.set()
            watcher.join(timeout=1)

    asyncio.run(run_upload())

    assert pool.connection.calls == []
    assert not list((tmp_path / "outputs").glob("**/*.*"))


def test_upload_storage_cleanup_failure_preserves_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = FakeConnection(fail_on_artifact_insert=True)
    app, pool, storage = make_app(tmp_path, connection=connection)

    def fail_delete(artifact: Any) -> bool:
        raise OSError("private cleanup path")

    monkeypatch.setattr(storage, "delete", fail_delete)
    with TestClient(app) as client, caplog.at_level(logging.WARNING):
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Upload storage is unavailable"}
    assert "private cleanup path" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_upload_storage_failure_creates_no_database_rows(tmp_path: Path) -> None:
    connection = FakeConnection()
    app, pool, storage = make_app(tmp_path, connection=connection)

    def fail_put(*args: Any, **kwargs: Any) -> Any:
        raise OSError("private storage failure")

    storage.put = fail_put  # type: ignore[method-assign]
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Upload storage is unavailable"}
    assert connection.calls == []


def test_upload_response_never_exposes_storage_uri(tmp_path: Path) -> None:
    app, pool, storage = make_app(tmp_path)
    with TestClient(app) as client:
        app.state.db_pool = pool
        app.state.storage = storage
        response = post_file(client)

    assert response.status_code == 201
    assert "uri" not in response.json()
    assert "file://" not in response.text


def test_upload_limit_setting_must_be_a_positive_integer() -> None:
    # Detailed parsing cases live with the API Settings contract tests.
    from musicsheet_api.config import Settings

    with pytest.raises(ValueError, match="MAX_UPLOAD_BYTES"):
        Settings.from_env({"MAX_UPLOAD_BYTES": "0"})
