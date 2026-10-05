import importlib.metadata
import subprocess
import sys
from pathlib import Path


def test_locked_environment_and_process_boundary():
    assert sys.version_info[:2] == (3, 13)
    assert importlib.metadata.version("mir_eval") == "0.8.2"
    assert importlib.metadata.version("mido") == "1.3.3"
    code = """
import sys
import musicsheet_common, musicsheet_storage, musicsheet_pipeline
import musicsheet_transcription_eval
from musicsheet_pipeline.basic_pitch.process import run_owned_process
from musicsheet_pipeline.basic_pitch.result import validate_result_files
assert not any(name.split('.')[0] in {'torch','tensorflow','onnxruntime','basic_pitch','piano_transcription_inference'} for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=Path(__file__).parents[3], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_cli_help_exposes_prepare_without_network():
    result = subprocess.run([sys.executable, "-I", "-m", "musicsheet_transcription_eval", "--help"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "prepare" in result.stdout


def test_cli_path_escape_rejected_before_network(monkeypatch):
    import uuid
    from musicsheet_transcription_eval import cli, dataset
    repo = Path(__file__).parents[3]
    name = "test-cli-escape-" + uuid.uuid4().hex
    output = repo / "outputs" / ".." / name
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise ValueError("network invoked")
    monkeypatch.setattr(dataset, "download_metadata", forbidden)
    try:
        assert cli.main(["prepare", "--output-root", str(output), "--manifest", str(repo / "docs/evaluations" / (name + ".json")), "--ffmpeg", sys.executable]) == 4
        assert not calls
    finally:
        escaped = repo / name
        if escaped.exists(): escaped.rmdir()
