"""Job-scoped progress SSE with pre-response dependency checks."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from musicsheet_api.events.store import InvalidEventCursor, parse_event_id
from musicsheet_api.events.streaming import SSEStreamingResponse, stream_events
from musicsheet_api.jobs.repository import JobRepository

router = APIRouter(prefix="/api/v1/jobs", tags=["events"])


@router.get("/{job_id}/events", response_class=SSEStreamingResponse)
async def job_events(job_id: UUID, request: Request) -> SSEStreamingResponse:
    values = request.headers.getlist("last-event-id")
    if len(values) > 1:
        raise HTTPException(status_code=422, detail="Invalid event cursor")
    cursor = values[0] if values else "0-0"
    try:
        parse_event_id(cursor)
    except InvalidEventCursor:
        raise HTTPException(status_code=422, detail="Invalid event cursor") from None

    canonical_id = str(job_id)
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Job database is unavailable")
    try:
        job = await JobRepository(pool).get_job(canonical_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Job database is unavailable") from None
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    store = getattr(request.app.state, "event_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Event stream is unavailable")
    try:
        initial = await store.initial_read(canonical_id, cursor)
    except InvalidEventCursor:
        raise HTTPException(status_code=422, detail="Invalid event cursor") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Event stream is unavailable") from None
    return SSEStreamingResponse(
        stream_events(store, canonical_id, cursor, initial),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
