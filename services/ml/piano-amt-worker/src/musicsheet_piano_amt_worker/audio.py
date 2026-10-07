"""Bounded, fully decoded PCM input with one hash/frames snapshot."""

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
import wave

from .provenance import regular_file


@dataclass(frozen=True)
class ValidatedAudio:
    pcm: bytes
    frames: int
    duration_sec: float
    sha256: str


def validate_input_audio(path: Path) -> ValidatedAudio:
    path = regular_file(path, maximum=2 * 1024 * 1024)
    try:
        with path.open("rb") as handle:
            data = handle.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("audio size limit")
        with wave.open(BytesIO(data), "rb") as wav:
            frames = wav.getnframes()
            if (wav.getnchannels() != 1 or wav.getframerate() != 16000
                or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE"
                or not 0 < frames <= 480000):
                raise ValueError("16000Hz mono PCM16 up to 30 seconds required")
            pcm = wav.readframes(frames)
            if len(pcm) != frames * 2 or wav.readframes(1):
                raise ValueError("incomplete audio frames")
    except (OSError, EOFError, wave.Error):
        raise ValueError("invalid audio") from None
    return ValidatedAudio(pcm, frames, frames / 16000, hashlib.sha256(data).hexdigest())
