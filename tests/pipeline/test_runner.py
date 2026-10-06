import asyncio
import io
from datetime import datetime,timezone

import pytest
from musicsheet_common import PipelineStage
from musicsheet_pipeline.contracts import StageMessage,InfrastructureUnavailable
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.runner import run_stage
from musicsheet_pipeline.providers import RetryableProviderError,PermanentProviderError,PROVIDERS

from .runner_support import environment,Provider,Events,ROLE,IDENTITY
from .support import JOB


def test_six_stages_complete_in_order_with_reused_upload(tmp_path):
    async def check():
        c,storage,original=environment(tmp_path)
        provider=Provider()
        events=Events(c)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        for stage in PipelineStage:
            await run_stage(StageMessage(JOB,stage,1),connection=c,storage=storage,
                            providers={s:provider for s in PipelineStage},event_store=events)
        assert c.db.jobs[JOB]["status"]=="COMPLETED"
        assert len(c.db.attempts)==6 and len(c.db.artifacts)==1
        assert [e.overall_progress for e in events.events if e.stage_progress==100]==[16,33,50,66,83,100]
        assert all(ctx.target_instrument=="piano" for ctx in provider.calls)
        assert all(events.committed)
        assert provider.calls[0].inputs==(original,)
        assert PROVIDERS=={}
    asyncio.run(check())


@pytest.mark.parametrize("error,code,retry",[
    (RuntimeError("secret-sentinel"),"PROVIDER_FAILED",False),
    (PermanentProviderError(),"PROVIDER_FAILED",False),
    (RetryableProviderError(),"PROVIDER_RETRYABLE",True),
])
def test_provider_error_boundary(tmp_path,error,code,retry,capsys,caplog):
    async def check():
        c,storage,_=environment(tmp_path)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        provider=Provider(error=error)
        for generation in range(1,4) if retry else (1,):
            c.db.outbox[(JOB,"DOWNLOAD",generation)]["available_at"]=datetime.now(timezone.utc)
            await run_stage(StageMessage(JOB,"DOWNLOAD",generation),connection=c,storage=storage,
                            providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        assert c.db.jobs[JOB]["status"]=="FAILED" and c.db.jobs[JOB]["error_code"]==code
        assert len(c.db.attempts)==(3 if retry else 1)
        assert "secret-sentinel" not in str(c.db.jobs)+str(c.db.attempts)
    asyncio.run(check())
    captured=capsys.readouterr()
    assert "secret-sentinel" not in captured.out+captured.err+caplog.text


def test_missing_provider_fails_without_success(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,providers={},event_store=None)
        assert c.db.jobs[JOB]["error_code"]=="PROVIDER_NOT_CONFIGURED" and len(c.db.outbox)==1
    asyncio.run(check())


def test_provider_timeout_closes_provider_and_does_not_retry(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        closed=asyncio.Event()
        async def action(ctx):
            try:
                await asyncio.Future()
            finally:
                closed.set()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
                        providers={PipelineStage.DOWNLOAD:Provider(action=action)},event_store=None,provider_timeout=.01)
        assert closed.is_set() and c.db.jobs[JOB]["error_code"]=="PROVIDER_TIMEOUT" and len(c.db.outbox)==1
    asyncio.run(check())


def test_duplicate_validates_completed_output_without_running_provider(tmp_path):
    async def check():
        c,storage,original=environment(tmp_path)
        provider=Provider()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        args=dict(connection=c,storage=storage,providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        assert len(provider.calls)==1
        storage.delete(original)
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        assert len(provider.calls)==1 and c.db.jobs[JOB]["error_code"]=="ARTIFACT_INVALID"
    asyncio.run(check())


@pytest.mark.parametrize("order",["cancel_first","complete_first"])
def test_cancel_completion_race(tmp_path,order):
    async def check():
        c,storage,_=environment(tmp_path)
        entered,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def action(ctx):
            entered.set()
            try:
                await release.wait()
                return ctx.inputs
            finally:
                closed.set()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        task=asyncio.create_task(run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:Provider(action=action)},event_store=None,cancellation_interval=.001))
        try:
            await asyncio.wait_for(entered.wait(),1)
            if order=="cancel_first":
                c.db.jobs[JOB]["status"]="CANCEL_REQUESTED"
                await asyncio.wait_for(closed.wait(),1)
            release.set()
            await task
            assert c.db.jobs[JOB]["status"]==("CANCELED" if order=="cancel_first" else "RUNNING")
            assert len(c.db.outbox)==(1 if order=="cancel_first" else 2)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        assert not c.db.locks and not c.listeners
    asyncio.run(check())


def test_monitor_connection_loss_fences_provider_result(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        entered,closed=asyncio.Event(),asyncio.Event()
        async def action(ctx):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                closed.set()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        task=asyncio.create_task(run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:Provider(action=action)},event_store=None,cancellation_interval=.001))
        await asyncio.wait_for(entered.wait(),1)
        c.terminate()
        with pytest.raises(InfrastructureUnavailable):
            await asyncio.wait_for(task,1)
        assert closed.is_set() and len(c.db.outbox)==1
    asyncio.run(check())


def test_metadata_collision_becomes_artifact_failure(tmp_path):
    async def check():
        c,storage,original=environment(tmp_path)
        async def action(ctx):
            output=storage.put(JOB,f"attempt_{ctx.attempt_id}_new.wav",ROLE,io.BytesIO(b"def"),"test","1")
            return (output.model_copy(update={"id":original.id}),)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:Provider(action=action)},event_store=None)
        assert c.db.jobs[JOB]["error_code"]=="ARTIFACT_INVALID" and len(c.db.outbox)==1
        assert c.db.artifacts[original.id]==original.model_dump()
    asyncio.run(check())


def test_mutating_context_input_cannot_invent_a_reused_db_reference(tmp_path):
    from uuid import uuid4
    async def check():
        c,storage,original=environment(tmp_path)
        async def action(ctx):
            ctx.inputs[0].id=str(uuid4())
            return ctx.inputs
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:Provider(action=action)},event_store=None)
        assert c.db.jobs[JOB]["error_code"]=="ARTIFACT_INVALID"
        assert list(c.db.artifacts)==[original.id] and len(c.db.outbox)==1
    asyncio.run(check())


def test_target_change_invalidates_duplicate_fingerprint(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        provider=Provider()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        args=dict(connection=c,storage=storage,providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        c.db.jobs[JOB]["target_instrument"]="guitar"
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        assert len(provider.calls)==1 and c.db.jobs[JOB]["error_code"]=="INPUT_CHANGED"
    asyncio.run(check())


def test_corrupt_input_prevents_provider_invocation(tmp_path):
    async def check():
        c,storage,original=environment(tmp_path)
        with storage.open_read(original) as stream:
            filename=stream.name
        from pathlib import Path
        Path(filename).write_bytes(b"bad")
        provider=Provider()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        assert not provider.calls and c.db.jobs[JOB]["error_code"]=="ARTIFACT_INVALID"
    asyncio.run(check())


@pytest.mark.parametrize("phase",["open","read","close"])
def test_storage_interrupted_error_is_validation_failure_not_caller_cancellation(tmp_path,phase):
    async def check():
        c,storage,_=environment(tmp_path)
        original_open=storage.open_read
        class Stream:
            def __init__(self,inner):
                self.inner=inner
            def __enter__(self):
                return self
            def __exit__(self,*args):
                self.inner.close()
                if phase=="close":
                    raise InterruptedError("secret-sentinel")
            def read(self,size):
                if phase=="read":
                    raise InterruptedError("secret-sentinel")
                return self.inner.read(size)
        def interrupted(ref):
            if phase=="open":
                raise InterruptedError("secret-sentinel")
            return Stream(original_open(ref))
        storage.open_read=interrupted
        provider=Provider()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        assert c.db.jobs[JOB]["error_code"]=="ARTIFACT_INVALID" and not provider.calls
        assert not c.db.locks and not c.listeners
    asyncio.run(check())
