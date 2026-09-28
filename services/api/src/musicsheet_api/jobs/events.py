"""Redis Streams storage for typed job progress events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from musicsheet_common import JobProgressEvent

if TYPE_CHECKING:
    import redis.asyncio
    _RedisClient = redis.asyncio.Redis
else:
    _RedisClient = Any


_logger = logging.getLogger(__name__)
_STREAM_MAXLEN = 100


@dataclass(frozen=True, slots=True)
class StoredJobEvent:
    """One Redis entry, including corrupt entries that still advance a cursor."""

    stream_id: str
    event: JobProgressEvent | None


def _decode_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise TypeError("Redis stream values must be text or bytes")


class JobEventStore:
    """Append and replay job progress events using an injected Redis client."""

    def __init__(self, redis_client: _RedisClient) -> None:
        self._redis = redis_client

    @staticmethod
    def stream_key(job_id: str) -> str:
        return f"job:{job_id}:events"

    async def publish(self, event: JobProgressEvent) -> str:
        """Append the event JSON and return its Redis Stream ID as text."""
        stream_id = await self._redis.xadd(
            self.stream_key(event.job_id),
            {"data": event.model_dump_json()},
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )
        return _decode_text(stream_id)

    async def read_after(
        self,
        job_id: str,
        last_id: str,
        *,
        block_ms: int = 1_000,
    ) -> list[StoredJobEvent]:
        """Read the next bounded batch after ``last_id``."""
        streams = await self._redis.xread(
            streams={self.stream_key(job_id): last_id},
            count=_STREAM_MAXLEN,
            block=block_ms,
        )
        if not streams:
            return []

        stored: list[StoredJobEvent] = []
        for _stream_name, entries in streams:
            for raw_id, fields in entries:
                try:
                    stream_id = _decode_text(raw_id)
                except (TypeError, UnicodeDecodeError):
                    _logger.warning("Ignoring job event with an invalid stream ID")
                    continue

                try:
                    payload = fields.get(b"data", fields.get("data"))
                    if payload is None:
                        raise ValueError("missing event payload")
                    event = JobProgressEvent.model_validate_json(_decode_text(payload))
                except Exception:
                    _logger.warning("Ignoring corrupt job event payload")
                    event = None
                stored.append(StoredJobEvent(stream_id=stream_id, event=event))
        return stored
