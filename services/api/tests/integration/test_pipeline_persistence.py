"""Opt-in v2 contracts; the marked disposable database guard remains mandatory."""
import asyncio
from uuid import uuid4

import asyncpg
import pytest

from musicsheet_api.migrations.runner import MIGRATIONS, apply_migrations
from musicsheet_pipeline.contracts import StageMessage, StageBusy
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.repository import PipelineRepository
from musicsheet_pipeline.contracts import ProviderIdentity
from musicsheet_common import ArtifactRef,ArtifactRole
from musicsheet_pipeline.dispatcher import dispatch_once
from musicsheet_pipeline.outbox import recover_pending
from test_postgres_persistence import database_url, clean_database, _assert_disposable

pytestmark = pytest.mark.integration


def run(coroutine):
    failed = False
    try:
        return asyncio.run(asyncio.wait_for(coroutine, 15))
    except AssertionError:
        raise
    except Exception:
        failed = True
    if failed:
        pytest.fail("Pipeline PostgreSQL operation failed", pytrace=False)


def test_v1_upgrade_preserves_jobs_artifacts_attempts(clean_database):
    async def check():
        assert await apply_migrations(clean_database, migrations=MIGRATIONS[:1]) == [1]
        c = await asyncpg.connect(clean_database)
        job, attempt, artifact = (str(uuid4()) for _ in range(3))
        try:
            await _assert_disposable(c)
            await c.execute("INSERT INTO jobs(id,source_type) VALUES($1,'UPLOAD')",job)
            await c.execute("INSERT INTO stage_attempts(id,job_id,stage,attempt,status) VALUES($1,$2,'DOWNLOAD',2,'COMPLETED')",attempt,job)
            await c.execute("INSERT INTO artifacts(id,job_id,role,filename,uri,mime_type,size_bytes,sha256) VALUES($1,$2,'SOURCE_ORIGINAL','input.wav','file:///test/input.wav','audio/wav',3,$3)",artifact,job,"a"*64)
            assert await apply_migrations(clean_database) == [2]
            row = await c.fetchrow("SELECT attempt,generation,input_fingerprint,output_artifact_ids::text AS outputs FROM stage_attempts WHERE id=$1",attempt)
            assert tuple(row)==(2,2,None,"[]")
            assert await c.fetchval("SELECT count(*) FROM artifacts WHERE id=$1",artifact)==1
            assert await c.fetchval("SELECT status FROM jobs WHERE id=$1",job)=="PENDING"
            assert await c.fetchval("SELECT count(*) FROM pipeline_outbox")==0
            assert await apply_migrations(clean_database)==[]
        finally:
            await c.close()
    run(check())


def test_v2_duplicate_history_rolls_back(clean_database):
    async def check():
        await apply_migrations(clean_database,migrations=MIGRATIONS[:1])
        c = await asyncpg.connect(clean_database)
        job=str(uuid4())
        try:
            await c.execute("INSERT INTO jobs(id,source_type) VALUES($1,'UPLOAD')",job)
            for _ in range(2):
                await c.execute("INSERT INTO stage_attempts(id,job_id,stage,status) VALUES($1,$2,'DOWNLOAD','FAILED')",str(uuid4()),job)
            with pytest.raises(asyncpg.PostgresError):
                await apply_migrations(clean_database)
            assert await c.fetchval("SELECT count(*) FROM schema_migrations WHERE version=2")==0
            assert await c.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name='jobs' AND column_name='active_attempt_id'")==0
            assert await c.fetchval("SELECT count(*) FROM stage_attempts WHERE job_id=$1",job)==2
        finally:
            await c.close()
    run(check())


def test_concurrent_migration_applies_once(clean_database):
    async def check():
        assert sorted(await asyncio.gather(apply_migrations(clean_database),apply_migrations(clean_database))) == [[],[1,2]]
    run(check())


def test_two_sessions_only_one_claim(clean_database):
    async def check():
        await apply_migrations(clean_database)
        c = await asyncpg.connect(clean_database)
        second = await asyncpg.connect(clean_database)
        job=str(uuid4())
        try:
            await c.execute("INSERT INTO jobs(id,source_type) VALUES($1,'UPLOAD')",job)
            message=StageMessage(job,"DOWNLOAD",1)
            await enqueue_stage(c,message)
            async with PipelineRepository(c).stage_session(message):
                with pytest.raises(StageBusy):
                    async with PipelineRepository(second).stage_session(message):
                        pass
                assert await c.fetchval("SELECT count(*) FROM stage_attempts WHERE job_id=$1",job)==0
            async with PipelineRepository(second).stage_session(message):
                pass
        finally:
            await second.close()
            await c.close()
    run(check())


async def create_job(connection):
    job=str(uuid4())
    await connection.execute("INSERT INTO jobs(id,source_type) VALUES($1,'UPLOAD')",job)
    ref=ArtifactRef(id=str(uuid4()),job_id=job,role=ArtifactRole.SOURCE_ORIGINAL,
        filename="source.wav",uri="file:///test/source.wav",mime_type="audio/wav",size_bytes=3,
        sha256="a"*64,producer="test",producer_version="1")
    await connection.execute("INSERT INTO artifacts(id,job_id,role,filename,uri,mime_type,size_bytes,sha256,producer,producer_version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        ref.id,job,ref.role.value,ref.filename,ref.uri,ref.mime_type,ref.size_bytes,ref.sha256,ref.producer,ref.producer_version)
    await enqueue_stage(connection,StageMessage(job,"DOWNLOAD",1))
    return job,ref


IDENTITY=ProviderIdentity("test","1",{},frozenset({ArtifactRole.SOURCE_ORIGINAL}),frozenset({ArtifactRole.SOURCE_ORIGINAL}))


@pytest.mark.parametrize("cancel_first",[True,False])
def test_actual_cancel_and_completion_order_preserves_terminal(clean_database,cancel_first):
    async def check():
        await apply_migrations(clean_database)
        c=await asyncpg.connect(clean_database,timeout=2,command_timeout=5)
        second=await asyncpg.connect(clean_database,timeout=2,command_timeout=5)
        job,ref=await create_job(c)
        try:
            from musicsheet_common import PipelineStage
            for stage in PipelineStage:
                message=StageMessage(job,stage,1)
                async with PipelineRepository(c).stage_session(message) as session:
                    prepared=await session.prepare(IDENTITY)
                    if stage.value=="RENDER" and cancel_first:
                        async with second.transaction():
                            await second.execute("UPDATE jobs SET status='CANCEL_REQUESTED' WHERE id=$1",job)
                            completion=asyncio.create_task(session.complete(prepared.context.attempt_id,(ref,)))
                            await asyncio.sleep(.01)
                            assert not completion.done()
                        result=await completion
                    else:
                        result=await session.complete(prepared.context.attempt_id,(ref,))
            assert result.job.status.value==("CANCELED" if cancel_first else "COMPLETED")
            late=await second.fetchval("UPDATE jobs SET status='CANCEL_REQUESTED' WHERE id=$1 AND status IN ('PENDING','RUNNING','RETRYING') RETURNING id",job)
            assert late is None
        finally:
            await second.close()
            await c.close()
    run(check())


def test_actual_three_attempts_and_completed_reference_reuse(clean_database):
    async def check():
        await apply_migrations(clean_database)
        c=await asyncpg.connect(clean_database,timeout=2,command_timeout=5)
        try:
            job,ref=await create_job(c)
            for generation in (1,2,3):
                await c.execute("UPDATE pipeline_outbox SET available_at=CURRENT_TIMESTAMP WHERE job_id=$1",job)
                async with PipelineRepository(c).stage_session(StageMessage(job,"DOWNLOAD",generation)) as session:
                    p=await session.prepare(IDENTITY)
                    await session.fail(p.context.attempt_id,code="PROVIDER_RETRYABLE",retryable=True)
            assert await c.fetchval("SELECT status FROM jobs WHERE id=$1",job)=="FAILED"
            assert [(r["attempt"],r["generation"]) for r in await c.fetch("SELECT attempt,generation FROM stage_attempts WHERE job_id=$1 ORDER BY attempt",job)]==[(1,1),(2,2),(3,3)]
            assert await c.fetchval("SELECT count(*) FROM pipeline_outbox WHERE job_id=$1",job)==3
            other,source=await create_job(c)
            async with PipelineRepository(c).stage_session(StageMessage(other,"DOWNLOAD",1)) as session:
                p=await session.prepare(IDENTITY)
                await session.complete(p.context.attempt_id,(source,))
                duplicate=await session.prepare(IDENTITY)
                assert duplicate.action=="DUPLICATE" and duplicate.completed_outputs==(source,)
            assert await c.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1",other)==1
        finally:
            await c.close()
    run(check())


def test_actual_dispatchers_lock_one_row_and_recovery_is_bounded(clean_database):
    async def check():
        import threading
        await apply_migrations(clean_database)
        c=await asyncpg.connect(clean_database,timeout=2,command_timeout=5)
        second=await asyncpg.connect(clean_database,timeout=2,command_timeout=5)
        entered,release=threading.Event(),threading.Event()
        calls=[]
        class Publisher:
            def publish(self,message,*,task_id):
                entered.set()
                assert release.wait(2)
                calls.append(task_id)
        task=None
        try:
            job,_=await create_job(c)
            task=asyncio.create_task(dispatch_once(c,Publisher()))
            assert await asyncio.to_thread(entered.wait,1)
            assert await dispatch_once(second,Publisher())==0
            release.set()
            assert await task==1 and len(calls)==1
            for _ in range(3):
                await c.execute("INSERT INTO jobs(id,source_type) VALUES($1,'YOUTUBE')",str(uuid4()))
            async with c.transaction(): assert await recover_pending(c,limit=2)==2
            async with c.transaction(): assert await recover_pending(c,limit=2)==1
            async with c.transaction(): assert await recover_pending(c,limit=2)==0
        finally:
            release.set()
            if task:
                await asyncio.gather(task,return_exceptions=True)
            await second.close()
            await c.close()
    run(check())
