"""Redis job-event store contract tests."""

import asyncio
import json
import sys
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, get_type_hints
from unittest.mock import AsyncMock

from musicsheet_common import JobProgressEvent, JobStatus, PipelineStage

from musicsheet_api.jobs.events import JobEventStore


JOB_ID = "11111111-1111-4111-8111-111111111111"
EVENT = JobProgressEvent(
    job_id=JOB_ID,
    status=JobStatus.RUNNING,
    stage=PipelineStage.SEPARATE,
    stage_progress=40,
    overall_progress=20,
    message="Separating audio",
    timestamp=datetime(2026, 9, 28, tzinfo=timezone.utc),
)


def test_publish_appends_typed_json_to_bounded_job_stream() -> None:
    redis = type("FakeRedis", (), {})()
    redis.xadd = AsyncMock(return_value=b"1727481600000-0")
    store = JobEventStore(redis)  # type: ignore[arg-type]

    stream_id = asyncio.run(store.publish(EVENT))

    assert stream_id == "1727481600000-0"
    redis.xadd.assert_awaited_once()
    args, kwargs = redis.xadd.await_args
    assert args[0] == f"job:{JOB_ID}:events"
    assert set(args[1]) == {"data"}
    assert json.loads(args[1]["data"]) == EVENT.model_dump(mode="json")
    assert kwargs == {"maxlen": 100, "approximate": True}


def test_read_after_decodes_bytes_and_text_entries_in_order() -> None:
    redis = type("FakeRedis", (), {})()
    redis.xread = AsyncMock(
        return_value=[
            (
                f"job:{JOB_ID}:events",
                [
                    (b"10-0", {b"data": EVENT.model_dump_json().encode()}),
                    ("11-0", {"data": EVENT.model_dump_json()}),
                ],
            )
        ]
    )
    store = JobEventStore(redis)  # type: ignore[arg-type]

    entries = asyncio.run(store.read_after(JOB_ID, "9-0", block_ms=250))

    assert [entry.stream_id for entry in entries] == ["10-0", "11-0"]
    assert all(entry.event == EVENT for entry in entries)
    redis.xread.assert_awaited_once_with(
        streams={f"job:{JOB_ID}:events": "9-0"},
        count=100,
        block=250,
    )


def test_read_after_normalizes_timeout_none_to_empty_list() -> None:
    redis = type("FakeRedis", (), {})()
    redis.xread = AsyncMock(return_value=None)
    store = JobEventStore(redis)  # type: ignore[arg-type]

    entries = asyncio.run(store.read_after(JOB_ID, "0-0"))

    assert entries == []


def test_read_after_skips_corrupt_payload_and_returns_its_cursor(caplog) -> None:
    redis = type("FakeRedis", (), {})()
    redis.xread = AsyncMock(
        return_value=[
            (
                f"job:{JOB_ID}:events".encode(),
                [(b"12-0", {b"data": b"not-json"})],
            )
        ]
    )
    store = JobEventStore(redis)  # type: ignore[arg-type]

    entries = asyncio.run(store.read_after(JOB_ID, "11-0"))

    assert len(entries) == 1
    assert entries[0].stream_id == "12-0"
    assert entries[0].event is None
    assert "corrupt" in caplog.text.lower()
    assert "not-json" not in caplog.text


def test_publish_propagates_redis_failure() -> None:
    redis = type("FakeRedis", (), {})()
    redis.xadd = AsyncMock(side_effect=ConnectionError("redis secret endpoint"))
    store = JobEventStore(redis)  # type: ignore[arg-type]

    try:
        asyncio.run(store.publish(EVENT))
    except ConnectionError as error:
        assert str(error) == "redis secret endpoint"
    else:
        raise AssertionError("Redis write errors must propagate to the caller")


def test_jobs_package_keeps_lazy_model_reexport() -> None:
    from musicsheet_api.jobs import JobRecord
    from musicsheet_api.jobs.models import JobRecord as ModelsJobRecord

    assert JobRecord is ModelsJobRecord


def test_jobs_package_keeps_lazy_repository_reexport(monkeypatch) -> None:
    import musicsheet_api.jobs as jobs_package

    sentinel = object()
    repository_module = ModuleType("musicsheet_api.jobs.repository")
    repository_module.JobRepository = sentinel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, repository_module.__name__, repository_module)

    assert jobs_package.JobRepository is sentinel


def test_redis_type_annotation_is_safe_to_resolve_without_importing_redis() -> None:
    hints = get_type_hints(JobEventStore.__init__)

    assert hints["redis_client"] is Any
