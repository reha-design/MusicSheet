"""Input checks for the Basic Pitch worker's WAV contract."""

from dataclasses import dataclass
from pathlib import Path

import soundfile as sf


EXPECTED_SAMPLE_RATE = 22_050
EXPECTED_CHANNELS = 1
_DECODE_BLOCK_FRAMES = 65_536


class InvalidAudioError(ValueError):
    """Raised when an input file does not satisfy the worker audio contract."""


@dataclass(frozen=True)
class AudioInfo:
    sample_rate: int
    channels: int
    frames: int


def _reject_truncated_riff_container(path: Path) -> None:
    """Catch truncated WAV payloads even when libsndfile clips the frame count."""
    try:
        file_size = path.stat().st_size
        with path.open("rb") as wav_file:
            header = wav_file.read(12)
            if len(header) < 12 or header[8:12] != b"WAVE":
                raise InvalidAudioError("input audio must use a RIFF/WAVE container")

            if header[:4] == b"RIFF":
                byte_order = "little"
            elif header[:4] == b"RIFX":
                byte_order = "big"
            else:
                raise InvalidAudioError("input audio must use a RIFF/WAVE container")

            container_end = int.from_bytes(header[4:8], byteorder=byte_order) + 8
            if container_end > file_size:
                raise InvalidAudioError("input WAV container is truncated")

            position = 12
            has_data_chunk = False
            while position < container_end:
                if container_end - position < 8:
                    raise InvalidAudioError("input WAV contains an incomplete chunk header")

                wav_file.seek(position)
                chunk_header = wav_file.read(8)
                chunk_name = chunk_header[:4]
                chunk_size = int.from_bytes(chunk_header[4:8], byteorder=byte_order)
                chunk_data_end = position + 8 + chunk_size
                padded_chunk_end = chunk_data_end + (chunk_size & 1)
                if chunk_data_end > container_end or chunk_data_end > file_size:
                    raise InvalidAudioError("input WAV contains a truncated chunk payload")
                if chunk_name == b"data":
                    has_data_chunk = True
                position = padded_chunk_end

            if position != container_end or not has_data_chunk:
                raise InvalidAudioError("input WAV has an invalid chunk layout")
    except OSError as error:
        raise InvalidAudioError(f"input WAV could not be read: {path}") from error


def validate_input_audio(path: Path) -> AudioInfo:
    """Validate a nonempty mono 22,050 Hz WAV and decode it in bounded blocks."""
    audio_path = Path(path)
    if not audio_path.is_file():
        raise InvalidAudioError(f"input audio file does not exist: {audio_path}")
    _reject_truncated_riff_container(audio_path)

    try:
        with sf.SoundFile(audio_path, mode="r") as audio_file:
            if audio_file.format != "WAV":
                raise InvalidAudioError("input audio must be a WAV file")
            if audio_file.frames <= 0:
                raise InvalidAudioError("input WAV must contain audio frames")
            if audio_file.samplerate != EXPECTED_SAMPLE_RATE:
                raise InvalidAudioError(
                    f"input WAV sample rate must be {EXPECTED_SAMPLE_RATE} Hz"
                )
            if audio_file.channels != EXPECTED_CHANNELS:
                raise InvalidAudioError("input WAV must be mono")

            expected_frames = audio_file.frames
            decoded_frames = 0
            while True:
                block = audio_file.read(
                    frames=_DECODE_BLOCK_FRAMES,
                    dtype="float32",
                    always_2d=True,
                )
                if block.shape[0] == 0:
                    break
                decoded_frames += block.shape[0]

            if decoded_frames != expected_frames:
                raise InvalidAudioError("input WAV payload is incomplete or corrupt")

            return AudioInfo(
                sample_rate=audio_file.samplerate,
                channels=audio_file.channels,
                frames=expected_frames,
            )
    except InvalidAudioError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise InvalidAudioError(f"input audio is not a readable WAV: {audio_path}") from error
