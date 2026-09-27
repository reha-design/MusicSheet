"""Bounded infrastructure probes used by API readiness checks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg

READINESS_TIMEOUT_SECONDS = 1.0


async def check_postgres(
    database_url: str | None,
    *,
    timeout: float = READINESS_TIMEOUT_SECONDS,
) -> str:
    if not database_url:
        return "unavailable"

    connection: Any | None = None
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        async with asyncio.timeout_at(deadline):
            connection = await asyncpg.connect(database_url, timeout=timeout)
            await connection.execute("SELECT 1")
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            await connection.close(timeout=remaining)
            connection = None
        return "ok"
    except Exception:
        return "unavailable"
    finally:
        if connection is not None:
            try:
                connection.terminate()
            except Exception:
                pass


async def check_redis(
    redis_client: Any | None,
    *,
    timeout: float = READINESS_TIMEOUT_SECONDS,
) -> str:
    if redis_client is None:
        return "unavailable"

    try:
        async with asyncio.timeout(timeout):
            return "ok" if await redis_client.ping() else "unavailable"
    except Exception:
        return "unavailable"


def _write_storage_probe(storage_dir: Path) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = storage_dir / f".health-check-{uuid4().hex}"
    try:
        temporary_path.write_bytes(b"health-check\n")
    finally:
        temporary_path.unlink(missing_ok=True)


def _consume_worker_result(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


async def check_storage(
    storage_dir: Path,
    *,
    timeout: float = READINESS_TIMEOUT_SECONDS,
) -> str:
    worker = asyncio.create_task(asyncio.to_thread(_write_storage_probe, storage_dir))
    worker.add_done_callback(_consume_worker_result)
    try:
        await asyncio.wait_for(asyncio.shield(worker), timeout=timeout)
        return "ok"
    except Exception:
        return "unavailable"
