import asyncio
from pathlib import Path
from threading import Event
from typing import Mapping

import pytest
from fastapi.testclient import TestClient

from musicsheet_api import health, probes
from musicsheet_api import app as app_module
from musicsheet_api.app import create_app
from musicsheet_api.config import Settings


class FixedHealthChecks:
    def __init__(self, checks: Mapping[str, str]) -> None:
        self.checks = checks

    async def readiness(self) -> Mapping[str, str]:
        return self.checks


def test_ready_all_dependencies_healthy() -> None:
    checks = FixedHealthChecks(
        {"postgres": "ok", "redis": "ok", "storage": "ok"}
    )

    with TestClient(create_app(health_checks=checks)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgres": "ok", "redis": "ok", "storage": "ok"},
    }


@pytest.mark.parametrize("failed_check", ["postgres", "redis", "storage"])
def test_ready_reports_each_dependency_failure(failed_check: str) -> None:
    checks = {"postgres": "ok", "redis": "ok", "storage": "ok"}
    checks[failed_check] = "unavailable"

    with TestClient(create_app(health_checks=FixedHealthChecks(checks))) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": checks}


def test_ready_bounds_slow_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_postgres(_: str | None, *, timeout: float) -> str:
        await asyncio.sleep(timeout * 10)
        return "ok"

    async def healthy_redis(_: object | None, *, timeout: float) -> str:
        return "ok"

    async def healthy_storage(_: Path, *, timeout: float) -> str:
        return "ok"

    monkeypatch.setattr(probes, "check_postgres", slow_postgres)
    monkeypatch.setattr(probes, "check_redis", healthy_redis)
    monkeypatch.setattr(probes, "check_storage", healthy_storage)
    settings = Settings.from_env(
        {"DATABASE_URL": "postgresql://db.invalid/music"},
        working_directory=Path.cwd(),
    )

    async def run_check() -> Mapping[str, str]:
        return await health.ReadinessChecks(
            settings,
            redis_client=object(),
            timeout_seconds=0.02,
        ).readiness()

    checks = asyncio.run(run_check())

    assert checks == {"postgres": "unavailable", "redis": "ok", "storage": "ok"}


def test_postgres_probe_executes_select_one_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.queries: list[str] = []
            self.closed = False

        async def execute(self, query: str) -> None:
            self.queries.append(query)

        async def close(self, *, timeout: float) -> None:
            self.closed = True

    connection = FakeConnection()
    connect_args: list[tuple[str, float]] = []

    async def fake_connect(database_url: str, *, timeout: float) -> FakeConnection:
        connect_args.append((database_url, timeout))
        return connection

    monkeypatch.setattr(probes.asyncpg, "connect", fake_connect)

    status = asyncio.run(
        probes.check_postgres("postgresql://db.internal/music", timeout=0.1)
    )

    assert status == "ok"
    assert connection.queries == ["SELECT 1"]
    assert connection.closed
    assert connect_args == [("postgresql://db.internal/music", 0.1)]


def test_redis_client_is_shared_and_closed_at_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.ping_calls = 0
            self.close_calls = 0

        async def ping(self) -> bool:
            self.ping_calls += 1
            return True

        async def aclose(self) -> None:
            self.close_calls += 1

    redis_client = FakeRedis()
    created_urls: list[str] = []

    def fake_from_url(url: str) -> FakeRedis:
        created_urls.append(url)
        return redis_client

    monkeypatch.setattr(app_module.Redis, "from_url", fake_from_url)
    settings = Settings.from_env(
        {
            "REDIS_URL": "redis://cache.internal:6379/0",
            "LOCAL_STORAGE_DIR": str(tmp_path / "artifacts"),
        },
        working_directory=tmp_path,
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert app.state.redis_client is redis_client
        assert app.state.health_checks.redis_client is redis_client

    assert response.status_code == 503
    assert created_urls == ["redis://cache.internal:6379/0"]
    assert redis_client.ping_calls == 1
    assert redis_client.close_calls == 1


def test_slow_redis_ping_marks_only_redis_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def healthy_postgres(_: str | None, *, timeout: float) -> str:
        return "ok"

    async def healthy_storage(_: Path, *, timeout: float) -> str:
        return "ok"

    class SlowRedis:
        async def ping(self) -> bool:
            await asyncio.sleep(1)
            return True

    monkeypatch.setattr(probes, "check_postgres", healthy_postgres)
    monkeypatch.setattr(probes, "check_storage", healthy_storage)
    settings = Settings.from_env(
        {"LOCAL_STORAGE_DIR": str(tmp_path / "artifacts")},
        working_directory=tmp_path,
    )
    checks = health.ReadinessChecks(
        settings,
        SlowRedis(),
        timeout_seconds=0.02,
    )

    with TestClient(create_app(settings=settings, health_checks=checks)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "postgres": "ok",
            "redis": "unavailable",
            "storage": "ok",
        },
    }


def test_redis_client_construction_failure_does_not_block_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_create_client(url: str) -> object:
        raise ValueError(f"bad credentials in {url}")

    monkeypatch.setattr(app_module.Redis, "from_url", fail_to_create_client)
    settings = Settings.from_env(
        {
            "REDIS_URL": "redis://user:secret@cache.internal/0",
            "LOCAL_STORAGE_DIR": str(tmp_path / "artifacts"),
        },
        working_directory=tmp_path,
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "checks": {
            "postgres": "unavailable",
            "redis": "unavailable",
            "storage": "ok",
        },
    }
    assert "secret" not in ready.text


def test_storage_probe_removes_temporary_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_write_bytes = Path.write_bytes

    def fail_after_partial_write(path: Path, data: bytes) -> int:
        if path.name.startswith(".health-check-"):
            path.touch()
            raise OSError("write failed")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_after_partial_write)

    status = asyncio.run(probes.check_storage(tmp_path))

    assert status == "unavailable"
    assert list(tmp_path.iterdir()) == []


def test_storage_probe_cleans_temporary_file_after_timeout_worker_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_started = Event()
    allow_write_to_finish = Event()
    temporary_paths: list[Path] = []
    original_write_bytes = Path.write_bytes

    def delayed_write(path: Path, data: bytes) -> int:
        if path.name.startswith(".health-check-"):
            path.touch()
            temporary_paths.append(path)
            write_started.set()
            allow_write_to_finish.wait(timeout=2)
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", delayed_write)

    async def run_timed_probe() -> None:
        status = await probes.check_storage(tmp_path, timeout=0.02)
        assert status == "unavailable"
        assert write_started.wait(timeout=1)
        assert len(temporary_paths) == 1
        assert temporary_paths[0].exists()

        allow_write_to_finish.set()
        for _ in range(100):
            if not temporary_paths[0].exists():
                return
            await asyncio.sleep(0.01)
        pytest.fail("timed-out storage worker did not remove its temporary file")

    try:
        asyncio.run(run_timed_probe())
    finally:
        allow_write_to_finish.set()


def test_ready_does_not_expose_secrets_or_paths() -> None:
    secret_message = "postgresql://user:password@db.internal /private/music"

    class BrokenHealthChecks:
        async def readiness(self) -> Mapping[str, str]:
            raise RuntimeError(secret_message)

    with TestClient(create_app(health_checks=BrokenHealthChecks())) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "postgres": "unavailable",
            "redis": "unavailable",
            "storage": "unavailable",
        },
    }
    assert "password" not in response.text
    assert "/private/music" not in response.text


def test_missing_connection_settings_do_not_prevent_api_startup(
    tmp_path: Path,
) -> None:
    settings = Settings.from_env(
        {"LOCAL_STORAGE_DIR": str(tmp_path / "artifacts")},
        working_directory=tmp_path,
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "checks": {
            "postgres": "unavailable",
            "redis": "unavailable",
            "storage": "ok",
        },
    }


def test_invalid_connection_settings_do_not_prevent_api_startup(
    tmp_path: Path,
) -> None:
    settings = Settings.from_env(
        {
            "DATABASE_URL": "not-a-postgres-dsn",
            "REDIS_URL": "not-a-redis-url",
            "LOCAL_STORAGE_DIR": str(tmp_path / "artifacts"),
        },
        working_directory=tmp_path,
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "checks": {
            "postgres": "unavailable",
            "redis": "unavailable",
            "storage": "ok",
        },
    }
