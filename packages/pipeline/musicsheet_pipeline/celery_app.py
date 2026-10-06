"""Import-safe Celery factory and deployment app entry point."""
import re

from celery import Celery
from celery.signals import worker_init
from musicsheet_common import PipelineStage

from .config import PipelineSettings
from .contracts import StageMessage
from .tasks import execute_task,runtime

TASK_NAMES={stage:f"pipeline.tasks.{stage.value.lower()}" for stage in PipelineStage}
QUEUES={stage:queue for stage,queue in zip(PipelineStage,
    ("cpu_io_queue","cpu_io_queue","gpu_ai_queue","gpu_ai_queue","cpu_render_queue","cpu_render_queue"))}


def create_celery_app(settings,*,runtime_factory=None,queue_prefix=""):
    if not isinstance(queue_prefix,str) or len(queue_prefix)>64 or (queue_prefix and not re.fullmatch(r"[a-zA-Z0-9_-]+",queue_prefix)):
        raise ValueError("Invalid queue prefix")
    app=Celery("musicsheet_pipeline",broker=settings.broker_url,backend=settings.result_backend)
    app.conf.update(task_acks_late=True,task_reject_on_worker_lost=True,
        task_serializer="json",result_serializer="json",accept_content=["json"],result_accept_content=["json"],
        worker_prefetch_multiplier=1,task_publish_retry=False,broker_connection_timeout=2,
        broker_transport_options={"visibility_timeout":3600,"socket_connect_timeout":2,"socket_timeout":2},
        result_backend_transport_options={"visibility_timeout":3600},visibility_timeout=3600,
        redis_socket_connect_timeout=2,redis_socket_timeout=2,
        task_routes={TASK_NAMES[s]:{"queue":queue_prefix+QUEUES[s]} for s in PipelineStage})
    factory=runtime_factory or runtime
    def register(stage):
        @app.task(name=TASK_NAMES[stage],bind=True,max_retries=None,ignore_result=True,shared=False,lazy=False)
        def stage_task(self,job_id,generation=1):
            message=StageMessage(job_id,stage,generation)
            execute_task(self,message,settings=settings,runtime_factory=factory)
        return stage_task
    for stage in PipelineStage:
        register(stage)
    def require_configuration(sender=None,**kwargs):
        if getattr(sender,"app",None) is app:
            try:
                settings.require_ready()
            except ValueError:
                raise SystemExit("Pipeline database and broker configuration are required") from None
    worker_init.connect(require_configuration,weak=False)
    return app


# Celery loads this module in its CLI process. Construction opens no sockets.
app=create_celery_app(PipelineSettings.from_env())
