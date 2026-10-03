"""Opt-in v2 contracts; the marked disposable database guard remains mandatory."""
import asyncio
from uuid import uuid4

import asyncpg
import pytest

from musicsheet_api.migrations.runner import MIGRATIONS, apply_migrations
from musicsheet_pipeline.contracts import StageMessage, StageBusy
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.repository import PipelineRepository
from test_postgres_persistence import database_url, clean_database, _assert_disposable

pytestmark = pytest.mark.integration


def run(coroutine):
    failed = False
    try:
        return asyncio.run(asyncio.wait_for(coroutine, 15))
    except (AssertionError, ValueError):
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
