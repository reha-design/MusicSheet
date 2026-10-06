"""Actual model registration plus controlled cancellation/ownership loss."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pytest

from musicsheet_common import ArtifactRef, PipelineStage
from musicsheet_pipeline.basic_pitch import provider as module
from musicsheet_pipeline.basic_pitch.provider import BasicPitchProvider
from musicsheet_pipeline.config import BasicPitchSettings
from musicsheet_pipeline.contracts import InfrastructureUnavailable, StageMessage
from musicsheet_pipeline.runner import run_stage
from integration.test_basic_pitch_provider import FIXTURE, FIXTURE_SHA256, assert_results, installed_provider
from ..test_basic_pitch_audio import pcm
from ..test_basic_pitch_process import alive
from .basic_pitch_support import owned_job, run_live, wait_until

pytestmark = pytest.mark.pipeline_db_integration


@pytest.mark.ml_integration
def test_real_model_transcribe_commits_two_artifacts(tmp_path, monkeypatch):
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    async def run():
        provider = await installed_provider(tmp_path)
        calls = []
        original = module.run_owned_process
        async def count(*args, **kwargs):
            calls.append(1)
            return await original(*args, **kwargs)
        monkeypatch.setattr(module, "run_owned_process", count)
        async with owned_job(tmp_path, FIXTURE.read_bytes()) as (connection, observer, storage, job):
            before = await observer.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1", job)
            message = StageMessage(job, "TRANSCRIBE", 1)
            args = dict(connection=connection, storage=storage, providers={PipelineStage.TRANSCRIBE: provider}, event_store=None)
            await run_stage(message, **args)
            attempt = await observer.fetchrow("SELECT * FROM stage_attempts WHERE job_id=$1 AND stage='TRANSCRIBE'", job)
            assert attempt["status"] == "COMPLETED"
            ids = json.loads(attempt["output_artifact_ids"])
            assert len(ids) == 2
            rows = await observer.fetch("SELECT * FROM artifacts WHERE id=ANY($1::varchar[])", ids)
            refs = tuple(ArtifactRef.model_validate(dict(row)) for row in rows)
            assert_results(storage, refs, attempt["id"])
            assert await observer.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1", job) == before + 2
            assert await observer.fetchval("SELECT count(*) FROM pipeline_outbox WHERE job_id=$1 AND stage='POSTPROCESS'", job) == 1
            row = await observer.fetchrow("SELECT status,current_stage FROM jobs WHERE id=$1", job)
            assert dict(row) == {"status": "RUNNING", "current_stage": "TRANSCRIBE"}
            await run_stage(message, **args)
            assert calls == [1]
            assert await observer.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1", job) == before + 2
            assert await observer.fetchval("SELECT count(*) FROM pipeline_outbox WHERE job_id=$1 AND stage='POSTPROCESS'", job) == 1
    run_live(run())


@pytest.mark.parametrize("case", ["cancel", "connection-loss"])
def test_transcribe_cancellation_or_ownership_loss_fences_outputs(tmp_path, monkeypatch, case):
    started = tmp_path / "started"
    code = f'''import time,os
from pathlib import Path
Path({str(started)!r}).write_text(str(os.getpid()))
time.sleep(25)
'''
    monkeypatch.setattr(module, "BOOTSTRAP", code)
    directories = []
    def temporary(*args, **kwargs):
        directory = TemporaryDirectory(*args, **kwargs)
        directories.append(directory)
        return directory
    monkeypatch.setattr(module, "TemporaryDirectory", temporary)
    provider = BasicPitchProvider(BasicPitchSettings(Path(sys.executable), tmp_path / "unused-ffmpeg"), ffmpeg_version="test")
    async def run():
        async with owned_job(tmp_path, pcm()) as (connection, observer, storage, job):
            before = await observer.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1", job)
            task = asyncio.create_task(run_stage(StageMessage(job, "TRANSCRIBE", 1), connection=connection,
                storage=storage, providers={PipelineStage.TRANSCRIBE: provider}, event_store=None, cancellation_interval=.02))
            try:
                await wait_until(started.exists)
                if case == "cancel":
                    await observer.execute("UPDATE jobs SET status='CANCEL_REQUESTED' WHERE id=$1", job)
                    await asyncio.wait_for(task, 15)
                    assert await observer.fetchval("SELECT status FROM jobs WHERE id=$1", job) == "CANCELED"
                else:
                    connection.terminate()
                    with pytest.raises(InfrastructureUnavailable):
                        await asyncio.wait_for(task, 15)
                assert await observer.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1", job) == before
                assert await observer.fetchval("SELECT count(*) FROM pipeline_outbox WHERE job_id=$1 AND stage='POSTPROCESS'", job) == 0
                assert directories and all(not Path(directory.name).exists() for directory in directories)
                assert not alive(int(started.read_text()))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    run_live(run())
