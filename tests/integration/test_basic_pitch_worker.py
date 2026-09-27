import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

import pytest

from musicsheet_common import TranscriptionResult


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "audio" / "basic_pitch_smoke.wav"
FIXTURE_SHA256 = "2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a"
EXPECTED_SOURCE_COMMIT = "049dc8a01a170c2370d7b246ec1c2067e060c3bf"


def _uv_executable() -> str:
    configured = os.environ.get("MUSICSHEET_UV_EXECUTABLE")
    executable = configured or shutil.which("uv") or shutil.which("uv.exe")
    if not executable:
        pytest.fail("uv was not found; set MUSICSHEET_UV_EXECUTABLE to its executable path")
    return executable


def _run_worker(input_audio: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    command = [
        _uv_executable(),
        "run",
        "--locked",
        "--project",
        "services/ml/basic-pitch-worker",
        "--python",
        "3.12",
        "basic-pitch-worker",
        "--input-audio",
        str(input_audio),
        "--output-dir",
        str(output_dir),
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


def _write_pcm_wav(path: Path, *, sample_rate: int, channels: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * channels * 1_024)


@pytest.mark.ml_integration
def test_basic_pitch_worker_transcribes_cc0_fixture(tmp_path: Path):
    assert sys.version_info[:2] == (3, 13)
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert digest == FIXTURE_SHA256

    output_dir = tmp_path / "basic-pitch-result"
    started = time.perf_counter()
    process = _run_worker(FIXTURE, output_dir)
    elapsed_sec = time.perf_counter() - started

    assert process.returncode == 0, process.stderr
    assert process.stdout == ""
    json_path = output_dir / "raw_transcription.json"
    assert json_path.is_file()
    raw_json = json.loads(json_path.read_text(encoding="utf-8"))
    result = TranscriptionResult.model_validate_json(json_path.read_text(encoding="utf-8"))

    assert result.schema_version == 1
    assert result.provider.id == "spotify-basic-pitch"
    assert result.provider.package_version == "0.4.0"
    assert result.provider.source_commit == EXPECTED_SOURCE_COMMIT
    assert result.provider.model_asset == "nmp.onnx"
    assert result.provider.supports_pedal is False
    assert result.provider.confidence_semantics == "uncalibrated_note_activation_mean"
    assert result.note_events
    for note in result.note_events:
        assert 0 <= note.pitch <= 127
        assert 0 <= note.onset_sec <= note.offset_sec
        assert note.amt_confidence is not None
        assert 0 <= note.amt_confidence <= 1

    midi_path = output_dir / "transcription.mid"
    assert midi_path.is_file()
    assert midi_path.stat().st_size > 0
    assert raw_json["schema_version"] == 1
    assert elapsed_sec > 0


@pytest.mark.ml_integration
@pytest.mark.parametrize("case", ["missing", "wrong_channels", "wrong_sample_rate"])
def test_basic_pitch_worker_rejects_invalid_audio_without_output(tmp_path: Path, case: str):
    if case == "missing":
        input_audio = tmp_path / "missing.wav"
    elif case == "wrong_channels":
        input_audio = tmp_path / "stereo.wav"
        _write_pcm_wav(input_audio, sample_rate=22_050, channels=2)
    else:
        input_audio = tmp_path / "wrong-rate.wav"
        _write_pcm_wav(input_audio, sample_rate=44_100, channels=1)

    output_dir = tmp_path / "result"
    process = _run_worker(input_audio, output_dir)

    assert process.returncode == 2, process.stderr
    assert not output_dir.exists()
