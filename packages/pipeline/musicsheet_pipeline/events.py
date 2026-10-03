"""Bounded Redis Streams persistence; PostgreSQL remains authoritative."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from musicsheet_common import JobProgressEvent
from redis.asyncio import Redis
from redis.exceptions import ResponseError

COMMAND_TIMEOUT_SECONDS = 2.0
_MAX_U64 = 2**64 - 1
_ID_PATTERN = re.compile(r"[0-9]+-[0-9]+", re.ASCII)
_UNAVAILABLE = "Event stream is unavailable"


class InvalidEventCursor(ValueError):
    """Malformed or future stream cursor."""


class EventStoreUnavailable(Exception):
    """Sanitized dependency or event validation failure."""


def normalize_job_id(value: str | UUID) -> str:
    try:
        if not isinstance(value, (str, UUID)):
            raise ValueError
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid job ID") from None


def parse_event_id(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or len(value) > 41 or not _ID_PATTERN.fullmatch(value):
        raise InvalidEventCursor("Invalid event cursor")
    parts = tuple(int(part) for part in value.split("-"))
    if any(part > _MAX_U64 for part in parts):
        raise InvalidEventCursor("Invalid event cursor")
    return parts


@dataclass(frozen=True)
class StreamEvent:
    id: str
    event: JobProgressEvent


class EventStore(Protocol):
    async def publish(self, event: JobProgressEvent) -> str: ...
    async def initial_read(self, job_id: str, cursor: str) -> list[StreamEvent]: ...
    async def read(
        self, job_id: str, cursor: str, *, block_ms: int = 15000,
    ) -> list[StreamEvent]: ...


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, str):
        return value
    raise ValueError("Invalid Redis response")


class RedisEventStore:
    """Uses a caller-owned client. Reads do not consume events for other readers."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    async def publish(self, event: JobProgressEvent) -> str:
        try:
            validated = JobProgressEvent.model_validate(event.model_dump(warnings=False))
            validated.job_id = normalize_job_id(validated.job_id)
            result = await asyncio.wait_for(
                self.client.xadd(
                    f"job:{validated.job_id}:events",
                    {"payload": validated.model_dump_json()},
                    maxlen=100, approximate=True,
                ),
                COMMAND_TIMEOUT_SECONDS,
            )
            event_id = _text(result)
            parse_event_id(event_id)
            return event_id
        except Exception:
            raise EventStoreUnavailable(_UNAVAILABLE) from None

    async def initial_read(self, job_id: str, cursor: str) -> list[StreamEvent]:
        job_id = normalize_job_id(job_id)
        cursor_value = parse_event_id(cursor)
        if cursor_value != (0, 0):
            try:
                try:
                    info = await asyncio.wait_for(
                        self.client.xinfo_stream(f"job:{job_id}:events"),
                        COMMAND_TIMEOUT_SECONDS,
                    )
                    latest = _text(info.get("last-generated-id", info.get(b"last-generated-id")))
                except ResponseError as error:
                    if str(error).lower() != "no such key":
                        raise
                    latest = "0-0"
                latest_value = parse_event_id(latest)
            except Exception:
                raise EventStoreUnavailable(_UNAVAILABLE) from None
            if cursor_value > latest_value:
                raise InvalidEventCursor("Invalid event cursor")
        return await self._read(job_id, cursor, block_ms=None)

    async def read(
        self, job_id: str, cursor: str, *, block_ms: int = 15000,
    ) -> list[StreamEvent]:
        job_id = normalize_job_id(job_id)
        parse_event_id(cursor)
        if isinstance(block_ms, bool) or not isinstance(block_ms, int) or block_ms <= 0:
            raise ValueError("Block duration must be a positive integer")
        return await self._read(job_id, cursor, block_ms=block_ms)

    async def _read(
        self, job_id: str, cursor: str, *, block_ms: int | None,
    ) -> list[StreamEvent]:
        key = f"job:{job_id}:events"
        timeout = COMMAND_TIMEOUT_SECONDS if block_ms is None else block_ms / 1000 + 5
        try:
            response = await asyncio.wait_for(
                self.client.xread({key: cursor}, count=100, block=block_ms), timeout,
            )
            if not response:
                return []
            if len(response) != 1:
                raise ValueError("Invalid stream response")
            stream_key, entries = response[0]
            if _text(stream_key) != key or len(entries) > 100:
                raise ValueError("Invalid stream response")
            previous = parse_event_id(cursor)
            result = []
            for raw_id, fields in entries:
                event_id = _text(raw_id)
                current = parse_event_id(event_id)
                if current <= previous:
                    raise ValueError("Invalid event order")
                payload = _text(fields.get("payload", fields.get(b"payload")))
                event = JobProgressEvent.model_validate_json(payload)
                if normalize_job_id(event.job_id) != job_id:
                    raise ValueError("Invalid event job")
                event.job_id = job_id
                result.append(StreamEvent(event_id, event))
                previous = current
            return result
        except Exception:
            raise EventStoreUnavailable(_UNAVAILABLE) from None
