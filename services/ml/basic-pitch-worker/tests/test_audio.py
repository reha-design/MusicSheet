from pathlib import Path
import struct

import numpy as np
import pytest
import soundfile as sf

from musicsheet_basic_pitch_worker.audio import AudioInfo, InvalidAudioError, validate_input_audio


def _write_wav(path: Path, *, sample_rate: int = 22_050, channels: int = 1) -> None:
    audio = np.zeros((1_024, channels), dtype=np.float32)
    sf.write(path, audio, sample_rate, format="WAV", subtype="PCM_16")


def _write_rifx_wav(path: Path, *, frames: int = 1_024) -> None:
    samples = b"\x00\x00" * frames
    fmt_chunk = b"fmt " + struct.pack(">IHHIIHH", 16, 1, 1, 22_050, 44_100, 2, 16)
    data_chunk = b"data" + struct.pack(">I", len(samples)) + samples
    wave_payload = b"WAVE" + fmt_chunk + data_chunk
    path.write_bytes(b"RIFX" + struct.pack(">I", len(wave_payload)) + wave_payload)


def test_rejects_missing_file(tmp_path: Path):
    with pytest.raises(InvalidAudioError):
        validate_input_audio(tmp_path / "missing.wav")


def test_rejects_corrupt_wav_payload(tmp_path: Path):
    audio_path = tmp_path / "truncated.wav"
    _write_wav(audio_path)
    truncated = bytearray(audio_path.read_bytes()[:-100])
    # Repair the outer RIFF length while leaving the data chunk's declared
    # payload length untouched; this isolates truncation inside the WAV chunk.
    truncated[4:8] = (len(truncated) - 8).to_bytes(4, byteorder="little")
    audio_path.write_bytes(truncated)

    with pytest.raises(InvalidAudioError):
        validate_input_audio(audio_path)


def test_rejects_truncated_rifx_payload(tmp_path: Path):
    audio_path = tmp_path / "truncated-rifx.wav"
    _write_rifx_wav(audio_path)
    truncated = bytearray(audio_path.read_bytes()[:-100])
    truncated[4:8] = struct.pack(">I", len(truncated) - 8)
    audio_path.write_bytes(truncated)

    with pytest.raises(InvalidAudioError):
        validate_input_audio(audio_path)


@pytest.mark.parametrize(
    ("sample_rate", "channels"),
    [(44_100, 1), (22_050, 2)],
)
def test_rejects_wrong_channels_and_sample_rate(
    tmp_path: Path,
    sample_rate: int,
    channels: int,
):
    audio_path = tmp_path / "unsupported.wav"
    _write_wav(audio_path, sample_rate=sample_rate, channels=channels)

    with pytest.raises(InvalidAudioError):
        validate_input_audio(audio_path)


def test_accepts_nonempty_22050_hz_mono_wav(tmp_path: Path):
    audio_path = tmp_path / "piano.wav"
    _write_wav(audio_path)

    info = validate_input_audio(audio_path)

    assert info == AudioInfo(sample_rate=22_050, channels=1, frames=1_024)


def test_accepts_nonempty_22050_hz_mono_rifx_wav(tmp_path: Path):
    audio_path = tmp_path / "piano-rifx.wav"
    _write_rifx_wav(audio_path)

    info = validate_input_audio(audio_path)

    assert info == AudioInfo(sample_rate=22_050, channels=1, frames=1_024)
