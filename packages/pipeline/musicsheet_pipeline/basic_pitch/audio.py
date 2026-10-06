"""Validate the local WAV container before optional FFmpeg conversion."""
from pathlib import Path
import struct
import threading
import wave

from musicsheet_common import ArtifactRole
from ..config import BasicPitchSettings
from ..contracts import InvalidArtifact, StageContext
from ..providers import PermanentProviderError
from .io import check_stop, run_owned_io
from .process import run_owned_process


def _inspect(path: Path, stop: threading.Event) -> bool:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12 or header[:4] not in {b"RIFF", b"RIFX"} or header[8:] != b"WAVE":
                raise ValueError
            endian = "<" if header[:4] == b"RIFF" else ">"
            end = struct.unpack(endian + "I", header[4:8])[0] + 8
            if end != size:
                raise ValueError
            fmt = None
            data_size = None
            while stream.tell() < end:
                check_stop(stop)
                chunk = stream.read(8)
                if len(chunk) != 8:
                    raise ValueError
                length = struct.unpack(endian + "I", chunk[4:])[0]
                next_position = stream.tell() + length + (length & 1)
                if next_position > end:
                    raise ValueError
                if chunk[:4] == b"fmt ":
                    if fmt is not None or length < 16:
                        raise ValueError
                    fmt = struct.unpack(endian + "HHIIHH", stream.read(16))
                if chunk[:4] == b"data":
                    if data_size is not None or not length:
                        raise ValueError
                    data_size = length
                stream.seek(next_position)
            if fmt is None or data_size is None or not all(fmt[i] > 0 for i in (1, 2, 3, 4)):
                raise ValueError
            if fmt[0] in {1, 3} and data_size % fmt[4]:
                raise ValueError
        try:
            with wave.open(str(path), "rb") as source:
                frames, count = source.getnframes(), 0
                width = source.getnchannels() * source.getsampwidth()
                canonical = source.getframerate() == 22050 and source.getnchannels() == 1
                while block := source.readframes(32768):
                    check_stop(stop)
                    if len(block) % width:
                        raise ValueError
                    count += len(block) // width
                if count != frames or not count:
                    raise ValueError
                return canonical
        except wave.Error:
            return False  # Valid non-PCM WAV, including IEEE float, needs FFmpeg.
    except InterruptedError:
        raise
    except Exception:
        raise InvalidArtifact() from None


async def prepare_input(context: StageContext, temp_root: Path, settings: BasicPitchSettings) -> Path:
    if len(context.inputs) != 1 or context.inputs[0].role != ArtifactRole.SEPARATED_AUDIO:
        raise InvalidArtifact()
    try:
        path = await run_owned_io(lambda stop: context.storage.materialize(context.inputs[0], temp_root),
            cancellation=context.cancellation)
    except Exception:
        raise PermanentProviderError() from None
    if await run_owned_io(lambda stop: _inspect(path, stop), cancellation=context.cancellation):
        return path
    converted = temp_root / "model-input.wav"
    result = await run_owned_process([str(settings.ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-protocol_whitelist", "file,pipe", "-f", "wav", "-i", str(path), "-vn", "-ac", "1", "-ar", "22050",
        "-c:a", "pcm_s16le", str(converted)], cwd=temp_root, cancellation=context.cancellation)
    if result.returncode != 0:
        raise PermanentProviderError()
    if not await run_owned_io(lambda stop: _inspect(converted, stop), cancellation=context.cancellation):
        raise InvalidArtifact()
    return converted
