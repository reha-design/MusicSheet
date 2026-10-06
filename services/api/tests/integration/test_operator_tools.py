"""Guarded, real PostgreSQL/Redis checks for the shared pipeline execution tools."""
import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest
from redis.asyncio import Redis
from musicsheet_common import JobStatus
from musicsheet_pipeline.contracts import ProviderIdentity, StageMessage
from musicsheet_pipeline.events import RedisEventStore
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.repository import PipelineRepository

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
