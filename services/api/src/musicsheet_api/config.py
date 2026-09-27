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
    max_upload_bytes: int
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

        raw_upload_limit = env.get("MAX_UPLOAD_BYTES", "104857600")
        try:
            max_upload_bytes = int(raw_upload_limit)
        except (TypeError, ValueError):
            raise ValueError("MAX_UPLOAD_BYTES must be a positive integer") from None
        if max_upload_bytes <= 0:
            raise ValueError("MAX_UPLOAD_BYTES must be a positive integer")

        return cls(
            database_url=env.get("DATABASE_URL"),
            redis_url=env.get("REDIS_URL"),
            local_storage_dir=storage_dir,
            max_upload_bytes=max_upload_bytes,
            nvidia_smi_bin=env.get("NVIDIA_SMI_BIN") or None,
            ffmpeg_bin=env.get("FFMPEG_BIN") or None,
            musescore_bin=env.get("MUSESCORE_BIN") or None,
        )
