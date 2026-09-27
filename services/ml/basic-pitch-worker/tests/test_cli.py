from pathlib import Path
import json
import shutil
import subprocess

import numpy as np
import soundfile as sf

from musicsheet_basic_pitch_worker.inference import InferenceError, PredictionOutput
from musicsheet_basic_pitch_worker.output import OutputError
from musicsheet_basic_pitch_worker import cli


def _write_valid_wav(path: Path) -> None:
    sf.write(path, np.zeros(1_024, dtype=np.float32), 22_050, format="WAV", subtype="PCM_16")


def _prediction(midi_data=None) -> PredictionOutput:
    return PredictionOutput(
        model_output=object(),
        midi_data=midi_data,
        note_events=[(0.0, 0.5, 60, 0.75, [])],
    )


def test_cli_returns_2_for_invalid_audio(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli, "run_prediction", lambda _path: (_ for _ in ()).throw(AssertionError()))

    exit_code = cli.main(
        ["--input-audio", str(tmp_path / "missing.wav"), "--output-dir", str(tmp_path / "out")]
    )

    assert exit_code == 2
    assert not (tmp_path / "out").exists()


def test_cli_success_returns_0_and_writes_result(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "piano.wav"
    _write_valid_wav(audio_path)
    output_dir = tmp_path / "result"
    monkeypatch.setattr(cli, "run_prediction", lambda _path: _prediction())

    exit_code = cli.main(
        ["--input-audio", str(audio_path), "--output-dir", str(output_dir)]
    )

    assert exit_code == 0
    saved = json.loads((output_dir / "raw_transcription.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1
    assert saved["provider"]["package_version"] == "0.4.0"


def test_cli_returns_3_for_inference_failure(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "piano.wav"
    _write_valid_wav(audio_path)

    def fail_prediction(_path):
        raise InferenceError("model failed")

    monkeypatch.setattr(cli, "run_prediction", fail_prediction)

    exit_code = cli.main(
        ["--input-audio", str(audio_path), "--output-dir", str(tmp_path / "out")]
    )

    assert exit_code == 3
    assert not (tmp_path / "out").exists()


def test_cli_returns_4_for_output_failure(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "piano.wav"
    _write_valid_wav(audio_path)
    monkeypatch.setattr(cli, "run_prediction", lambda _path: _prediction())

    def fail_output(*_args, **_kwargs):
        raise OutputError("disk failed")

    monkeypatch.setattr(cli, "write_outputs", fail_output)

    exit_code = cli.main(
        ["--input-audio", str(audio_path), "--output-dir", str(tmp_path / "out")]
    )

    assert exit_code == 4
    assert not (tmp_path / "out").exists()


def test_cli_rejects_existing_output_directory(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "piano.wav"
    _write_valid_wav(audio_path)
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    monkeypatch.setattr(cli, "run_prediction", lambda _path: (_ for _ in ()).throw(AssertionError()))

    exit_code = cli.main(
        ["--input-audio", str(audio_path), "--output-dir", str(output_dir)]
    )

    assert exit_code == 4
    assert output_dir.is_dir()


def test_cli_does_not_publish_partial_output(tmp_path: Path, monkeypatch):
    audio_path = tmp_path / "piano.wav"
    _write_valid_wav(audio_path)
    output_dir = tmp_path / "result"

    class BrokenMidi:
        def write(self, path):
            Path(path).write_text("partial midi", encoding="utf-8")
            raise OSError("midi write failed")

    monkeypatch.setattr(cli, "run_prediction", lambda _path: _prediction(BrokenMidi()))

    exit_code = cli.main(
        ["--input-audio", str(audio_path), "--output-dir", str(output_dir)]
    )

    assert exit_code == 4
    assert not output_dir.exists()
    assert list(tmp_path.glob(".result.tmp-*")) == []


def test_console_entry_point_runs_help():
    executable = shutil.which("basic-pitch-worker")
    assert executable is not None

    process = subprocess.run(
        [executable, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0
    assert "--input-audio" in process.stdout
    assert "--output-dir" in process.stdout
