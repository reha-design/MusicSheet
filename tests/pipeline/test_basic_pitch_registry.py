import asyncio
from pathlib import Path
import subprocess
import sys
import traceback

import pytest

from musicsheet_common import PipelineStage
from musicsheet_pipeline.basic_pitch import process
from musicsheet_pipeline.basic_pitch.process import ProcessResult
from musicsheet_pipeline.config import BasicPitchSettings, PipelineSettings
from musicsheet_pipeline.providers import build_providers, PermanentProviderError, PROVIDERS
from .basic_pitch_support import context


def settings(root, enabled=True):
    return PipelineSettings(None, None, None, None, root,
        BasicPitchSettings(Path(sys.executable), root / "ffmpeg") if enabled else None)


def test_disabled_provider_performs_no_probe(tmp_path, monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("disabled factory must not probe")
    monkeypatch.setattr(process, "run_owned_process", unexpected)
    assert asyncio.run(build_providers(settings(tmp_path, False))) is PROVIDERS


def test_only_transcribe_is_enabled(tmp_path, monkeypatch):
    calls = []
    async def probe(argv, **kwargs):
        calls.append((argv, kwargs))
        return ProcessResult(0, b"OK\n" if "-c" in argv else b"ffmpeg version test\nconfiguration: hidden\n")
    monkeypatch.setattr(process, "run_owned_process", probe)
    providers = asyncio.run(build_providers(settings(tmp_path)))
    assert set(providers) == {PipelineStage.TRANSCRIBE}
    assert len(calls) == 2 and all(kwargs["timeout"] == 5 and kwargs["capture_stdout"] for _, kwargs in calls)
    assert providers[PipelineStage.TRANSCRIBE].identity.name == "spotify-basic-pitch"
    with pytest.raises(TypeError):
        providers[PipelineStage.DOWNLOAD] = providers[PipelineStage.TRANSCRIBE]


@pytest.mark.parametrize("error", [PermanentProviderError(), TimeoutError("secret-sentinel"), OSError("secret-sentinel")])
def test_probe_failure_returns_permanent_stage_provider_without_raw_exception(tmp_path, monkeypatch, error):
    async def bad(*args, **kwargs):
        raise error
    monkeypatch.setattr(process, "run_owned_process", bad)
    providers = asyncio.run(build_providers(settings(tmp_path)))
    assert set(providers) == {PipelineStage.TRANSCRIBE} and providers.get(PipelineStage.DOWNLOAD) is None
    with pytest.raises(PermanentProviderError) as caught:
        asyncio.run(providers[PipelineStage.TRANSCRIBE].run(context(tmp_path)))
    assert "secret-sentinel" not in "".join(traceback.format_exception(caught.value))


def test_probe_cancellation_propagates(tmp_path, monkeypatch):
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError
    monkeypatch.setattr(process, "run_owned_process", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(build_providers(settings(tmp_path)))


def test_import_does_not_spawn_or_import_model():
    code = '''import asyncio,subprocess,socket,sys
def fail(*args,**kwargs): raise AssertionError("import side effect")
asyncio.create_subprocess_exec=fail
subprocess.Popen=fail
socket.create_connection=fail
import musicsheet_pipeline.basic_pitch.provider, musicsheet_pipeline.providers
assert not any(name.startswith(("basic_pitch", "musicsheet_basic_pitch_worker", "onnxruntime", "torch", "tensorflow")) for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
