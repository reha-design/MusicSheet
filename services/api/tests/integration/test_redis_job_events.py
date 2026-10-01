"""Opt-in tests against an explicitly configured Redis instance."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from musicsheet_common import JobProgressEvent, JobStatus, PipelineStage

from musicsheet_api.jobs.events import JobEventStore


pytestmark = pytest.mark.redis_integration


def _redis_url() -> str:
    url = os.environ.get("MUSICSHEET_TEST_REDIS_URL")
    if not url:
        pytest.skip("set MUSICSHEET_TEST_REDIS_URL to run Redis integration tests")
    return url


def _event(job_id: str, message: str) -> JobProgressEvent:
    return JobProgressEvent(
        job_id=job_id,
        status=JobStatus.RUNNING,
        stage=PipelineStage.SEPARATE,
        stage_progress=40,
        overall_progress=20,
        message=message,
        timestamp=datetime.now(timezone.utc),
    )


def test_real_redis_persists_and_replays_events_after_cursor() -> None:
    url = _redis_url()
    from redis.asyncio import Redis

    job_id = f"redis-test-{uuid4().hex}"
    key = f"job:{job_id}:events"

    async def verify() -> None:
        redis = Redis.from_url(url)
        store = JobEventStore(redis)
        try:
            first_id = await store.publish(_event(job_id, "first"))
            second_id = await store.publish(_event(job_id, "second"))

            replay = await store.read_after(job_id, first_id, block_ms=1)
            assert [(entry.stream_id, entry.event.message) for entry in replay] == [
                (second_id, "second")
            ]

            async def publish_live_event() -> str:
                await asyncio.sleep(0.05)
                return await store.publish(_event(job_id, "live"))

            publisher = asyncio.create_task(publish_live_event())
            live = await store.read_after(job_id, second_id, block_ms=1_000)
            live_id = await publisher
            assert [(entry.stream_id, entry.event.message) for entry in live] == [
                (live_id, "live")
            ]
        finally:
            try:
                await redis.delete(key)
            finally:
                await redis.aclose()

    asyncio.run(verify())


def test_real_redis_stream_retains_approximately_last_100_events() -> None:
    url = _redis_url()
    from redis.asyncio import Redis

    job_id = f"redis-test-{uuid4().hex}"
    key = f"job:{job_id}:events"

    async def verify() -> None:
        redis = Redis.from_url(url)
        store = JobEventStore(redis)
        try:
            ids: list[str] = []
            for index in range(300):
                ids.append(await store.publish(_event(job_id, f"event-{index}")))

            retained_length = await redis.xlen(key)
            assert 100 <= retained_length <= 200

            first_retained = await redis.xrange(key, min="-", max="+", count=1)
            assert first_retained
            first_retained_id = first_retained[0][0]
            if isinstance(first_retained_id, bytes):
                first_retained_id = first_retained_id.decode("utf-8")
            assert first_retained_id != ids[0]

            replay_from_trimmed_cursor = await store.read_after(
                job_id,
                ids[0],
                block_ms=1,
            )
            assert replay_from_trimmed_cursor
            assert replay_from_trimmed_cursor[0].stream_id == first_retained_id

            newest = await store.read_after(job_id, ids[-2], block_ms=1)
            assert [(entry.stream_id, entry.event.message) for entry in newest] == [
                (ids[-1], "event-299")
            ]
        finally:
            try:
                await redis.delete(key)
            finally:
                await redis.aclose()

    asyncio.run(verify())
