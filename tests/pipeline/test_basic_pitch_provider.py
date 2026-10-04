import asyncio
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import traceback

import pytest

from musicsheet_common import ArtifactRole, PipelineStage
from musicsheet_pipeline.basic_pitch import provider as module
from musicsheet_pipeline.basic_pitch.provider import BasicPitchProvider
from musicsheet_pipeline.config import BasicPitchSettings
from musicsheet_pipeline.contracts import InfrastructureUnavailable, InvalidArtifact, ProviderIdentity, StageMessage
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.providers import PermanentProviderError
from musicsheet_pipeline.runner import run_stage
from .basic_pitch_support import context, midi, payload
from .test_basic_pitch_audio import pcm
from .support import Connection, JOB


def provider(tmp_path, monkeypatch, *, exit_code=0, invalid=False, blocking=False, version="test"):
    counter = tmp_path / "worker-calls"
    code = f'''import sys,json,time,os
from pathlib import Path
counter=Path({str(counter)!r})
with counter.open("a") as out: out.write("called\\n")
root=Path(sys.argv[sys.argv.index("--output-dir")+1]); root.mkdir()
(root/"started").touch()
(root/"pid").write_text(str(os.getpid()))
if {blocking!r}: time.sleep(25)
if {exit_code!r}: raise SystemExit({exit_code!r})
(root/"raw_transcription.json").write_text({json.dumps(payload())!r}, encoding="utf-8")
(root/"transcription.mid").write_bytes({(b"invalid" if invalid else midi())!r})
'''
    monkeypatch.setattr(module, "BOOTSTRAP", code)
    instance = BasicPitchProvider(BasicPitchSettings(Path(sys.executable), tmp_path / "not-needed-ffmpeg"), ffmpeg_version=version)
    return instance, counter


def input_context(tmp_path):
    ctx = context(tmp_path)
    ref = ctx.storage.put(ctx.message.job_id, "stem.wav", ArtifactRole.SEPARATED_AUDIO, io.BytesIO(pcm()), "test", "1")
    return replace(ctx, inputs=(ref,))


def track_temp(monkeypatch):
    directories = []
    def create(*args, **kwargs):
        temp = tempfile.TemporaryDirectory(*args, **kwargs)
        directories.append(temp)
        return temp
    monkeypatch.setattr(module, "TemporaryDirectory", create)
    return directories


def test_provider_preserves_exact_output_roles_and_attempt_names(tmp_path, monkeypatch):
    instance, counter = provider(tmp_path, monkeypatch)
    ctx = input_context(tmp_path)
    directories = track_temp(monkeypatch)
    refs = asyncio.run(instance.run(ctx))
    assert {ref.role for ref in refs} == {ArtifactRole.RAW_TRANSCRIPTION, ArtifactRole.MIDI}
    assert len(refs) == 2 and all(ref.filename.startswith(f"attempt_{ctx.attempt_id}_") for ref in refs)
    assert all(ref.producer == instance.identity.name and ref.producer_version == instance.identity.version for ref in refs)
    assert counter.read_text().splitlines() == ["called"]
    assert directories and all(not Path(directory.name).exists() for directory in directories)


def test_failed_validation_stores_nothing(tmp_path, monkeypatch):
    instance, _ = provider(tmp_path, monkeypatch, invalid=True)
    ctx = input_context(tmp_path)
    with pytest.raises(InvalidArtifact):
        asyncio.run(instance.run(ctx))
    assert list((ctx.storage.base_dir / ctx.message.job_id).iterdir()) == [ctx.storage.base_dir / ctx.message.job_id / "stem.wav"]


@pytest.mark.parametrize("exit_code", [2, 3, 4])
def test_exit_2_3_4_are_permanent(tmp_path, monkeypatch, exit_code):
    instance, _ = provider(tmp_path, monkeypatch, exit_code=exit_code)
    directories = track_temp(monkeypatch)
    with pytest.raises(PermanentProviderError) as caught:
        asyncio.run(instance.run(input_context(tmp_path)))
    assert "secret-sentinel" not in "".join(traceback.format_exception(caught.value))
    assert all(not Path(directory.name).exists() for directory in directories)


def test_cancel_cleans_workspace_after_children_and_io(tmp_path, monkeypatch):
    instance, _ = provider(tmp_path, monkeypatch, blocking=True)
    ctx = input_context(tmp_path)
    directories = track_temp(monkeypatch)
    async def run():
        task = asyncio.create_task(instance.run(ctx))
        try:
            deadline = asyncio.get_running_loop().time() + 8
            while not directories or not (Path(directories[0].name) / "result" / "started").exists():
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(.02)
            ctx.cancellation.set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 10)
            assert all(not Path(directory.name).exists() for directory in directories)
        finally:
            ctx.cancellation.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize("case", ["late-cancel", "cleanup-failure"])
def test_results_owned_until_temp_cleanup_succeeds(tmp_path, monkeypatch, case):
    instance, _ = provider(tmp_path, monkeypatch)
    ctx = input_context(tmp_path)
    saved = []
    original = module.store_outputs
    async def store(*args, **kwargs):
        refs = await original(*args, **kwargs)
        saved.extend(refs)
        if case == "late-cancel":
            ctx.cancellation.set()
        return refs
    monkeypatch.setattr(module, "store_outputs", store)
    if case == "cleanup-failure":
        def temp(*args, **kwargs):
            directory = tempfile.TemporaryDirectory(*args, **kwargs)
            original_cleanup = directory.cleanup
            def fail():
                original_cleanup()
                raise OSError("secret-sentinel")
            directory.cleanup = fail
            return directory
        monkeypatch.setattr(module, "TemporaryDirectory", temp)
    with pytest.raises(asyncio.CancelledError if case == "late-cancel" else PermanentProviderError) as caught:
        asyncio.run(instance.run(ctx))
    assert len(saved) == 2 and all(not ctx.storage.exists(ref) for ref in saved)
    assert "secret-sentinel" not in "".join(traceback.format_exception(caught.value))


async def preceding_stages(tmp_path):
    c = Connection()
    ctx = context(tmp_path)
    storage = ctx.storage
    original = storage.put(JOB, "source.wav", ArtifactRole.SOURCE_ORIGINAL, io.BytesIO(pcm()), "upload", "1")
    c.db.artifacts = {original.id: original.model_dump()}
    class Before:
        def __init__(self, input_role, output_role):
            self.identity = ProviderIdentity("test-before", "1", {}, frozenset({input_role}), frozenset({output_role}))
        async def run(self, current):
            if current.message.stage == PipelineStage.DOWNLOAD:
                return current.inputs
            return (storage.put(JOB, f"attempt_{current.attempt_id}_audio.wav", next(iter(self.identity.output_roles)),
                io.BytesIO(pcm()), self.identity.name, self.identity.version),)
    stages = {PipelineStage.DOWNLOAD: Before(ArtifactRole.SOURCE_ORIGINAL, ArtifactRole.SOURCE_ORIGINAL),
        PipelineStage.PREPROCESS: Before(ArtifactRole.SOURCE_ORIGINAL, ArtifactRole.CANONICAL_AUDIO),
        PipelineStage.SEPARATE: Before(ArtifactRole.CANONICAL_AUDIO, ArtifactRole.SEPARATED_AUDIO)}
    await enqueue_stage(c, StageMessage(JOB, "DOWNLOAD", 1))
    for stage in stages:
        await run_stage(StageMessage(JOB, stage, 1), connection=c, storage=storage, providers=stages, event_store=None)
    assert c.db.jobs[JOB]["status"] == "RUNNING"
    return c, storage


def test_duplicate_fingerprint_skips_worker_and_configuration_change_fails(tmp_path, monkeypatch):
    instance, counter = provider(tmp_path, monkeypatch)
    async def run():
        c, storage = await preceding_stages(tmp_path)
        before = len(c.db.artifacts)
        args = dict(connection=c, storage=storage, providers={PipelineStage.TRANSCRIBE: instance}, event_store=None)
        message = StageMessage(JOB, "TRANSCRIBE", 1)
        await run_stage(message, **args)
        assert len(c.db.artifacts) - before == 2
        assert c.db.jobs[JOB]["status"] == "RUNNING" and c.db.jobs[JOB]["current_stage"] == "TRANSCRIBE"
        attempt = next(a for a in c.db.attempts.values() if a["stage"] == "TRANSCRIBE")
        assert attempt["status"] == "COMPLETED" and len(attempt["output_artifact_ids"]) == 2
        assert len([key for key in c.db.outbox if key[1] == "POSTPROCESS"]) == 1
        await run_stage(message, **args)
        assert len(counter.read_text().splitlines()) == 1
        changed, _ = provider(tmp_path, monkeypatch, version="changed")
        args["providers"] = {PipelineStage.TRANSCRIBE: changed}
        await run_stage(message, **args)
        assert c.db.jobs[JOB]["error_code"] == "INPUT_CHANGED"
        assert len(counter.read_text().splitlines()) == 1
    asyncio.run(run())


@pytest.mark.parametrize("case", ["cancel", "connection-loss"])
def test_cancel_or_lost_ownership_never_commits_outputs(tmp_path, monkeypatch, case):
    instance, counter = provider(tmp_path, monkeypatch, blocking=True)
    async def run():
        c, storage = await preceding_stages(tmp_path)
        before = len(c.db.artifacts)
        task = asyncio.create_task(run_stage(StageMessage(JOB, "TRANSCRIBE", 1), connection=c, storage=storage,
            providers={PipelineStage.TRANSCRIBE: instance}, event_store=None, cancellation_interval=.02))
        try:
            deadline = asyncio.get_running_loop().time() + 8
            while not counter.exists():
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(.02)
            if case == "cancel":
                c.db.jobs[JOB]["status"] = "CANCEL_REQUESTED"
                await asyncio.wait_for(task, 10)
            else:
                c.terminate()
                with pytest.raises(InfrastructureUnavailable):
                    await asyncio.wait_for(task, 10)
            assert len(c.db.artifacts) == before and not any(key[1] == "POSTPROCESS" for key in c.db.outbox)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
