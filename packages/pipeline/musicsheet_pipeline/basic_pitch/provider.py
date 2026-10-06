"""Opt-in adapter; inference dependencies live only in the isolated worker."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from musicsheet_common import ArtifactRole
from ..contracts import InfrastructureUnavailable, InvalidArtifact, ProviderIdentity
from ..providers import PermanentProviderError
from .audio import prepare_input
from .process import _drain, run_owned_process
from .io import rollback_outputs, run_owned_io, store_outputs
from .result import JSON_LIMIT, MIDI_LIMIT, PROVENANCE, validate_result_files

BOOTSTRAP = '''import sys,importlib.metadata
if sys.version_info[:2] != (3,12) or importlib.metadata.version("musicsheet-basic-pitch-worker") != "0.1.0":
    raise SystemExit(3)
from musicsheet_basic_pitch_worker.cli import main
raise SystemExit(main())
'''


class BasicPitchProvider:
    def __init__(self, settings, *, ffmpeg_version, setup_ok=True):
        self._settings, self._setup_ok = settings, setup_ok
        self.identity = ProviderIdentity("spotify-basic-pitch", "0.1.0", {
            "adapter_version": "0.1.0", "schema_version": 1, "model": PROVENANCE,
            "input": {"sample_rate": 22050, "channels": 1, "encoding": "PCM"},
            "python": str(settings.python), "ffmpeg": str(settings.ffmpeg),
            "ffmpeg_version": ffmpeg_version, "json_limit": JSON_LIMIT, "midi_limit": MIDI_LIMIT,
        }, frozenset({ArtifactRole.SEPARATED_AUDIO}),
            frozenset({ArtifactRole.RAW_TRANSCRIPTION, ArtifactRole.MIDI}))

    async def run(self, context):
        if not self._setup_ok:
            raise PermanentProviderError() from None
        if context.cancellation.is_set():
            raise asyncio.CancelledError
        refs = ()
        try:
            directory = TemporaryDirectory(prefix="musicsheet-basic-pitch-")
            try:
                root = Path(directory.name)
                audio = await prepare_input(context, root, self._settings)
                if context.report_progress is not None:
                    await context.report_progress(20)
                output = root / "result"
                process = await run_owned_process([
                    str(self._settings.python), "-I", "-c", BOOTSTRAP,
                    "--input-audio", str(audio), "--output-dir", str(output),
                ], cwd=root, cancellation=context.cancellation, timeout=1800)
                if process.returncode != 0:
                    raise PermanentProviderError()
                if context.report_progress is not None:
                    await context.report_progress(70)
                files = await run_owned_io(lambda stop: validate_result_files(output, stop=stop),
                    cancellation=context.cancellation)
                if context.report_progress is not None:
                    await context.report_progress(85)
                refs = await store_outputs(context, files, identity=self.identity)
                if context.report_progress is not None:
                    await context.report_progress(95)
                if context.cancellation.is_set():
                    raise asyncio.CancelledError
            finally:
                # Child processes and I/O have drained before this point. Own cleanup too.
                await _drain(asyncio.to_thread(directory.cleanup))
            if context.cancellation.is_set():
                raise asyncio.CancelledError
            return refs
        except BaseException as error:
            await rollback_outputs(context.storage, refs)
            if isinstance(error, (asyncio.CancelledError, InfrastructureUnavailable, InvalidArtifact, TimeoutError)):
                raise
            raise PermanentProviderError() from None
