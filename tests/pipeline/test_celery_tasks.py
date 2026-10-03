import asyncio
import subprocess
import sys
import traceback
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from celery.exceptions import Retry,Reject
from musicsheet_common import PipelineStage
from musicsheet_pipeline.config import PipelineSettings
from musicsheet_pipeline.celery_app import create_celery_app,TASK_NAMES,QUEUES
from musicsheet_pipeline.tasks import execute_task
from musicsheet_pipeline.contracts import StageMessage,InfrastructureUnavailable
from musicsheet_pipeline.outbox import enqueue_stage

from .runner_support import environment,Provider
from .support import JOB


def settings():
    return PipelineSettings.from_env({"DATABASE_URL":"postgresql://test:secret-sentinel@localhost/test","CELERY_BROKER_URL":"redis://localhost:6379/0"})


def test_named_eager_tasks_own_same_loop_resources_and_execute_six_stages(tmp_path):
    c,storage,_=environment(tmp_path)
    provider=Provider()
    opened,closed=[],[]
    @asynccontextmanager
    async def runtime(_):
        loop=asyncio.get_running_loop()
        opened.append(loop)
        try:
            yield SimpleNamespace(connection=c,storage=storage,providers={s:provider for s in PipelineStage},event_store=None)
        finally:
            assert asyncio.get_running_loop() is loop
            closed.append(loop)
    asyncio.run(enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1)))
    app=create_celery_app(settings(),runtime_factory=runtime)
    for stage in PipelineStage:
        result=app.tasks[TASK_NAMES[stage]].apply(kwargs={"job_id":JOB,"generation":1},throw=True)
        assert result.successful()
    assert len(opened)==len(closed)==6 and c.db.jobs[JOB]["status"]=="COMPLETED"
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
    assert app.conf.accept_content==["json"] and app.conf.worker_prefetch_multiplier==1
    assert app.conf.broker_transport_options["visibility_timeout"]==3600
    assert app.conf.visibility_timeout==3600
    assert app.conf.task_serializer==app.conf.result_serializer=="json"
    assert app.conf.result_backend is None
    assert {v["queue"] for v in app.conf.task_routes.values()}==set(QUEUES.values())
    app.close()


@pytest.mark.parametrize("publish_failure",[False,True])
def test_infrastructure_retry_or_delayed_requeue_is_sanitized(publish_failure):
    delays=[]
    @asynccontextmanager
    async def broken(_):
        raise RuntimeError("secret-sentinel")
        yield
    class Task:
        def retry(self,**kwargs):
            assert kwargs["countdown"]==5 and kwargs["max_retries"] is None
            assert isinstance(kwargs["exc"],InfrastructureUnavailable)
            if publish_failure:
                raise RuntimeError("secret-sentinel")
            raise Retry(exc=kwargs["exc"])
    with pytest.raises(Reject if publish_failure else Retry) as error:
        execute_task(Task(),StageMessage(JOB,"DOWNLOAD",1),settings=settings(),runtime_factory=broken,sleeper=delays.append)
    assert delays==([5] if publish_failure else [])
    if publish_failure:
        assert error.value.requeue
    assert "secret-sentinel" not in "".join(traceback.format_exception(error.value))


def test_import_has_no_network_api_or_model_side_effects():
    code='import socket,sys; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(AssertionError("network")); import musicsheet_pipeline.celery_app; assert not any(n.startswith(("fastapi","musicsheet_api","basic_pitch","torch")) for n in sys.modules)'
    result=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_runtime_cleanup_error_does_not_retry_committed_success(tmp_path,caplog):
    c,storage,_=environment(tmp_path)
    provider=Provider()
    @asynccontextmanager
    async def runtime(_):
        yield SimpleNamespace(connection=c,storage=storage,providers={PipelineStage.DOWNLOAD:provider},event_store=None)
        raise RuntimeError("secret-sentinel")
    class Task:
        def retry(self,**kwargs):
            raise AssertionError("retry after success")
    asyncio.run(enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1)))
    execute_task(Task(),StageMessage(JOB,"DOWNLOAD",1),settings=settings(),runtime_factory=runtime)
    assert len(provider.calls)==1 and c.db.jobs[JOB]["overall_progress"]==16
    assert "Pipeline runtime cleanup failed" in caplog.text and "secret-sentinel" not in caplog.text


def test_apps_do_not_share_injected_runtime_or_queue_prefix(tmp_path):
    c,storage,_=environment(tmp_path)
    used=[]
    def factory(name):
        @asynccontextmanager
        async def runtime(_):
            used.append(name)
            yield SimpleNamespace(connection=c,storage=storage,providers={},event_store=None)
        return runtime
    first=create_celery_app(settings(),runtime_factory=factory("first"),queue_prefix="one_")
    second=create_celery_app(settings(),runtime_factory=factory("second"),queue_prefix="two_")
    asyncio.run(enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1)))
    first.tasks[TASK_NAMES[PipelineStage.DOWNLOAD]].apply(kwargs={"job_id":JOB},throw=True)
    second.tasks[TASK_NAMES[PipelineStage.DOWNLOAD]].apply(kwargs={"job_id":JOB},throw=True)
    assert used==["first","second"]
    assert first.conf.task_routes[TASK_NAMES[PipelineStage.DOWNLOAD]]["queue"]=="one_cpu_io_queue"
    assert second.conf.task_routes[TASK_NAMES[PipelineStage.DOWNLOAD]]["queue"]=="two_cpu_io_queue"
    first.close()
    second.close()
