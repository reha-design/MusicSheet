"""Redis boundary contracts; real event models and serialization are exercised."""

import asyncio
import json
import traceback
import warnings
from uuid import UUID

import pytest
from redis.exceptions import ResponseError
from musicsheet_common import JobProgressEvent

from musicsheet_pipeline import events as store_module
from musicsheet_api.events.store import (
    EventStoreUnavailable,
    InvalidEventCursor,
    RedisEventStore,
    normalize_job_id,
    parse_event_id,
)

JOB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SECRET = "secret-token-example"


def progress(**changes):
    return JobProgressEvent.model_validate({
        "job_id": JOB, "status": "RUNNING", "stage": "TRANSCRIBE",
        "stage_progress": 40, "overall_progress": 55, "message": "전사 중\n진행",
        "timestamp": "2026-10-02T00:00:00Z", **changes,
    })


class RedisDouble:
    def __init__(self, entries=(), *, latest="20-0", error=None, binary=False):
        self.entries = entries
        self.latest = latest
        self.error = error
        self.binary = binary
        self.writes = []
        self.reads = []

    async def xadd(self, key, fields, **options):
        if self.error:
            raise self.error
        self.writes.append((key, fields, options))
        return b"20-0" if self.binary else "20-0"

    async def xinfo_stream(self, key):
        if self.error:
            raise self.error
        if self.latest is None:
            raise ResponseError("no such key")
        return {b"last-generated-id": self.latest.encode()} if self.binary else {
            "last-generated-id": self.latest,
        }

    async def xread(self, streams, **options):
        self.reads.append((streams, options))
        if self.error:
            raise self.error
        if not self.entries:
            return []
        key = next(iter(streams))
        entries = self.entries
        if self.binary:
            key = key.encode()
            entries = [(i.encode(), {b"payload": p.encode()}) for i, p in entries]
        else:
            entries = [(i, {"payload": p}) for i, p in entries]
        return [(key, entries)]


def test_publish_serializes_validated_event_and_scopes_key():
    client = RedisDouble(binary=True)
    result = asyncio.run(RedisEventStore(client).publish(progress(job_id=JOB.upper())))
    assert result == "20-0"
    key, fields, options = client.writes[0]
    assert key == f"job:{JOB}:events"
    assert options == {"maxlen": 100, "approximate": True}
    data = json.loads(fields["payload"])
    assert data["job_id"] == JOB
    assert data["status"] == "RUNNING"
    assert data["message"] == "전사 중\n진행"
    assert "\n" not in fields["payload"]


@pytest.mark.parametrize("field,value", [
    ("status", SECRET), ("stage_progress", 101), ("job_id", SECRET),
])
def test_publish_revalidates_mutated_model(field, value, caplog):
    event = progress()
    setattr(event, field, value)
    client = RedisDouble()
    with warnings.catch_warnings(record=True) as captured:
        with pytest.raises(EventStoreUnavailable) as failure:
            asyncio.run(RedisEventStore(client).publish(event))
    assert client.writes == []
    assert not captured
    assert SECRET not in caplog.text + str(failure.value) + repr(failure.value)
    assert SECRET not in "".join(traceback.format_exception(failure.value))


@pytest.mark.parametrize("value,want", [
    ("0-0", (0, 0)), ("0001-02", (1, 2)),
    ("18446744073709551615-18446744073709551615", (2**64-1, 2**64-1)),
])
def test_cursor_bounds_and_ascii_format(value, want):
    assert parse_event_id(value) == want


@pytest.mark.parametrize("value", [
    "", "$", "+", "-1-0", "1", "1-2-3", " 1-0", "1-0\n", "１-０",
    "18446744073709551616-0", "0-18446744073709551616", "0"*40+"-0",
])
def test_invalid_cursor_is_rejected(value):
    with pytest.raises(InvalidEventCursor):
        parse_event_id(value)


def test_job_id_normalization_and_rejection():
    assert normalize_job_id(UUID(JOB)) == JOB
    assert normalize_job_id(JOB.upper()) == JOB
    with pytest.raises(ValueError, match="Invalid job ID"):
        normalize_job_id("../escape")


def test_initial_read_is_exclusive_and_nonblocking():
    client = RedisDouble([("20-0", progress().model_dump_json())])
    result = asyncio.run(RedisEventStore(client).initial_read(JOB, "10-0"))
    assert [x.id for x in result] == ["20-0"]
    assert client.reads == [({f"job:{JOB}:events": "10-0"}, {"count": 100, "block": None})]


def test_future_cursor_uses_last_generated_id():
    client = RedisDouble(latest="9-10")
    with pytest.raises(InvalidEventCursor):
        asyncio.run(RedisEventStore(client).initial_read(JOB, "10-0"))
    assert not client.reads


def test_nonzero_cursor_without_stream_is_rejected():
    with pytest.raises(InvalidEventCursor):
        asyncio.run(RedisEventStore(RedisDouble(latest=None)).initial_read(JOB, "1-0"))


def test_deleted_last_entry_does_not_make_valid_cursor_future():
    assert asyncio.run(RedisEventStore(RedisDouble(latest="20-0")).initial_read(JOB, "20-0")) == []


@pytest.mark.parametrize("binary", [False, True])
def test_read_handles_bytes_and_text(binary):
    client = RedisDouble([("20-0", progress().model_dump_json())], binary=binary)
    result = asyncio.run(RedisEventStore(client).read(JOB, "0-0"))
    assert result[0].event.job_id == JOB
    assert result[0].event.overall_progress == 55
    assert client.reads[0][1] == {"count": 100, "block": 15000}


@pytest.mark.parametrize("payload", [
    SECRET, '{"status":"secret-token-example"}',
    progress(job_id=OTHER).model_dump_json(),
    progress().model_dump_json().replace('"RUNNING"', '"secret-token-example"'),
    progress().model_dump_json().replace('"stage_progress":40', '"stage_progress":101'),
])
def test_read_rejects_wrong_job_and_invalid_payload(payload, caplog):
    client = RedisDouble([("20-0", payload)])
    with pytest.raises(EventStoreUnavailable) as failure:
        asyncio.run(RedisEventStore(client).read(JOB, "0-0"))
    assert SECRET not in caplog.text + str(failure.value) + repr(failure.value)
    assert SECRET not in "".join(traceback.format_exception(failure.value))


@pytest.mark.parametrize("ids", [["$"], ["10-0"], ["20-0", "20-0"], ["30-0", "20-0"]])
def test_read_rejects_invalid_or_nonincreasing_ids(ids):
    client = RedisDouble([(i, progress().model_dump_json()) for i in ids])
    with pytest.raises(EventStoreUnavailable):
        asyncio.run(RedisEventStore(client).read(JOB, "10-0"))


def test_trimmed_cursor_reads_remaining_entries():
    client = RedisDouble([("20-0", progress().model_dump_json())])
    assert [x.id for x in asyncio.run(RedisEventStore(client).initial_read(JOB, "1-0"))] == ["20-0"]


def test_empty_read_is_empty_list():
    assert asyncio.run(RedisEventStore(RedisDouble()).read(JOB, "0-0")) == []


@pytest.mark.parametrize("error", [OSError(SECRET), ResponseError("WRONGTYPE "+SECRET)])
def test_redis_errors_are_sanitized(error):
    client = RedisDouble(error=error)
    async def check():
        for operation in (
            lambda: RedisEventStore(client).publish(progress()),
            lambda: RedisEventStore(client).initial_read(JOB, "1-0"),
            lambda: RedisEventStore(client).read(JOB, "0-0"),
        ):
            with pytest.raises(EventStoreUnavailable) as failure:
                await operation()
            assert SECRET not in "".join(traceback.format_exception(failure.value))
    asyncio.run(check())


def test_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(store_module, "COMMAND_TIMEOUT_SECONDS", 0.01)
    class SlowRedis(RedisDouble):
        async def xread(self, *args, **kwargs):
            await asyncio.sleep(10)
    async def check():
        with pytest.raises(EventStoreUnavailable):
            await asyncio.wait_for(RedisEventStore(SlowRedis()).initial_read(JOB, "0-0"), 0.2)
    asyncio.run(check())


def test_cancellation_propagates():
    async def check():
        started, canceled = asyncio.Event(), asyncio.Event()
        class PendingRedis(RedisDouble):
            async def xread(self, *args, **kwargs):
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    canceled.set()
        task = asyncio.create_task(RedisEventStore(PendingRedis()).read(JOB, "0-0"))
        await asyncio.wait_for(started.wait(), 0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert canceled.is_set()
    asyncio.run(check())
