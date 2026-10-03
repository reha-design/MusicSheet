"""At-least-once delivery of durable outbox rows, one transaction per message."""
import asyncio

from .contracts import StageMessage
from .models import TERMINAL


class DispatchUnavailable(Exception):
    def __init__(self):
        super().__init__("Pipeline dispatch is unavailable")


async def _publish(publisher,message,task_id):
    task=asyncio.create_task(asyncio.to_thread(publisher.publish,message,task_id=task_id))
    canceled=False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            canceled=True
        except Exception:
            break
    if canceled:
        task.exception()
        raise asyncio.CancelledError
    task.result()


async def dispatch_once(connection,publisher,*,limit=100):
    if type(limit) is not int or not 1<=limit<=100:
        raise ValueError("Invalid dispatch limit")
    count=0
    try:
        while count<limit:
            async with connection.transaction():
                row=await connection.fetchrow(
                    "/* pipeline.dispatch.next */ SELECT o.*,j.status FROM pipeline_outbox o JOIN jobs j ON j.id=o.job_id "
                    "WHERE o.published_at IS NULL AND o.available_at<=CURRENT_TIMESTAMP "
                    "ORDER BY o.available_at,o.id LIMIT 1 FOR UPDATE OF o SKIP LOCKED")
                if row is None:
                    break
                if row["status"] not in TERMINAL:
                    await _publish(publisher,StageMessage(row["job_id"],row["stage"],row["generation"]),row["id"])
                await connection.execute("/* pipeline.dispatch.sent */ UPDATE pipeline_outbox SET published_at=CURRENT_TIMESTAMP WHERE id=$1",row["id"])
            count+=1
        return count
    except Exception:
        raise DispatchUnavailable() from None


class CeleryPublisher:
    def __init__(self,settings,*,queue_prefix=""):
        from .celery_app import create_celery_app
        self.app=create_celery_app(settings,queue_prefix=queue_prefix)
        self.queue_prefix=queue_prefix
        self.connection=self.app.connection_for_write()

    def publish(self,message,*,task_id):
        from .celery_app import TASK_NAMES,QUEUES
        try:
            self.app.send_task(TASK_NAMES[message.stage],kwargs={"job_id":message.job_id,"generation":message.generation},
                task_id=task_id,queue=self.queue_prefix+QUEUES[message.stage],connection=self.connection,retry=False,ignore_result=True)
        except Exception:
            raise DispatchUnavailable() from None

    def close(self):
        try:
            self.connection.release()
        finally:
            self.app.close()
