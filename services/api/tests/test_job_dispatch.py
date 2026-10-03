"""Registration persists its first dispatch intent in the same transaction."""
import asyncio
import copy
import io
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from musicsheet_api.jobs.uploads import create_upload_job
from musicsheet_storage import LocalStorage

from test_job_routes import api_app,SOURCE_URL
from test_job_uploads import FakeConnection,FakePool


class Connection(FakeConnection):
    def __init__(self,*,fail_outbox=False):
        super().__init__()
        self.jobs={}
        self.artifacts={}
        self.outbox={}
        self.fail_outbox=fail_outbox
    @asynccontextmanager
    async def transaction(self):
        before=copy.deepcopy((self.jobs,self.artifacts,self.outbox))
        self.transaction_events.append("begin")
        try:
            yield
        except BaseException:
            self.jobs,self.artifacts,self.outbox=before
            self.transaction_events.append("rollback")
            raise
        else:
            self.transaction_events.append("commit")
    async def fetchrow(self,query,*args):
        row=await super().fetchrow(query,*args)
        (self.jobs if query.startswith("INSERT INTO jobs") else self.artifacts)[row["id"]]=row
        return row
    async def execute(self,query,*args):
        assert "INSERT INTO pipeline_outbox" in query
        if self.fail_outbox:
            raise RuntimeError("secret-sentinel")
        self.outbox[(args[1],args[2],args[3])]=args[0]
        return "INSERT 0 1"


@pytest.mark.parametrize("failure",[False,True])
def test_youtube_registration_atomically_reserves_download_without_broker(failure,capsys,caplog):
    c=Connection(fail_outbox=failure)
    app=api_app()
    with TestClient(app) as client:
        app.state.db_pool=FakePool(c)
        response=client.post("/api/v1/jobs",json={"source_url":SOURCE_URL})
    assert response.status_code==(503 if failure else 201)
    if failure:
        assert c.jobs==c.outbox=={} and c.transaction_events==["begin","rollback"]
    else:
        job=response.json()
        assert job["status"]=="PENDING" and len(c.jobs)==len(c.outbox)==1
        assert (job["id"],"DOWNLOAD",1) in c.outbox and c.transaction_events==["begin","commit"]
    captured=capsys.readouterr()
    assert "secret-sentinel" not in response.text+captured.out+captured.err+caplog.text


@pytest.mark.parametrize("failure",[False,True])
def test_upload_outbox_failure_rolls_back_metadata_and_file(tmp_path,failure):
    async def check():
        c=Connection(fail_outbox=failure)
        storage=LocalStorage(tmp_path)
        args=dict(file=io.BytesIO(b"abc"),original_filename="test.wav",target_instrument="piano",pool=FakePool(c),storage=storage,max_upload_bytes=10)
        if failure:
            with pytest.raises(RuntimeError):
                await create_upload_job(**args)
            assert c.jobs==c.artifacts==c.outbox=={}
            assert not list(tmp_path.glob("*/*.wav"))
        else:
            job=await create_upload_job(**args)
            assert len(c.jobs)==len(c.artifacts)==len(c.outbox)==1 and (job.id,"DOWNLOAD",1) in c.outbox
            assert len(list(tmp_path.glob("*/*.wav")))==1
    asyncio.run(check())


def test_upload_cancellation_after_commit_keeps_file_and_outbox(tmp_path):
    async def check():
        committed,release=asyncio.Event(),asyncio.Event()
        class SlowCommit(Connection):
            @asynccontextmanager
            async def transaction(self):
                async with super().transaction():
                    yield
                committed.set()
                await release.wait()
        c=SlowCommit()
        task=asyncio.create_task(create_upload_job(file=io.BytesIO(b"abc"),original_filename="test.wav",target_instrument="piano",
            pool=FakePool(c),storage=LocalStorage(tmp_path),max_upload_bytes=10))
        try:
            await asyncio.wait_for(committed.wait(),1)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(c.jobs)==len(c.artifacts)==len(c.outbox)==1
            assert len(list(tmp_path.glob("*/*.wav")))==1
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())


@pytest.mark.parametrize("directory",["outputs","~/outputs","nested/files"])
def test_worker_and_api_resolve_identical_storage_directory(tmp_path,directory):
    from musicsheet_api.config import Settings
    from musicsheet_pipeline.config import PipelineSettings
    env={"LOCAL_STORAGE_DIR":directory}
    assert Settings.from_env(env,working_directory=tmp_path).local_storage_dir==PipelineSettings.from_env(env,working_directory=tmp_path).local_storage_dir
