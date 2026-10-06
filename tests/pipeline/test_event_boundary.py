import asyncio

import pytest
from musicsheet_common import PipelineStage
from musicsheet_pipeline.runner import run_stage
from musicsheet_pipeline.contracts import StageMessage,InfrastructureUnavailable
from musicsheet_pipeline.outbox import enqueue_stage

from .runner_support import environment,Provider,Events
from .support import JOB


def test_redis_failure_after_commit_does_not_rerun_provider(tmp_path,caplog):
    async def check():
        c,storage,_=environment(tmp_path)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        provider=Provider()
        args=dict(connection=c,storage=storage,providers={PipelineStage.DOWNLOAD:provider},event_store=Events(c,error=RuntimeError("secret-sentinel")))
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        assert len(provider.calls)==1 and c.db.jobs[JOB]["overall_progress"]==16
    asyncio.run(check())
    assert "Pipeline event publication failed" in caplog.text
    assert "secret-sentinel" not in caplog.text


def test_database_failure_emits_no_event(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        c.fail_query=True
        events=Events(c)
        with pytest.raises(InfrastructureUnavailable):
            await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
                providers={PipelineStage.DOWNLOAD:Provider()},event_store=events)
        assert events.events==[]
    asyncio.run(check())


def test_completion_transaction_failure_emits_no_success_event(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        async def action(ctx):
            c.fail_outbox=True
            return ctx.inputs
        events=Events(c)
        with pytest.raises(InfrastructureUnavailable):
            await run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
                providers={PipelineStage.DOWNLOAD:Provider(action=action)},event_store=events)
        assert len(events.events)==1 and events.events[0].stage_progress==0
        assert c.db.jobs[JOB]["overall_progress"]==0 and len(c.db.outbox)==1
    asyncio.run(check())


def test_cancellation_during_committed_event_publication_propagates(tmp_path):
    async def check():
        c,storage,_=environment(tmp_path)
        entered,closed=asyncio.Event(),asyncio.Event()
        class PendingEvent:
            async def publish(self,event):
                if event.stage_progress==100:
                    entered.set()
                    try:
                        await asyncio.Future()
                    finally:
                        closed.set()
        provider=Provider()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        task=asyncio.create_task(run_stage(StageMessage(JOB,"DOWNLOAD",1),connection=c,storage=storage,
            providers={PipelineStage.DOWNLOAD:provider},event_store=PendingEvent()))
        try:
            await asyncio.wait_for(entered.wait(),1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set() and len(provider.calls)==1 and c.db.jobs[JOB]["overall_progress"]==16
            assert not c.db.locks and not c.listeners
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())
