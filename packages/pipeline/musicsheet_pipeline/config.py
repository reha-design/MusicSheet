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
class BasicPitchSettings:
    python: Path = field(repr=False)
    ffmpeg: Path = field(repr=False)

    def __post_init__(self):
        try:
            for name in ("python", "ffmpeg"):
                path = Path(getattr(self, name))
                if not path.is_absolute():
                    raise ValueError
                object.__setattr__(self, name, path)
        except Exception:
            raise ValueError("Invalid pipeline configuration") from None


@dataclass(frozen=True)
class PipelineSettings:
    database_url: str|None=field(repr=False)
    broker_url: str|None=field(repr=False)
    result_backend: str|None=field(repr=False)
    redis_url: str|None=field(repr=False)
    local_storage_dir: Path
    basic_pitch: BasicPitchSettings | None = None

    @classmethod
    def from_env(cls,environ=None,*,working_directory=None):
        env=os.environ if environ is None else environ
        try:
            cwd=(working_directory or Path.cwd()).resolve()
            storage=Path(env.get("LOCAL_STORAGE_DIR") or "outputs")
            if not storage.is_absolute():
                storage=(cwd/storage).resolve(strict=False)
            selector = env.get("TRANSCRIPTION_PROVIDER")
            basic_pitch = None
            if selector:
                if selector != "basic-pitch":
                    raise ValueError
                basic_pitch = BasicPitchSettings(env.get("BASIC_PITCH_PYTHON"), env.get("FFMPEG_EXECUTABLE"))
            return cls(_url(env.get("DATABASE_URL"),{"postgres","postgresql"}),
                _url(env.get("CELERY_BROKER_URL"),{"redis","rediss"}),
                _url(env.get("CELERY_RESULT_BACKEND"),{"redis","rediss"}),
                _url(env.get("REDIS_URL"),{"redis","rediss"}),storage,basic_pitch)
        except Exception:
            raise ValueError("Invalid pipeline configuration") from None

    def require_ready(self):
        if not self.database_url or not self.broker_url:
            raise ValueError("Pipeline database and broker configuration are required")
