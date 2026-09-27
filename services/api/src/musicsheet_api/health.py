"""Interfaces and orchestration for API readiness checks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from typing import Protocol

from musicsheet_api import probes
from musicsheet_api.config import Settings

READINESS_CHECK_NAMES = ("postgres", "redis", "storage")
READINESS_TIMEOUT_SECONDS = 1.0


class HealthCheckProvider(Protocol):
    async def readiness(self) -> Mapping[str, str]: ...


class ReadinessChecks:
    def __init__(
        self,
        settings: Settings,
        redis_client: object | None,
        *,
        timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
    ) -> None:
        self.settings = settings
        self.redis_client = redis_client
        self.timeout_seconds = timeout_seconds

    async def readiness(self) -> Mapping[str, str]:
        results = await asyncio.gather(
            self._bounded(
                probes.check_postgres(
                    self.settings.database_url,
                    timeout=self.timeout_seconds,
                )
            ),
            self._bounded(
                probes.check_redis(
                    self.redis_client,
                    timeout=self.timeout_seconds,
                )
            ),
            self._bounded(
                probes.check_storage(
                    self.settings.local_storage_dir,
                    timeout=self.timeout_seconds,
                )
            ),
        )
        return dict(zip(READINESS_CHECK_NAMES, results, strict=True))

    async def _bounded(self, check: Awaitable[str]) -> str:
        try:
            result = await asyncio.wait_for(check, timeout=self.timeout_seconds)
        except Exception:
            return "unavailable"
        return "ok" if result == "ok" else "unavailable"
