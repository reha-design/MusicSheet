"""Process configuration for the standalone API service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    redis_url: str | None
    local_storage_dir: Path
    nvidia_smi_bin: str | None
    ffmpeg_bin: str | None
    musescore_bin: str | None

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        working_directory: Path | None = None,
    ) -> Settings:
        env = os.environ if environ is None else environ
        cwd = (working_directory or Path.cwd()).resolve()
        storage_dir = Path(env.get("LOCAL_STORAGE_DIR") or "outputs")
        if not storage_dir.is_absolute():
            storage_dir = (cwd / storage_dir).resolve(strict=False)

        return cls(
            database_url=env.get("DATABASE_URL"),
            redis_url=env.get("REDIS_URL"),
            local_storage_dir=storage_dir,
            nvidia_smi_bin=env.get("NVIDIA_SMI_BIN") or None,
            ffmpeg_bin=env.get("FFMPEG_BIN") or None,
            musescore_bin=env.get("MUSESCORE_BIN") or None,
        )
