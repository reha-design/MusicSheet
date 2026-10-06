"""Guarded, real PostgreSQL/Redis checks for the shared pipeline execution tools."""
import asyncio
import json
import os
from uuid import UUID, uuid4

import asyncpg
import pytest
from redis.asyncio import Redis
from musicsheet_common import JobStatus
from musicsheet_pipeline.contracts import ProviderIdentity, StageMessage
from musicsheet_pipeline.events import RedisEventStore
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.repository import PipelineRepository
from musicsheet_pipeline.maintenance import scan_stalled, fail_stalled
from musicsheet_pipeline.models import JobObservation
from musicsheet_pipeline.contracts import InfrastructureUnavailable

from test_postgres_persistence import database_url, clean_database, migrated_database, _assert_disposable

pytestmark = pytest.mark.integration
IDENTITY = ProviderIdentity("operator-test", "1", {}, frozenset(), frozenset())


def live(coroutine):
    try:
        return asyncio.run(asyncio.wait_for(coroutine, 20))
    except (AssertionError, ValueError):
        raise
    except Exception:
        pytest.fail("Operator tool disposable integration failed", pytrace=False)


def test_real_progress_commits_and_uses_existing_redis_payload(migrated_database):
    url = os.getenv("MUSICSHEET_TEST_REDIS_URL")
    if not url:
        pytest.skip("MUSICSHEET_TEST_REDIS_URL is unset")
    async def check():
        c = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        observer = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        redis = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        store = RedisEventStore(redis)
        job = str(uuid4())
        key = f"job:{job}:events"
        try:
            await _assert_disposable(c)
            await _assert_disposable(observer)
            await c.execute("INSERT INTO jobs(id,source_type) VALUES($1,'YOUTUBE')", job)
            message = StageMessage(job, "DOWNLOAD", 1)
            await enqueue_stage(c, message)
            async with PipelineRepository(c).stage_session(message) as session:
                prepared = await session.prepare(IDENTITY)
                transition = await session.report_progress(prepared.context.attempt_id, 60)
                row = await observer.fetchrow("SELECT stage_progress,overall_progress FROM jobs WHERE id=$1", job)
                assert tuple(row) == (60, 10)
                from musicsheet_pipeline.runner import _publish
                await _publish(store, transition)
                entries = await store.initial_read(job, "0-0")
                assert len(entries) == 1 and entries[0].event.stage_progress == 60
                raw = await redis.xrange(key)
                assert set(raw[0][1]) == {b"payload"}
                assert json.loads(raw[0][1][b"payload"])["status"] == "RUNNING"
                before = await observer.fetchval("SELECT updated_at FROM jobs WHERE id=$1", job)
                assert await session.report_progress(prepared.context.attempt_id, 30) is None
                assert await observer.fetchval("SELECT updated_at FROM jobs WHERE id=$1", job) == before
                await observer.execute("UPDATE jobs SET status='CANCEL_REQUESTED' WHERE id=$1", job)
                assert await session.report_progress(prepared.context.attempt_id, 80) is None
                await observer.execute("UPDATE jobs SET status='RUNNING' WHERE id=$1", job)
                await enqueue_stage(observer, StageMessage(job, "DOWNLOAD", 2))
                assert await session.report_progress(prepared.context.attempt_id, 80) is None
        finally:
            await redis.delete(key)
            await redis.aclose()
            await c.close()
            await observer.close()
    live(check())


async def insert_stalled(c, status="RUNNING"):
    job, attempt = str(uuid4()), str(uuid4())
    await c.execute("INSERT INTO jobs(id,source_type,status,source_url,active_attempt_id,updated_at) "
                    "VALUES($1,'YOUTUBE',$2,'https://secret-sentinel',$3,CURRENT_TIMESTAMP-INTERVAL '3 hours')",
                    job, status, attempt)
    await c.execute("INSERT INTO stage_attempts(id,job_id,stage,attempt,status,error_detail,started_at) "
                    "VALUES($1,$2,'DOWNLOAD',1,'RUNNING','secret-sentinel',CURRENT_TIMESTAMP-INTERVAL '3 hours')",
                    attempt, job)
    await enqueue_stage(c, StageMessage(job, "DOWNLOAD", 1))
    row = await c.fetchrow("SELECT * FROM jobs WHERE id=$1", job)
    return JobObservation(job, row["status"], row["current_stage"], row["updated_at"], attempt)


def test_real_scan_filters_orders_limits_and_latest_attempt(migrated_database):
    async def check():
        c = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        try:
            await _assert_disposable(c)
            first = await insert_stalled(c)
            pending = await insert_stalled(c, "PENDING")
            retrying = await insert_stalled(c, "RETRYING")
            cancel = await insert_stalled(c, "CANCEL_REQUESTED")
            terminal = await insert_stalled(c, "COMPLETED")
            null = await insert_stalled(c)
            fresh = await insert_stalled(c)
            await c.execute("UPDATE jobs SET updated_at=NULL WHERE id=$1", null.job_id)
            await c.execute("UPDATE jobs SET updated_at=CURRENT_TIMESTAMP WHERE id=$1", fresh.job_id)
            await c.execute("UPDATE jobs SET updated_at=CURRENT_TIMESTAMP-INTERVAL '4 hours' WHERE id=ANY($1::varchar[])",
                            [pending.job_id, retrying.job_id, cancel.job_id])
            ids = sorted([str(uuid4()), str(uuid4())])
            for n, id in enumerate(ids, 2):
                await c.execute("INSERT INTO stage_attempts(id,job_id,stage,attempt,generation,status,started_at,error_code) "
                    "VALUES($1,$2,'DOWNLOAD',$3,$3,'FAILED','2026-01-01T00:00:00Z','PROVIDER_FAILED')", id, first.job_id, n)
            await c.execute("UPDATE stage_attempts SET started_at='2025-01-01T00:00:00Z' WHERE id=$1", first.active_attempt_id)
            await c.execute("INSERT INTO stage_attempts(id,job_id,stage,attempt,status,started_at) "
                            "VALUES($1,$2,'DOWNLOAD',4,'FAILED',NULL)", str(uuid4()), first.job_id)
            rows = await scan_stalled(c)
            assert [r.observation.job_id for r in rows] == sorted([pending.job_id,retrying.job_id,cancel.job_id])+[first.job_id]
            assert rows[-1].latest_attempt.attempt == 3
            assert len(await scan_stalled(c, limit=2)) == 2
            assert "secret-sentinel" not in json.dumps([r.to_dict() for r in rows])
        finally:
            await c.close()
    live(check())


def test_real_worker_lock_and_all_observation_changes_are_refused(migrated_database):
    async def check():
        worker = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        operator = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        try:
            await _assert_disposable(worker)
            await _assert_disposable(operator)
            obs = await insert_stalled(worker)
            async with PipelineRepository(worker).stage_session(StageMessage(obs.job_id, "DOWNLOAD", 1)):
                assert (await fail_stalled(operator, obs)).reason == "LOCK_HELD"
            for field, value in [("status", "CANCEL_REQUESTED"), ("current_stage", "PREPROCESS"),
                                  ("active_attempt_id", None), ("updated_at", None)]:
                original = await worker.fetchval(f"SELECT {field} FROM jobs WHERE id=$1", obs.job_id)
                if field == "updated_at":
                    await worker.execute("UPDATE jobs SET updated_at=CURRENT_TIMESTAMP WHERE id=$1", obs.job_id)
                else:
                    await worker.execute(f"UPDATE jobs SET {field}=$2 WHERE id=$1", obs.job_id, value)
                assert (await fail_stalled(operator, obs)).reason == "OBSERVATION_CHANGED"
                await worker.execute(f"UPDATE jobs SET {field}=$2 WHERE id=$1", obs.job_id, original)
            assert await worker.fetchval("SELECT status FROM stage_attempts WHERE id=$1", obs.active_attempt_id) == "RUNNING"
            assert await worker.fetchval("SELECT published_at IS NULL FROM pipeline_outbox WHERE job_id=$1", obs.job_id)
        finally:
            await worker.close()
            await operator.close()
    live(check())


@pytest.mark.parametrize("status,terminal,code", [("RUNNING", "FAILED", "WORKER_STALLED"),
                                                  ("CANCEL_REQUESTED", "CANCELED", "CANCELED")])
def test_real_recovery_atomic_history_outbox_final_skip_and_redis(migrated_database, status, terminal, code):
    url = os.getenv("MUSICSHEET_TEST_REDIS_URL")
    if not url:
        pytest.skip("MUSICSHEET_TEST_REDIS_URL is unset")
    async def check():
        c = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        redis = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        key = None
        try:
            await _assert_disposable(c)
            obs = await insert_stalled(c, status)
            key = f"job:{obs.job_id}:events"
            running, history, artifact = str(uuid4()), str(uuid4()), str(uuid4())
            await c.execute("INSERT INTO stage_attempts(id,job_id,stage,attempt,status) VALUES($1,$2,'PREPROCESS',1,'RUNNING')", running, obs.job_id)
            await c.execute("INSERT INTO stage_attempts(id,job_id,stage,attempt,status,output_artifact_ids) "
                            "VALUES($1,$2,'DOWNLOAD',2,'COMPLETED',$3::jsonb)", history, obs.job_id, json.dumps([artifact]))
            await c.execute("INSERT INTO artifacts(id,job_id,role,filename,uri,mime_type,size_bytes,sha256) "
                            "VALUES($1,$2,'SOURCE_ORIGINAL','source.wav','file:///secret-sentinel','audio/wav',3,$3)", artifact, obs.job_id, "a"*64)
            before_history = dict(await c.fetchrow("SELECT * FROM stage_attempts WHERE id=$1", history))
            before_artifact = dict(await c.fetchrow("SELECT * FROM artifacts WHERE id=$1", artifact))
            await enqueue_stage(c, StageMessage(obs.job_id, "PREPROCESS", 1), delay_seconds=10)
            result = await fail_stalled(c, obs, event_store=RedisEventStore(redis))
            assert result.changed and result.transition.job.status.value == terminal
            job = await c.fetchrow("SELECT * FROM jobs WHERE id=$1", obs.job_id)
            assert job["active_attempt_id"] is None and job["error_code"] == code and job["completed_at"] is not None
            attempts = await c.fetch("SELECT * FROM stage_attempts WHERE id=ANY($1::varchar[])", [running, obs.active_attempt_id])
            assert len(attempts) == 2 and all(a["status"] == "FAILED" and a["error_code"] == code and a["error_detail"] is None
                and a["completed_at"] is not None and a["duration_ms"] >= 0 for a in attempts)
            assert dict(await c.fetchrow("SELECT * FROM stage_attempts WHERE id=$1", history)) == before_history
            assert dict(await c.fetchrow("SELECT * FROM artifacts WHERE id=$1", artifact)) == before_artifact
            assert await c.fetchval("SELECT count(*) FROM pipeline_outbox WHERE job_id=$1 AND published_at IS NULL", obs.job_id) == 0
            async with PipelineRepository(c).stage_session(StageMessage(obs.job_id, "DOWNLOAD", 1)) as session:
                assert (await session.prepare(IDENTITY)).action == "SKIP"
            raw = await redis.xrange(key)
            assert len(raw) == 1 and set(raw[0][1]) == {b"payload"}
            assert json.loads(raw[0][1][b"payload"])["status"] == terminal
            assert not (await fail_stalled(c, obs, event_store=RedisEventStore(redis))).changed
            assert len(await redis.xrange(key)) == 1
        finally:
            if key:
                await redis.delete(key)
            await redis.aclose()
            await c.close()
    live(check())


@pytest.mark.parametrize("fault", ["last_write", "commit"])
def test_real_sql_and_deferred_commit_failures_rollback_all_tables(migrated_database, fault):
    async def check():
        c = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        try:
            await _assert_disposable(c)
            obs = await insert_stalled(c)
            async def snapshot():
                tables = []
                for table in ("jobs", "stage_attempts", "pipeline_outbox", "artifacts"):
                    tables.append([dict(r) for r in await c.fetch("SELECT * FROM "+table+" ORDER BY id")])
                return tuple(tables)
            before = await snapshot()
            await c.execute("CREATE FUNCTION operator_fault() RETURNS trigger LANGUAGE plpgsql AS $$ "
                            "BEGIN RAISE EXCEPTION 'secret-sentinel'; END $$")
            if fault == "last_write":
                await c.execute("CREATE TRIGGER operator_fault BEFORE UPDATE ON pipeline_outbox FOR EACH ROW EXECUTE FUNCTION operator_fault()")
            else:
                await c.execute("CREATE CONSTRAINT TRIGGER operator_fault AFTER UPDATE ON jobs DEFERRABLE INITIALLY DEFERRED "
                                "FOR EACH ROW EXECUTE FUNCTION operator_fault()")
            with pytest.raises(InfrastructureUnavailable):
                await fail_stalled(c, obs)
            assert await snapshot() == before
            lock = int.from_bytes(UUID(obs.job_id).bytes[:8], "big", signed=True)
            assert await c.fetchval("SELECT pg_try_advisory_lock($1)", lock)
            assert await c.fetchval("SELECT pg_advisory_unlock($1)", lock)
        finally:
            await c.close()
    live(check())


def test_real_outer_transaction_refused_without_event_or_state_change(migrated_database):
    async def check():
        c = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        observer = await asyncpg.connect(migrated_database, timeout=2, command_timeout=5)
        try:
            await _assert_disposable(c)
            await _assert_disposable(observer)
            obs = await insert_stalled(c)
            calls = []
            class Store:
                async def publish(self, event):
                    calls.append(event)
            tx = c.transaction()
            await tx.start()
            try:
                with pytest.raises(ValueError, match="idle connection"):
                    await fail_stalled(c, obs, event_store=Store())
                assert not calls
                assert await observer.fetchval("SELECT status FROM jobs WHERE id=$1", obs.job_id) == "RUNNING"
                lock = int.from_bytes(UUID(obs.job_id).bytes[:8], "big", signed=True)
                assert await observer.fetchval("SELECT pg_try_advisory_lock($1)", lock)
                assert await observer.fetchval("SELECT pg_advisory_unlock($1)", lock)
            finally:
                await tx.rollback()
            assert await observer.fetchval("SELECT status FROM jobs WHERE id=$1", obs.job_id) == "RUNNING"
        finally:
            await c.close()
            await observer.close()
    live(check())
