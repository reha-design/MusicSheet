"""FastAPI application factory for MusicSheet's API service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from redis.asyncio import Redis

from musicsheet_api.config import Settings
from musicsheet_api.database import create_optional_pool
from musicsheet_api.diagnostics import DiagnosticProvider, HostDiagnostics
from musicsheet_api.health import (
    READINESS_CHECK_NAMES,
    HealthCheckProvider,
    ReadinessChecks,
)
from musicsheet_api.jobs.upload_body_limit import UploadBodyLimitMiddleware
from musicsheet_api.jobs.router import router as jobs_router
from musicsheet_api.events.router import router as events_router
from musicsheet_api.events.store import RedisEventStore
from musicsheet_storage import LocalStorage


def create_app(
    settings: Settings | None = None,
    health_checks: HealthCheckProvider | None = None,
    diagnostics_checks: DiagnosticProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_diagnostics = diagnostics_checks or HostDiagnostics(resolved_settings)

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        db_pool = (
            await create_optional_pool(resolved_settings.database_url)
            if resolved_settings.database_url
            else None
        )
        api.state.db_pool = db_pool
        redis_client: Redis | None = None
        if resolved_settings.redis_url:
            try:
                redis_client = Redis.from_url(
                    resolved_settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=20,
                )
            except Exception:
                redis_client = None
        api.state.redis_client = redis_client
        api.state.event_store = RedisEventStore(redis_client) if redis_client is not None else None
        if health_checks is None:
            api.state.health_checks = ReadinessChecks(
                resolved_settings,
                redis_client,
            )
        else:
            api.state.health_checks = health_checks

        try:
            yield
        finally:
            try:
                if db_pool is not None:
                    await db_pool.close()
            finally:
                if redis_client is not None:
                    try:
                        await redis_client.aclose()
                    except Exception:
                        pass
                api.state.redis_client = None
                api.state.event_store = None
                api.state.db_pool = None

    app = FastAPI(title="MusicSheet API", lifespan=lifespan)
    app.add_middleware(
        UploadBodyLimitMiddleware,
        max_body_bytes=resolved_settings.max_upload_bytes + 64 * 1024,
    )
    app.state.settings = resolved_settings
    app.state.health_checks = health_checks
    app.state.diagnostics_checks = resolved_diagnostics
    app.state.redis_client = None
    app.state.event_store = None
    app.state.db_pool = None
    app.state.storage = LocalStorage(resolved_settings.local_storage_dir)
    app.include_router(jobs_router)
    app.include_router(events_router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid request data"},
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        try:
            raw_checks = await app.state.health_checks.readiness()
        except Exception:
            raw_checks = {}

        checks: dict[str, str] = {}
        for name in READINESS_CHECK_NAMES:
            checks[name] = (
                "ok"
                if isinstance(raw_checks, Mapping) and raw_checks.get(name) == "ok"
                else "unavailable"
            )
        is_ready = all(status == "ok" for status in checks.values())
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "status": "ready" if is_ready else "not_ready",
                "checks": checks,
            },
        )

    @app.get("/health/detail")
    async def detail() -> JSONResponse:
        try:
            result = await app.state.diagnostics_checks.detail()
        except Exception:
            result = {
                "gpu": {"status": "unavailable"},
                "ffmpeg": {"status": "unavailable"},
                "musescore": {"status": "unavailable"},
            }
        return JSONResponse(status_code=200, content=result)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("musicsheet_api.app:app", host="127.0.0.1", port=8000)
