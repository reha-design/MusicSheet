"""Optional PostgreSQL pool startup behavior."""

import asyncio
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from musicsheet_api import database
from musicsheet_api.app import create_app
from musicsheet_api.config import Settings


def test_database_unavailable_does_not_break_app_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, float, int]] = []

    async def refuse(dsn: str, *, timeout: float, min_size: int) -> None:
        calls.append((dsn, timeout, min_size))
        raise OSError("connection refused")

    monkeypatch.setattr(database.asyncpg, "create_pool", refuse)

    settings = Settings.from_env({"DATABASE_URL": "postgresql://db.invalid/music"}, working_directory=tmp_path)
    app = create_app(settings=settings)

    with TestClient(app) as client:
        assert app.state.db_pool is None
        assert client.get("/health/live").json() == {"status": "ok"}
    assert calls == [("postgresql://db.invalid/music", 1.0, 1)]


def test_pool_failure_log_omits_connection_details(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    secret = "postgresql://user:password@secret-host/music"

    async def refuse(**kwargs: object) -> None:
        raise OSError(f"connection refused to {secret}")

    monkeypatch.setattr(database.asyncpg, "create_pool", refuse)

    with caplog.at_level(logging.WARNING):
        pool = asyncio.run(database.create_optional_pool(secret))

    assert pool is None
    assert caplog.records
    for record in caplog.records:
        assert record.exc_info is None
        assert "password" not in record.getMessage()
        assert "secret-host" not in record.getMessage()
        assert "connection refused" not in record.getMessage()
