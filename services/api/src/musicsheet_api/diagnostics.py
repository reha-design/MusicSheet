"""Best-effort host diagnostics for tools used by the transcription worker."""

from __future__ import annotations

import asyncio
import csv
import io
import shutil
import subprocess
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from musicsheet_api.config import Settings

DIAGNOSTIC_TIMEOUT_SECONDS = 2.0
_GPU_QUERY = "--query-gpu=name,driver_version,memory.total,memory.free"
_GPU_FORMAT = "--format=csv,noheader,nounits"


class DiagnosticProvider(Protocol):
    async def detail(self) -> Mapping[str, Any]: ...


class HostDiagnostics:
    def __init__(
        self,
        settings: Settings,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        timeout_seconds: float = DIAGNOSTIC_TIMEOUT_SECONDS,
    ) -> None:
        self.settings = settings
        self.command_runner = command_runner or subprocess.run
        self.timeout_seconds = timeout_seconds

    async def detail(self) -> dict[str, dict[str, Any]]:
        gpu, ffmpeg, musescore = await asyncio.gather(
            self._gpu(),
            self._version(
                configured=self.settings.ffmpeg_bin,
                defaults=("ffmpeg",),
                args=("-version",),
                marker="ffmpeg version",
            ),
            self._version(
                configured=self.settings.musescore_bin,
                defaults=("MuseScore4", "musescore"),
                args=("--version",),
                marker="musescore",
            ),
        )
        return {"gpu": gpu, "ffmpeg": ffmpeg, "musescore": musescore}

    async def _gpu(self) -> dict[str, Any]:
        output = await self._run(
            configured=self.settings.nvidia_smi_bin,
            defaults=("nvidia-smi",),
            args=(_GPU_QUERY, _GPU_FORMAT),
        )
        if output is None:
            return {"status": "unavailable"}

        try:
            rows = csv.reader(io.StringIO(output))
            row = next((tuple(value.strip() for value in row) for row in rows if row), None)
            if row is None or len(row) != 4 or not row[0] or not row[1]:
                return {"status": "unavailable"}
            memory_total, memory_free = int(row[2]), int(row[3])
            if memory_total < 0 or memory_free < 0:
                return {"status": "unavailable"}
        except (StopIteration, ValueError, csv.Error):
            return {"status": "unavailable"}

        return {
            "status": "ok",
            "name": row[0][:128],
            "driver_version": row[1][:64],
            "memory_total_mb": memory_total,
            "memory_free_mb": memory_free,
        }

    async def _version(
        self,
        *,
        configured: str | None,
        defaults: tuple[str, ...],
        args: tuple[str, ...],
        marker: str,
    ) -> dict[str, str]:
        output = await self._run(configured=configured, defaults=defaults, args=args)
        if output is None:
            return {"status": "unavailable"}

        first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
        if not first_line.lower().startswith(marker):
            return {"status": "unavailable"}
        return {"status": "ok", "version": first_line[:160]}

    async def _run(
        self,
        *,
        configured: str | None,
        defaults: tuple[str, ...],
        args: tuple[str, ...],
    ) -> str | None:
        executable = _find_executable(configured, defaults)
        if executable is None:
            return None

        command = [executable, *args]
        worker = asyncio.create_task(
            asyncio.to_thread(
                self.command_runner,
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        )
        worker.add_done_callback(_consume_worker_result)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(worker),
                timeout=self.timeout_seconds,
            )
        except Exception:
            return None
        if result.returncode != 0 or not isinstance(result.stdout, str):
            return None
        return result.stdout


def _find_executable(configured: str | None, defaults: tuple[str, ...]) -> str | None:
    candidates = (configured,) if configured else defaults
    for candidate in candidates:
        try:
            executable = shutil.which(candidate)
        except (OSError, TypeError):
            executable = None
        if executable:
            return executable
    return None


def _consume_worker_result(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()
