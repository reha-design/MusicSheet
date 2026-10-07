import hashlib
import subprocess
import sys
from pathlib import Path

import pytest


def test_import_and_help_never_import_models_or_network():
    code = """import builtins
real = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch','librosa','torchlibrosa','piano_transcription_inference','requests','httpx'}:
        raise RuntimeError('Forbidden model/network import')
    return real(name,*args,**kwargs)
builtins.__import__=guarded
import musicsheet_piano_amt_worker
from musicsheet_piano_amt_worker.cli import main
assert main(['--help']) == 0
"""
    p = subprocess.run([sys.executable,"-I","-c",code],capture_output=True,text=True,timeout=15)
    assert p.returncode == 0, p.stderr


def test_audio_reads_all_frames_and_hash(audio):
    from musicsheet_piano_amt_worker.audio import validate_input_audio
    path = audio(frames=16000)
    validated = validate_input_audio(path)
    assert validated.frames == 16000 and validated.duration_sec == 1
    assert validated.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("options", [{"channels":2},{"rate":22050},{"width":1},{"frames":0},{"frames":480001}])
def test_audio_wrong_format_or_duration_rejected(audio, options):
    from musicsheet_piano_amt_worker.audio import validate_input_audio
    with pytest.raises(ValueError):
        validate_input_audio(audio(**options))


def test_truncated_wav_full_frames_rejected(audio):
    from musicsheet_piano_amt_worker.audio import validate_input_audio
    path = audio()
    path.write_bytes(path.read_bytes()[:-10])
    with pytest.raises(ValueError):
        validate_input_audio(path)


def test_checkpoint_missing_size_hash_rejected_before_model_import(checkpoint, monkeypatch):
    from musicsheet_piano_amt_worker import inference
    from musicsheet_piano_amt_worker.provenance import validate_checkpoint
    path, digest = checkpoint
    monkeypatch.setattr(inference,"_load_backend",lambda: pytest.fail("Invalid checkpoint imported model"))
    with pytest.raises(ValueError):
        validate_checkpoint(path, expected_sha256="0"*64)
    with pytest.raises(ValueError):
        inference.run_prediction(path.parent/"missing.wav",checkpoint=path.parent/"missing.pth",device="cpu")
    path.write_bytes(b"abc")
    with pytest.raises(ValueError):
        inference.run_prediction(path.parent/"missing.wav",checkpoint=path,device="cpu")
    path.write_bytes(b"abce")
    with pytest.raises(ValueError):
        validate_checkpoint(path, expected_sha256=hashlib.sha256(b"abce").hexdigest())


@pytest.mark.parametrize("linked", ["is_symlink", "is_junction"])
def test_linked_parent_rejected_for_input_checkpoint_and_output(audio,checkpoint,tmp_path,prediction,monkeypatch,linked):
    from musicsheet_piano_amt_worker.audio import validate_input_audio
    from musicsheet_piano_amt_worker.provenance import validate_checkpoint
    from musicsheet_piano_amt_worker.output import write_outputs
    path=audio()
    monkeypatch.setattr(Path,linked,lambda self: self == tmp_path)
    with pytest.raises(ValueError): validate_input_audio(path)
    with pytest.raises(ValueError): validate_checkpoint(checkpoint[0])
    with pytest.raises(ValueError): write_outputs(tmp_path/"out",prediction,input_sha256="a"*64,checkpoint_sha256="b"*64,device="cpu")
    assert not (tmp_path/"out").exists()
