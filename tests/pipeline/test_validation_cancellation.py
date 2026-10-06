import asyncio
import io
import threading

import pytest
from musicsheet_common import PipelineStage
from musicsheet_pipeline.contracts import StageMessage,InfrastructureUnavailable
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.runner import run_stage

from .runner_support import environment,Provider,ROLE
from .support import JOB


@pytest.mark.parametrize("mode",["input","completed","output"])
@pytest.mark.parametrize("failure",["cancel","lost","external_once","external_twice"])
def test_monitor_runs_during_slow_validation_and_thread_is_drained(tmp_path,mode,failure):
    async def check():
        c,storage,_=environment(tmp_path)
        ready,release=threading.Event(),threading.Event()
        open_read=storage.open_read
        opens=0
        block_at=1 if mode=="input" else 2
        if mode=="completed":
            block_at=3
        class Read:
            def __init__(self,stream,blocked):
                self.stream,self.blocked=stream,blocked
                self.close_count=0
            def __enter__(self):
                return self
            def __exit__(self,*args):
                self.stream.close()
                self.close_count+=1
            def read(self,size):
                assert size==64*1024
                if self.blocked:
                    ready.set()
                    if not release.wait(3):
                        raise OSError("secret-sentinel")
                    self.blocked=False
                return self.stream.read(size)
        streams=[]
        def slow_open(ref):
            nonlocal opens
            opens+=1
            stream=Read(open_read(ref),opens==block_at)
            streams.append(stream)
            return stream
        storage.open_read=slow_open
        async def output(ctx):
            return (ctx.storage.put(JOB,f"attempt_{ctx.attempt_id}_out.wav",ROLE,io.BytesIO(b"def"),"test","1"),)
        provider=Provider(action=output) if mode=="output" else Provider()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        args=dict(connection=c,storage=storage,providers={PipelineStage.DOWNLOAD:provider},event_store=None,cancellation_interval=.001)
        if mode=="completed":
            await run_stage(StageMessage(JOB,"DOWNLOAD",1),**args)
        before_outbox=len(c.db.outbox)
        before_artifacts=len(c.db.artifacts)
        task=asyncio.create_task(run_stage(StageMessage(JOB,"DOWNLOAD",1),**args))
        try:
            assert await asyncio.to_thread(ready.wait,1)
            queries_before=len(c.queries)
            if failure=="cancel":
                c.db.jobs[JOB]["status"]="CANCEL_REQUESTED"
                async def canceled():
                    while c.db.jobs[JOB]["status"]!="CANCELED":
                        await asyncio.sleep(.001)
                await asyncio.wait_for(canceled(),1)
            elif failure=="lost":
                c.terminate()
                await asyncio.sleep(.01)
            else:
                task.cancel()
                await asyncio.sleep(.01)
                if failure=="external_twice":
                    task.cancel()
                    await asyncio.sleep(.01)
            assert not task.done()
            if failure=="cancel":
                assert len(c.queries)>queries_before
            release.set()
            if failure=="lost":
                with pytest.raises(InfrastructureUnavailable):
                    await task
            elif failure.startswith("external"):
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            assert len(c.db.outbox)==before_outbox and len(c.db.artifacts)==before_artifacts
            assert len(provider.calls)==(0 if mode=="input" else 1)
            assert all(s.close_count==1 for s in streams)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        assert not c.db.locks and not c.listeners
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(check())
