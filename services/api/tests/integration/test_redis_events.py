"""Opt-in Redis contracts. Only keys owned by this test run are deleted."""

import asyncio
import os
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from musicsheet_common import JobProgressEvent

from musicsheet_api.app import create_app
from musicsheet_api.config import Settings
from musicsheet_api.events.store import RedisEventStore
from musicsheet_api.jobs.repository import JobRepository

pytestmark = pytest.mark.redis_integration


class SecretURL(str):
    def __repr__(self):
        return "<redacted Redis test URL>"


@pytest.fixture
def redis_url():
    value = os.getenv("MUSICSHEET_TEST_REDIS_URL")
    if not value:
        pytest.skip("MUSICSHEET_TEST_REDIS_URL is unset")
    return SecretURL(value)


def run(coroutine):
    failed = False
    try:
        return asyncio.run(asyncio.wait_for(coroutine, 8))
    except Exception:
        failed = True
    if failed:
        pytest.fail("Redis integration operation failed; check test service and ACL", pytrace=False)


def event(job_id):
    return JobProgressEvent(
        job_id=job_id, status="RUNNING", stage="TRANSCRIBE",
        stage_progress=40, overall_progress=55, message="integration",
    )


@asynccontextmanager
async def session(url):
    job_id = str(uuid4())
    key = f"job:{job_id}:events"
    clients = []
    def client():
        name = f"musicsheet-w02-test-{uuid4()}"
        connection = Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2,
            socket_timeout=5, client_name=name,
        )
        clients.append(connection)
        return connection, name
    publisher, _ = client()
    # No command is issued until all cleanup ownership is established.
    cleanup_failed = False
    original_failure = False
    try:
        await publisher.ping()
        yield job_id, publisher, client
    except BaseException:
        original_failure = True
        raise
    finally:
        try:
            await asyncio.wait_for(publisher.delete(key), 2)
        except Exception:
            cleanup_failed = True
        for connection in clients:
            try:
                await connection.aclose()
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            if original_failure:
                # Fixed text only; preserve the original operation's failure.
                import logging
                logging.getLogger(__name__).warning("Redis test resource cleanup failed")
            else:
                raise RuntimeError("Redis test resource cleanup failed")


async def wait_blocked(publisher, names, tasks):
    deadline = monotonic() + 1
    while (remaining := deadline - monotonic()) > 0:
        connections = await asyncio.wait_for(publisher.client_list(), remaining)
        blocked = {entry["name"] for entry in connections if "b" in entry["flags"] and entry["cmd"] == "xread"}
        if set(names) <= blocked:
            assert all(not task.done() for task in tasks)
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Redis read did not enter a blocked state")


async def readers_receive(url, number):
    async with session(url) as (job_id, publisher, new_client):
        readers = [new_client() for _ in range(number)]
        tasks = [asyncio.create_task(RedisEventStore(client).read(job_id, "0-0", block_ms=2000)) for client, _ in readers]
        try:
            await wait_blocked(publisher, [name for _, name in readers], tasks)
            event_id = await RedisEventStore(publisher).publish(event(job_id))
            batches = await asyncio.wait_for(asyncio.gather(*tasks), 4)
            assert all([entry.id for entry in batch] == [event_id] for batch in batches)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def test_real_redis_publish_and_exclusive_replay(redis_url):
    async def check():
        async with session(redis_url) as (job_id, client, _):
            store = RedisEventStore(client)
            first = await store.publish(event(job_id))
            second = await store.publish(event(job_id))
            assert [x.id for x in await store.initial_read(job_id, "0-0")] == [first, second]
            later = await store.initial_read(job_id, first)
            assert [x.id for x in later] == [second]
            assert later[0].event.job_id == job_id and later[0].event.overall_progress == 55
    run(check())


def test_real_redis_waiting_read_receives_new_event(redis_url):
    run(readers_receive(redis_url, 1))


def test_real_redis_two_readers_receive_same_event(redis_url):
    run(readers_receive(redis_url, 2))


def test_real_redis_trim_replays_retained_entries(redis_url):
    async def check():
        async with session(redis_url) as (job_id, client, _):
            store = RedisEventStore(client)
            ids = [await store.publish(event(job_id)) for _ in range(4)]
            await client.xtrim(f"job:{job_id}:events", maxlen=2, approximate=False)
            assert [x.id for x in await store.initial_read(job_id, ids[0])] == ids[-2:]
    run(check())


def test_real_redis_deleted_last_id_is_valid_cursor(redis_url):
    async def check():
        async with session(redis_url) as (job_id, client, _):
            store = RedisEventStore(client)
            last = await store.publish(event(job_id))
            await client.xdel(f"job:{job_id}:events", last)
            assert await store.initial_read(job_id, last) == []
    run(check())


def test_real_redis_empty_blocking_read_times_out(redis_url):
    async def check():
        async with session(redis_url) as (job_id, client, _):
            start = monotonic()
            assert await RedisEventStore(client).read(job_id, "0-0", block_ms=100) == []
            assert monotonic() - start >= 0.08
    run(check())


def test_sse_replays_events_from_real_redis(redis_url, monkeypatch):
    async def check():
        async with session(redis_url) as (job_id, client, _):
            event_id = await RedisEventStore(client).publish(event(job_id))
            app = create_app(settings=Settings.from_env({}))
            app.state.event_store = RedisEventStore(client)
            app.state.db_pool = object()
            async def get_job(self, requested_id):
                assert requested_id == job_id
                return object()
            monkeypatch.setattr(JobRepository, "get_job", get_job)
            incoming = asyncio.Queue()
            incoming.put_nowait({"type":"http.request", "body":b"", "more_body":False})
            sent = []
            async def receive():
                return await incoming.get()
            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body" and message.get("body"):
                    incoming.put_nowait({"type":"http.disconnect"})
            scope = {
                "type":"http", "asgi":{"version":"3.0", "spec_version":"2.4"},
                "http_version":"1.1", "method":"GET", "scheme":"http", "root_path":"",
                "path":f"/api/v1/jobs/{job_id}/events", "headers":[], "query_string":b"",
                "server":("test",80), "client":("test",1),
            }
            await asyncio.wait_for(app(scope, receive, send), 2)
            assert sent[0]["status"] == 200
            body = b"".join(x.get("body", b"") for x in sent)
            assert f"id: {event_id}\nevent: progress\n".encode() in body
            assert await client.ping()  # request did not close or disable the caller's client
    run(check())
