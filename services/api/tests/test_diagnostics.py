import asyncio
import subprocess
import time
from pathlib import Path
from typing import Mapping

import pytest
from fastapi.testclient import TestClient

from musicsheet_api import diagnostics
from musicsheet_api.app import create_app
from musicsheet_api.config import Settings


class FixedHealthChecks:
    async def readiness(self) -> Mapping[str, str]:
        return {"postgres": "ok", "redis": "ok", "storage": "ok"}


class MappingCommandRunner:
    def __init__(self, results: Mapping[str, subprocess.CompletedProcess[str]]) -> None:
        self.results = results
        self.commands: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = Path(args[0]).name.lower()
        self.commands.append(args)
        for name, result in self.results.items():
            if name.lower() in command:
                return result
        return subprocess.CompletedProcess(args, 1, "", "not found")


def make_settings(tmp_path: Path) -> Settings:
    return Settings.from_env({}, working_directory=tmp_path)


def install_fake_path_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        diagnostics.shutil,
        "which",
        lambda executable: f"C:/fake-bin/{executable}.exe",
    )


def test_detail_reports_gpu_driver_and_tool_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_path_lookup(monkeypatch)
    runner = MappingCommandRunner(
        {
            "nvidia-smi": subprocess.CompletedProcess(
                [], 0, "NVIDIA GeForce RTX 4060, 555.42, 8192, 4096\n", ""
            ),
            "ffmpeg": subprocess.CompletedProcess(
                [], 0, "ffmpeg version 7.1.1 Copyright (c)\nconfiguration...\n", ""
            ),
            "musescore4": subprocess.CompletedProcess(
                [], 0, "MuseScore 4.5.0\nCopyright\n", ""
            ),
        }
    )
    checks = diagnostics.HostDiagnostics(
        make_settings(tmp_path),
        command_runner=runner,
        timeout_seconds=0.1,
    )

    result = asyncio.run(checks.detail())

    assert result == {
        "gpu": {
            "status": "ok",
            "name": "NVIDIA GeForce RTX 4060",
            "driver_version": "555.42",
            "memory_total_mb": 8192,
            "memory_free_mb": 4096,
        },
        "ffmpeg": {"status": "ok", "version": "ffmpeg version 7.1.1 Copyright (c)"},
        "musescore": {"status": "ok", "version": "MuseScore 4.5.0"},
    }
    commands_by_executable = {
        Path(command[0]).name.lower(): command[1:] for command in runner.commands
    }
    assert commands_by_executable["nvidia-smi.exe"] == [
        "--query-gpu=name,driver_version,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ]
    assert commands_by_executable["ffmpeg.exe"] == ["-version"]
    assert commands_by_executable["musescore4.exe"] == ["--version"]


def test_detail_uses_configured_executable_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []

    def fake_which(executable: str) -> str:
        lookups.append(executable)
        return f"C:/fake-bin/{executable}.exe"

    monkeypatch.setattr(diagnostics.shutil, "which", fake_which)
    settings = Settings.from_env(
        {
            "NVIDIA_SMI_BIN": "nvidia-custom",
            "FFMPEG_BIN": "ffmpeg-custom",
            "MUSESCORE_BIN": "score-custom",
        },
        working_directory=tmp_path,
    )
    runner = MappingCommandRunner(
        {
            "nvidia-custom": subprocess.CompletedProcess(
                [], 0, "NVIDIA GPU, 555.42, 8192, 4096\n", ""
            ),
            "ffmpeg-custom": subprocess.CompletedProcess(
                [], 0, "ffmpeg version 7.1\n", ""
            ),
            "score-custom": subprocess.CompletedProcess(
                [], 0, "MuseScore 4.5\n", ""
            ),
        }
    )
    checks = diagnostics.HostDiagnostics(
        settings,
        command_runner=runner,
        timeout_seconds=0.1,
    )

    result = asyncio.run(checks.detail())

    assert set(lookups) == {"nvidia-custom", "ffmpeg-custom", "score-custom"}
    assert {Path(command[0]).name for command in runner.commands} == {
        "nvidia-custom.exe",
        "ffmpeg-custom.exe",
        "score-custom.exe",
    }
    assert all(result[name]["status"] == "ok" for name in ("gpu", "ffmpeg", "musescore"))


def test_detail_returns_unavailable_for_missing_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    checks = diagnostics.HostDiagnostics(make_settings(tmp_path))
    app = create_app(diagnostics_checks=checks)

    with TestClient(app) as client:
        response = client.get("/health/detail")

    assert response.status_code == 200
    assert response.json() == {
        "gpu": {"status": "unavailable"},
        "ffmpeg": {"status": "unavailable"},
        "musescore": {"status": "unavailable"},
    }


def test_detail_reports_nonzero_command_exit_as_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_path_lookup(monkeypatch)
    runner = MappingCommandRunner(
        {
            "nvidia-smi": subprocess.CompletedProcess([], 2, "gpu secret output", "private path"),
            "ffmpeg": subprocess.CompletedProcess([], 1, "version secret", "secret stderr"),
            "musescore4": subprocess.CompletedProcess([], 127, "version", "missing executable"),
        }
    )
    app = create_app(
        diagnostics_checks=diagnostics.HostDiagnostics(
            make_settings(tmp_path),
            command_runner=runner,
            timeout_seconds=0.1,
        )
    )

    with TestClient(app) as client:
        response = client.get("/health/detail")

    assert response.status_code == 200
    assert response.json() == {
        "gpu": {"status": "unavailable"},
        "ffmpeg": {"status": "unavailable"},
        "musescore": {"status": "unavailable"},
    }
    assert "secret" not in response.text
    assert "private path" not in response.text


def test_detail_bounds_hung_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_path_lookup(monkeypatch)
    started: set[str] = set()

    def hung_runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        started.add(Path(args[0]).name.lower())
        timeout = float(kwargs["timeout"])
        time.sleep(timeout * 1.2)
        raise subprocess.TimeoutExpired(args, timeout=timeout)

    app = create_app(
        diagnostics_checks=diagnostics.HostDiagnostics(
            make_settings(tmp_path),
            command_runner=hung_runner,
            timeout_seconds=0.03,
        )
    )
    start_time = time.perf_counter()

    with TestClient(app) as client:
        response = client.get("/health/detail")
    elapsed = time.perf_counter() - start_time

    assert response.status_code == 200
    assert response.json() == {
        "gpu": {"status": "unavailable"},
        "ffmpeg": {"status": "unavailable"},
        "musescore": {"status": "unavailable"},
    }
    assert elapsed < 0.5
    assert len(started) == 3


def test_detail_handles_bad_gpu_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_path_lookup(monkeypatch)
    runner = MappingCommandRunner(
        {
            "nvidia-smi": subprocess.CompletedProcess([], 0, "not csv gpu data", ""),
            "ffmpeg": subprocess.CompletedProcess([], 0, "ffmpeg version 7.1\n", ""),
            "musescore4": subprocess.CompletedProcess([], 0, "MuseScore 4.5\n", ""),
        }
    )
    app = create_app(
        diagnostics_checks=diagnostics.HostDiagnostics(
            make_settings(tmp_path),
            command_runner=runner,
            timeout_seconds=0.1,
        )
    )

    with TestClient(app) as client:
        response = client.get("/health/detail")

    assert response.status_code == 200
    assert response.json() == {
        "gpu": {"status": "unavailable"},
        "ffmpeg": {"status": "ok", "version": "ffmpeg version 7.1"},
        "musescore": {"status": "ok", "version": "MuseScore 4.5"},
    }


def test_detail_failure_does_not_change_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    app = create_app(
        health_checks=FixedHealthChecks(),
        diagnostics_checks=diagnostics.HostDiagnostics(make_settings(tmp_path)),
    )

    with TestClient(app) as client:
        detail = client.get("/health/detail")
        ready = client.get("/health/ready")

    assert detail.status_code == 200
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "checks": {"postgres": "ok", "redis": "ok", "storage": "ok"},
    }
