"""Test-owned provider injection; never imported by the deployment app."""
import asyncio
import io
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from musicsheet_common import ArtifactRole,PipelineStage
from musicsheet_pipeline.config import PipelineSettings
from musicsheet_pipeline.contracts import ProviderIdentity
from musicsheet_pipeline.providers import RetryableProviderError,PermanentProviderError
from musicsheet_pipeline.tasks import runtime,_owned_cleanup
from musicsheet_pipeline import celery_app as module
from .redis_transport import VerificationRedisTransport

ROOT=Path(os.environ["MUSICSHEET_LIVE_CONTROL"])
ROLE=dict(zip(PipelineStage,(ArtifactRole.SOURCE_ORIGINAL,ArtifactRole.CANONICAL_AUDIO,
    ArtifactRole.SEPARATED_AUDIO,ArtifactRole.RAW_TRANSCRIPTION,ArtifactRole.QUANTIZED_SCORE,ArtifactRole.PDF)))


def record(name,value):
    with (ROOT/name).open("a") as file:
        file.write(json.dumps(value)+"\n")


class Provider:
    def __init__(self,stage,connection):
        self.stage,self.connection=stage,connection
        index=list(PipelineStage).index(stage)
        previous=ROLE[list(PipelineStage)[index-1]] if index else ArtifactRole.SOURCE_ORIGINAL
        self.identity=ProviderIdentity("live-test","1",{},frozenset({previous}),frozenset({ROLE[stage]}))
    async def run(self,ctx):
        control=ROOT/ctx.message.job_id
        scenario=json.loads((control/"scenario.json").read_text())
        with (control/"calls.jsonl").open("a") as file:
            file.write(json.dumps({"stage":self.stage.value,"generation":ctx.message.generation})+"\n")
        if self.stage==PipelineStage.DOWNLOAD:
            (control/"entered").touch()
            if scenario=="retry_once" and ctx.message.generation==1:
                raise RetryableProviderError()
            if scenario in {"contend","kill","cancel","broker_failure"} and not (control/"release").exists():
                deadline=time.monotonic()+20
                while not (control/"release").exists():
                    if time.monotonic()>deadline:
                        raise PermanentProviderError()
                    await asyncio.sleep(.02)
            if scenario=="broker_failure" and not (control/"db_failed").exists():
                (control/"db_failed").touch()
                self.connection.terminate()
        source=io.BytesIO(b"test artifact\n")
        try:
            async def put():
                return await asyncio.to_thread(ctx.storage.put,ctx.message.job_id,
                    f"attempt_{ctx.attempt_id}_{self.stage.value.lower()}.bin",ROLE[self.stage],source,"live-test","1")
            task=asyncio.create_task(put())
            try:
                output=await asyncio.shield(task)
            except asyncio.CancelledError:
                async def drain():
                    await asyncio.shield(task)
                await _owned_cleanup(drain())
                raise
            return (output,)
        finally:
            source.close()


@asynccontextmanager
async def live_runtime(settings):
    async with runtime(settings) as resources:
        yield SimpleNamespace(connection=resources.connection,storage=resources.storage,
            event_store=resources.event_store,providers={s:Provider(s,resources.connection) for s in PipelineStage})


original_execute=module.execute_task
def execute(*args,**kwargs):
    def sleeper(seconds):
        record("retry-delay.jsonl",{"phase":"start","time":time.monotonic()})
        time.sleep(seconds)
        record("retry-delay.jsonl",{"phase":"end","time":time.monotonic()})
    return original_execute(*args,**kwargs,sleeper=sleeper)
module.execute_task=execute
app=module.create_celery_app(PipelineSettings.from_env(),runtime_factory=live_runtime,
    queue_prefix=os.environ["MUSICSHEET_LIVE_QUEUE_PREFIX"])
app.conf.broker_transport=VerificationRedisTransport
app.conf.broker_transport_options={**app.conf.broker_transport_options,
    "global_keyprefix":os.environ["MUSICSHEET_LIVE_KEY_PREFIX"],"visibility_timeout":5}
app.conf.result_backend_transport_options={"visibility_timeout":5,"global_keyprefix":os.environ["MUSICSHEET_LIVE_KEY_PREFIX"]}
app.conf.visibility_timeout=5
