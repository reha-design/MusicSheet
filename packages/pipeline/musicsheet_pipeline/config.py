"""Worker/dispatcher configuration with secret-safe representations."""
from __future__ import annotations

import os
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlsplit


def _url(value,schemes):
    if not value:
        return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in schemes or not parsed.hostname or any(c.isspace() for c in value):
            raise ValueError
        parsed.port
        return value
    except Exception:
        raise ValueError("Invalid pipeline configuration") from None


@dataclass(frozen=True)
class PipelineSettings:
    database_url: str|None=field(repr=False)
    broker_url: str|None=field(repr=False)
    result_backend: str|None=field(repr=False)
    redis_url: str|None=field(repr=False)
    local_storage_dir: Path

    @classmethod
    def from_env(cls,environ=None,*,working_directory=None):
        env=os.environ if environ is None else environ
        try:
            cwd=(working_directory or Path.cwd()).resolve()
            storage=Path(env.get("LOCAL_STORAGE_DIR") or "outputs")
            if not storage.is_absolute():
                storage=(cwd/storage).resolve(strict=False)
            return cls(_url(env.get("DATABASE_URL"),{"postgres","postgresql"}),
                _url(env.get("CELERY_BROKER_URL"),{"redis","rediss"}),
                _url(env.get("CELERY_RESULT_BACKEND"),{"redis","rediss"}),
                _url(env.get("REDIS_URL"),{"redis","rediss"}),storage)
        except Exception:
            raise ValueError("Invalid pipeline configuration") from None

    def require_ready(self):
        if not self.database_url or not self.broker_url:
            raise ValueError("Pipeline database and broker configuration are required")
