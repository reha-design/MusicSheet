"""Provider boundary. Deployment starts with no processing providers configured."""
from types import MappingProxyType
from typing import Mapping,Protocol

from musicsheet_common import ArtifactRef,PipelineStage
from .contracts import ProviderIdentity,StageContext


class RetryableProviderError(Exception):
    def __init__(self):
        super().__init__("Stage provider requests retry")


class PermanentProviderError(Exception):
    def __init__(self):
        super().__init__("Stage provider failed")


class StageProvider(Protocol):
    identity: ProviderIdentity
    async def run(self,context: StageContext) -> tuple[ArtifactRef,...]: ...


PROVIDERS: Mapping[PipelineStage,StageProvider]=MappingProxyType({})


async def build_providers(settings):
    if settings.basic_pitch is None:
        return PROVIDERS
    # Lazy imports keep module loading free of subprocesses and model dependencies.
    import asyncio
    from pathlib import Path
    from .basic_pitch.process import run_owned_process
    from .basic_pitch.provider import BasicPitchProvider
    probe = '''import sys,importlib.metadata as m
assert sys.version_info[:2] == (3,12)
assert m.version("musicsheet-basic-pitch-worker") == "0.1.0"
assert m.version("basic-pitch") == "0.4.0"
m.version("onnxruntime")
print("OK")
'''
    setup_ok, version = False, "unavailable"
    try:
        cancellation = asyncio.Event()
        python = await run_owned_process([str(settings.basic_pitch.python), "-I", "-c", probe],
            cwd=Path.cwd(), cancellation=cancellation, timeout=5, capture_stdout=True)
        if python.returncode != 0 or python.stdout.strip() != b"OK":
            raise PermanentProviderError()
        ffmpeg = await run_owned_process([str(settings.basic_pitch.ffmpeg), "-version"],
            cwd=Path.cwd(), cancellation=cancellation, timeout=5, capture_stdout=True)
        first_line = ffmpeg.stdout.decode("utf-8").splitlines()[0]
        if ffmpeg.returncode != 0 or not first_line.startswith("ffmpeg version "):
            raise PermanentProviderError()
        version, setup_ok = first_line, True
    except Exception:
        # A deployment error fails TRANSCRIBE permanently through the normal runner.
        # CancelledError is a BaseException and must still propagate to the owner.
        pass
    return MappingProxyType({PipelineStage.TRANSCRIBE:
        BasicPitchProvider(settings.basic_pitch, ffmpeg_version=version, setup_ok=setup_ok)})
