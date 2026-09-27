from fastapi.testclient import TestClient

from musicsheet_api.app import create_app


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
