import asyncio
import traceback
from datetime import datetime,timezone,timedelta

import pytest
from musicsheet_pipeline.contracts import StageMessage
from musicsheet_pipeline.dispatcher import dispatch_once,DispatchUnavailable
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.runner import run_stage
from musicsheet_common import PipelineStage

from .support import JOB,Connection
from .runner_support import environment,Provider


class Publisher:
    def __init__(self,error=None):
        self.calls=[]
        self.error=error
    def publish(self,message,*,task_id):
        self.calls.append((message,task_id))
        if self.error:
            raise self.error


@pytest.mark.parametrize("failure",["publish","commit"])
def test_failure_keeps_outbox_pending_for_same_id_redelivery(failure):
    async def check():
        c=Connection()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        publisher=Publisher(RuntimeError("secret-sentinel") if failure=="publish" else None)
        c.fail_commit=failure=="commit"
        with pytest.raises(DispatchUnavailable) as error:
            await dispatch_once(c,publisher)
        assert "secret-sentinel" not in "".join(traceback.format_exception(error.value))
        assert next(iter(c.db.outbox.values()))["published_at"] is None
        c.fail_commit=False
        publisher.error=None
        assert await dispatch_once(c,publisher)==1
        assert len(publisher.calls)==2 and publisher.calls[0]==publisher.calls[1]
    asyncio.run(check())


@pytest.mark.parametrize("status",["COMPLETED","FAILED","CANCELED","CANCEL_REQUESTED"])
def test_terminal_suppression_preserves_cancel_requested_delivery(status):
    async def check():
        c=Connection()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        c.db.jobs[JOB]["status"]=status
        publisher=Publisher()
        assert await dispatch_once(c,publisher)==1
        assert len(publisher.calls)==(1 if status=="CANCEL_REQUESTED" else 0)
    asyncio.run(check())


@pytest.mark.parametrize("delay",[False,True])
def test_register_cancel_dispatch_worker_finalizes_without_provider(tmp_path,delay):
    async def check():
        c,storage,_=environment(tmp_path)
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1),delay_seconds=5 if delay else 0)
        c.db.jobs[JOB]["status"]="CANCEL_REQUESTED"
        publisher=Publisher()
        if delay:
            assert await dispatch_once(c,publisher)==0
            c.db.outbox[(JOB,"DOWNLOAD",1)]["available_at"]=datetime.now(timezone.utc)
        assert await dispatch_once(c,publisher)==1
        provider=Provider()
        await run_stage(publisher.calls[0][0],connection=c,storage=storage,providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        assert not provider.calls and c.db.jobs[JOB]["status"]=="CANCELED" and len(c.db.outbox)==1
    asyncio.run(check())


@pytest.mark.parametrize("limit",[True,0,101,1.5])
def test_dispatch_limit_is_exact_bounded_integer(limit):
    with pytest.raises(ValueError):
        asyncio.run(dispatch_once(Connection(),Publisher(),limit=limit))


@pytest.mark.parametrize("cancels",[0,1,2])
def test_concurrent_dispatch_skips_owned_row_and_cancellation_drains_publish(cancels):
    import threading
    async def check():
        c=Connection()
        await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        entered,release=threading.Event(),threading.Event()
        class Blocking(Publisher):
            def publish(self,*args,**kwargs):
                entered.set()
                assert release.wait(2)
                super().publish(*args,**kwargs)
        publisher=Blocking()
        task=asyncio.create_task(dispatch_once(c,publisher))
        try:
            assert await asyncio.to_thread(entered.wait,1)
            assert await dispatch_once(Connection(c.db),Publisher())==0
            for _ in range(cancels):
                task.cancel()
                await asyncio.sleep(.01)
                assert not task.done()
            release.set()
            if cancels:
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert next(iter(c.db.outbox.values()))["published_at"] is None
            else:
                assert await task==1
            assert not c.db.outbox_locks
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())


def test_publisher_skips_optional_backend_and_sends_json_payload(monkeypatch):
    from contextlib import contextmanager
    from musicsheet_pipeline.dispatcher import CeleryPublisher
    from musicsheet_pipeline.config import PipelineSettings
    settings=PipelineSettings.from_env({"DATABASE_URL":"postgresql://localhost/test","CELERY_BROKER_URL":"redis://localhost/0","CELERY_RESULT_BACKEND":"redis://localhost/1"})
    publisher=CeleryPublisher(settings)
    backend_calls,sent=[],[]
    def backend_call(*args,**kwargs):
        backend_calls.append(1)
        raise RuntimeError("secret-sentinel")
    monkeypatch.setattr(publisher.app.backend,"on_task_call",backend_call)
    @contextmanager
    def producer_context(producer=None):
        class Producer:
            connection=publisher.connection
        yield Producer()
    monkeypatch.setattr(publisher.app,"producer_or_acquire",producer_context)
    monkeypatch.setattr(publisher.app.amqp,"send_task_message",lambda producer,name,message,**kwargs:sent.append((name,message,kwargs)))
    try:
        try:
            publisher.publish(StageMessage(JOB,"DOWNLOAD",1),task_id="test-message")
        except DispatchUnavailable:
            assert backend_calls==[1]
            raise
        assert not backend_calls and len(sent)==1
        assert sent[0][0]=="pipeline.tasks.download"
        assert sent[0][1].body[1]=={"job_id":JOB,"generation":1}
        assert sent[0][2]["retry"] is False
    finally:
        publisher.close()
