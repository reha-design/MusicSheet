from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from musicsheet_api import app as app_module
from musicsheet_api.app import create_app
from musicsheet_api.config import Settings


class NeverCalledHealthChecks:
    async def readiness(self) -> None:
        raise AssertionError("liveness must not run readiness checks")


class ReadyHealthChecks:
    async def readiness(self) -> dict[str, str]:
        return {"postgres": "ok", "redis": "ok", "storage": "ok"}


class FixedDiagnostics:
    async def detail(self) -> dict[str, object]:
        return {
            "gpu": {
                "status": "ok",
                "name": "NVIDIA GPU",
                "driver_version": "555.42",
                "memory_total_mb": 8192,
                "memory_free_mb": 4096,
            },
            "ffmpeg": {"status": "unavailable"},
            "musescore": {"status": "unavailable"},
        }


def test_live_returns_ok_without_running_dependency_checks() -> None:
    app = create_app(health_checks=NeverCalledHealthChecks())

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_health_routes_return_their_documented_contracts() -> None:
    app = create_app(
        health_checks=ReadyHealthChecks(),
        diagnostics_checks=FixedDiagnostics(),
    )

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        detail = client.get("/health/detail")

    assert (live.status_code, live.json()) == (200, {"status": "ok"})
    assert (ready.status_code, ready.json()) == (
        200,
        {
            "status": "ready",
            "checks": {"postgres": "ok", "redis": "ok", "storage": "ok"},
        },
    )
    assert (detail.status_code, detail.json()) == (
        200,
        {
            "gpu": {
                "status": "ok",
                "name": "NVIDIA GPU",
                "driver_version": "555.42",
                "memory_total_mb": 8192,
                "memory_free_mb": 4096,
            },
            "ffmpeg": {"status": "unavailable"},
            "musescore": {"status": "unavailable"},
        },
    )


def test_missing_database_url_keeps_pool_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_pool(url: str) -> object:
        raise AssertionError("pool creation must not run without DATABASE_URL")

    monkeypatch.setattr(app_module, "create_optional_pool", unexpected_pool)
    settings = Settings.from_env({}, working_directory=tmp_path)
    app = create_app(settings=settings, health_checks=NeverCalledHealthChecks())

    with TestClient(app) as client:
        assert app.state.db_pool is None
        assert client.get("/health/live").json() == {"status": "ok"}


def test_created_pool_is_closed_on_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePool:
        close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    pool = FakePool()
    urls: list[str] = []

    async def fake_pool(url: str) -> FakePool:
        urls.append(url)
        return pool

    monkeypatch.setattr(app_module, "create_optional_pool", fake_pool)
    settings = Settings.from_env({"DATABASE_URL": "postgresql://db.invalid/music"}, working_directory=tmp_path)
    app = create_app(settings=settings, health_checks=NeverCalledHealthChecks())

    with TestClient(app) as client:
        assert app.state.db_pool is pool
        assert client.get("/health/live").status_code == 200

    assert urls == ["postgresql://db.invalid/music"]
    assert pool.close_calls == 1


def test_health_override_does_not_disable_event_store(tmp_path, monkeypatch):
    class Client:
        close_calls = 0
        async def aclose(self):
            self.close_calls += 1
    redis = Client()
    options = {}
    def create(url, **kwargs):
        options.update(kwargs)
        return redis
    monkeypatch.setattr(app_module.Redis, "from_url", create)
    app = create_app(settings=Settings.from_env({"REDIS_URL":"redis://test/2"}, working_directory=tmp_path), health_checks=NeverCalledHealthChecks())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert app.state.event_store.client is redis
        assert app.state.redis_client is redis
    assert redis.close_calls == 1
    assert app.state.event_store is None and app.state.redis_client is None
    assert options == {"decode_responses": True, "socket_connect_timeout": 2, "socket_timeout": 20}


def test_missing_redis_url_disables_only_events(tmp_path):
    app = create_app(settings=Settings.from_env({}, working_directory=tmp_path), health_checks=NeverCalledHealthChecks())
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert app.state.event_store is None


def test_redis_initialization_failure_keeps_liveness(tmp_path, monkeypatch):
    def create(url, **kwargs):
        raise ValueError("secret-token-example")
    monkeypatch.setattr(app_module.Redis, "from_url", create)
    app = create_app(settings=Settings.from_env({"REDIS_URL":"redis://test/2"}, working_directory=tmp_path))
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert app.state.event_store is None


def test_redis_closes_once_on_shutdown_even_if_db_close_fails(tmp_path, monkeypatch):
    class Client:
        close_calls = 0
        async def aclose(self):
            self.close_calls += 1
    class Pool:
        async def close(self):
            raise RuntimeError("DB close failure")
    redis = Client()
    async def pool(url):
        return Pool()
    monkeypatch.setattr(app_module, "create_optional_pool", pool)
    monkeypatch.setattr(app_module.Redis, "from_url", lambda url, **kwargs: redis)
    app = create_app(settings=Settings.from_env({"DATABASE_URL":"postgresql://test/db", "REDIS_URL":"redis://test/2"}, working_directory=tmp_path), health_checks=NeverCalledHealthChecks())
    with pytest.raises(RuntimeError, match="DB close failure"):
        with TestClient(app):
            pass
    assert redis.close_calls == 1 and app.state.event_store is None
