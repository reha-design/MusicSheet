"""SSE framing and disconnect-aware streaming over an event store."""

import asyncio
from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from musicsheet_api.events.store import EventStore, StreamEvent, parse_event_id


def encode_progress(item: StreamEvent) -> str:
    parse_event_id(item.id)
    return f"id: {item.id}\nevent: progress\ndata: {item.event.model_dump_json()}\n\n"


async def stream_events(
    store: EventStore, job_id: str, cursor: str, initial: list[StreamEvent],
) -> AsyncIterator[str]:
    batch = initial
    try:
        while True:
            for item in batch:
                yield encode_progress(item)
                cursor = item.id
            batch = await store.read(job_id, cursor)
            if not batch:
                yield ": heartbeat\n\n"
    except Exception:
        yield 'event: stream_error\ndata: {"detail":"Event stream is unavailable"}\n\n'


class SSEStreamingResponse(StreamingResponse):
    """Always listen for disconnects, including while ASGI 2.4 waits in XREAD."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        tasks = [
            asyncio.create_task(self.stream_response(send)),
            asyncio.create_task(self.listen_for_disconnect(receive)),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                await close()
        if self.background is not None:
            await self.background()
