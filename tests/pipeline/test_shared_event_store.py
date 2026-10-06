import asyncio

import pytest
from musicsheet_common import JobProgressEvent
from musicsheet_pipeline.events import RedisEventStore,EventStoreUnavailable

from .support import JOB


def progress():
    return JobProgressEvent(job_id=JOB,status="RUNNING",stage="DOWNLOAD",stage_progress=0,overall_progress=0,message="Running")


@pytest.mark.parametrize("response",[[(b"\xff",[])],[(f"job:{JOB}:events",[(f"{n+1}-0",{"payload":progress().model_dump_json()}) for n in range(101)])]])
def test_shared_store_rejects_malformed_utf8_and_over_limit(response):
    class Client:
        async def xread(self,*args,**kwargs):
            return response
    with pytest.raises(EventStoreUnavailable):
        asyncio.run(RedisEventStore(Client()).initial_read(JOB,"0-0"))


@pytest.mark.parametrize("operation",["publish","metadata"])
def test_shared_store_publish_and_metadata_cancellation_propagates(operation):
    async def check():
        entered,closed=asyncio.Event(),asyncio.Event()
        class Client:
            async def pending(self):
                entered.set()
                try:
                    await asyncio.Future()
                finally:
                    closed.set()
            async def xadd(self,*args,**kwargs):
                return await self.pending()
            async def xinfo_stream(self,*args,**kwargs):
                return await self.pending()
        store=RedisEventStore(Client())
        task=asyncio.create_task(store.publish(progress()) if operation=="publish" else store.initial_read(JOB,"1-0"))
        try:
            await asyncio.wait_for(entered.wait(),1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())
