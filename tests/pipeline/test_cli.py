import subprocess
import sys
import os
import traceback

import pytest
from musicsheet_pipeline.config import PipelineSettings
from musicsheet_pipeline.cli import main


@pytest.mark.parametrize("field,value",[
    ("DATABASE_URL","secret-sentinel"),("CELERY_BROKER_URL","http://secret-sentinel"),
    ("REDIS_URL","redis://secret-sentinel:not-port"),("CELERY_RESULT_BACKEND","secret-sentinel")])
def test_invalid_urls_never_echo_the_value(field,value):
    env={"DATABASE_URL":"postgresql://localhost/test","CELERY_BROKER_URL":"redis://localhost/0",field:value}
    with pytest.raises(ValueError) as error:
        PipelineSettings.from_env(env)
    assert "secret-sentinel" not in "".join(traceback.format_exception(error.value))


def test_config_repr_hides_credentials_and_resolves_storage(tmp_path):
    s=PipelineSettings.from_env({"DATABASE_URL":"postgresql://test:secret-sentinel@localhost/db","CELERY_BROKER_URL":"redis://:secret-sentinel@localhost/0"},working_directory=tmp_path)
    assert "secret-sentinel" not in repr(s) and s.local_storage_dir==tmp_path/"outputs"


def test_storage_tilde_is_cwd_relative_like_api(tmp_path):
    settings=PipelineSettings.from_env({"LOCAL_STORAGE_DIR":"~/outputs"},working_directory=tmp_path)
    assert settings.local_storage_dir==tmp_path/"~"/"outputs"


@pytest.mark.parametrize("args",[["--poll-interval","nan"],["--poll-interval","secret-sentinel"],["--secret-sentinel"],["--once","--recover-pending"]])
def test_malformed_cli_flags_are_fixed_errors(args,capsys):
    assert main(args)==2
    captured=capsys.readouterr()
    assert "secret-sentinel" not in captured.out+captured.err


def test_missing_cli_configuration_subprocess_is_secret_safe():
    env=dict(os.environ)
    for key in ("DATABASE_URL","CELERY_BROKER_URL","CELERY_RESULT_BACKEND","REDIS_URL"):
        env.pop(key,None)
    result=subprocess.run([sys.executable,"-m","musicsheet_pipeline.cli","--once"],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==1 and "Traceback" not in result.stderr


@pytest.mark.parametrize("mode",["once","recover","poll_cancel"])
def test_cli_runtime_modes_close_resources(mode):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from musicsheet_pipeline.cli import _run
    from musicsheet_pipeline.outbox import enqueue_stage
    from musicsheet_pipeline.contracts import StageMessage
    from .support import JOB,Connection
    from .test_dispatcher import Publisher
    async def check():
        c=Connection()
        if mode!="recover":
            await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",1))
        opened,closed=[],[]
        sent=asyncio.Event()
        @asynccontextmanager
        async def connection(_):
            opened.append(1)
            try:
                yield c
            finally:
                closed.append(1)
                sent.set()
        class OwnedPublisher(Publisher):
            def close(self):
                closed.append("publisher")
        publisher=OwnedPublisher()
        args=SimpleNamespace(once=mode=="once",recover_pending=mode=="recover",poll_interval=.01)
        settings=PipelineSettings.from_env({})
        work=_run(settings,args,connection_factory=connection,publisher_factory=lambda _:publisher)
        if mode=="poll_cancel":
            task=asyncio.create_task(work)
            await asyncio.wait_for(sent.wait(),1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await work==0
        assert len(opened)==closed.count(1)
        assert ("publisher" in closed)==(mode!="recover")
        assert len(c.db.outbox)==1
    asyncio.run(check())


def test_configured_cli_dependency_failure_is_generic_in_subprocess():
    env=dict(os.environ,DATABASE_URL="postgresql://test:secret-sentinel@127.0.0.1:1/test",CELERY_BROKER_URL="redis://127.0.0.1:1/0")
    result=subprocess.run([sys.executable,"-m","musicsheet_pipeline.cli","--once"],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==1 and "secret-sentinel" not in result.stdout+result.stderr
    assert "Traceback" not in result.stderr
