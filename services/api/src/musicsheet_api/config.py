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
    celery_broker_url: str
    celery_result_backend: str
    celery_visibility_timeout: int
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

        raw_visibility_timeout = env.get("CELERY_VISIBILITY_TIMEOUT", "3600")
        try:
            celery_visibility_timeout = int(raw_visibility_timeout)
        except (TypeError, ValueError):
            raise ValueError("CELERY_VISIBILITY_TIMEOUT must be a positive integer") from None
        if celery_visibility_timeout <= 0:
            raise ValueError("CELERY_VISIBILITY_TIMEOUT must be a positive integer")

        return cls(
            database_url=env.get("DATABASE_URL"),
            redis_url=env.get("REDIS_URL"),
            celery_broker_url=env.get("CELERY_BROKER_URL") or "redis://localhost:6379/0",
            celery_result_backend=env.get("CELERY_RESULT_BACKEND") or "redis://localhost:6379/1",
            celery_visibility_timeout=celery_visibility_timeout,
            local_storage_dir=storage_dir,
            max_upload_bytes=max_upload_bytes,
            nvidia_smi_bin=env.get("NVIDIA_SMI_BIN") or None,
            ffmpeg_bin=env.get("FFMPEG_BIN") or None,
            musescore_bin=env.get("MUSESCORE_BIN") or None,
        )
