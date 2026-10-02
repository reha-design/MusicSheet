"""Finite ASGI exchanges verify streaming without buffering an infinite response."""

import asyncio
import json

import pytest
from musicsheet_common import JobProgressEvent

from musicsheet_api.app import create_app
from musicsheet_api.config import Settings
from musicsheet_api.events.store import EventStoreUnavailable, InvalidEventCursor, StreamEvent
from musicsheet_api.events.streaming import SSEStreamingResponse, encode_progress, stream_events
from musicsheet_api.jobs.repository import JobRepository

JOB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SECRET = "secret-token-example"


def item(event_id="10-0", status="RUNNING"):
    return StreamEvent(event_id, JobProgressEvent.model_validate({
        "job_id": JOB, "status": status, "stage": "TRANSCRIBE",
        "stage_progress": 40, "overall_progress": 55, "message": "one\ntwo\rthree",
        "timestamp": "2026-10-02T00:00:00Z",
    }))


class StoreDouble:
    def __init__(self, initial=(), later=(), *, initial_error=None, later_error=None):
        self.initial = list(initial)
        self.later = list(later)
        self.initial_error, self.later_error = initial_error, later_error
        self.cursors = []
        self.initial_calls = []
        self.pending = asyncio.Event()
        self.canceled = asyncio.Event()
        self.close_calls = 0

    async def initial_read(self, job_id, cursor):
        self.initial_calls.append((job_id, cursor))
        if self.initial_error:
            raise self.initial_error
        return [x for x in self.initial if tuple(map(int, x.id.split('-'))) > tuple(map(int, cursor.split('-')))]

    async def read(self, job_id, cursor, **kwargs):
        self.cursors.append(cursor)
        if self.later_error:
            raise self.later_error
        if self.later:
            return self.later.pop(0)
        self.pending.set()
        try:
            await asyncio.Future()
        finally:
            self.canceled.set()


def event_app(monkeypatch, store, *, lookup=True, db=True):
    app = create_app(settings=Settings.from_env({}))
    app.state.db_pool = object() if db else None
    app.state.event_store = store
    app.lookup_ids = []
    async def get_job(self, job_id):
        app.lookup_ids.append(job_id)
        if isinstance(lookup, Exception):
            raise lookup
        return object() if lookup else None
    monkeypatch.setattr(JobRepository, "get_job", get_job)
    return app


async def exchange(app, *, path=None, headers=(), frames=1, spec="2.4", disconnect_when=None):
    incoming = asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    sent = []
    count = 0
    async def receive():
        return await incoming.get()
    async def send(message):
        nonlocal count
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            count += 1
            if count >= frames and disconnect_when is None:
                incoming.put_nowait({"type": "http.disconnect"})
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": spec},
        "http_version": "1.1", "method": "GET", "scheme": "http", "root_path": "",
        "path": path or f"/api/v1/jobs/{JOB}/events", "query_string": b"",
        "headers": list(headers), "server": ("test", 80), "client": ("test", 1),
    }
    task = asyncio.create_task(app(scope, receive, send))
    async def disconnect():
        await disconnect_when.wait()
        incoming.put_nowait({"type": "http.disconnect"})
    stopper = asyncio.create_task(disconnect()) if disconnect_when else None
    try:
        await asyncio.wait_for(task, 2)
    finally:
        for pending in (task, stopper):
            if pending and not pending.done():
                pending.cancel()
        await asyncio.gather(*(x for x in (task, stopper) if x), return_exceptions=True)
    start = next(x for x in sent if x["type"] == "http.response.start")
    body = b"".join(x.get("body", b"") for x in sent if x["type"] == "http.response.body").decode()
    return start, body


def test_initial_subscription_replays_retained_events(monkeypatch):
    store = StoreDouble([item("10-0"), item("20-0")])
    start, body = asyncio.run(exchange(event_app(monkeypatch, store), frames=2))
    assert start["status"] == 200
    assert body.count("event: progress\n") == 2
    assert "id: 10-0\n" in body and "id: 20-0\n" in body
    assert store.initial_calls == [(JOB, "0-0")]


def test_last_event_id_replays_only_later_ids(monkeypatch):
    store = StoreDouble([item("10-0"), item("20-0")])
    _, body = asyncio.run(exchange(event_app(monkeypatch, store), headers=[(b"last-event-id", b"10-0")]))
    assert "id: 10-0\n" not in body and "id: 20-0\n" in body


def test_event_written_during_replay_is_delivered_next(monkeypatch):
    store = StoreDouble([item()], [[item("20-0")]])
    _, body = asyncio.run(exchange(event_app(monkeypatch, store), frames=2))
    assert body.index("id: 10-0") < body.index("id: 20-0")
    assert store.cursors[0] == "10-0"


def test_two_subscribers_receive_same_history(monkeypatch):
    store = StoreDouble([item()])
    app = event_app(monkeypatch, store)
    async def check():
        results = await asyncio.gather(exchange(app), exchange(app))
        assert all("id: 10-0\n" in body for _, body in results)
    asyncio.run(check())


def test_empty_read_emits_heartbeat(monkeypatch):
    store = StoreDouble(later=[[]])
    _, body = asyncio.run(exchange(event_app(monkeypatch, store)))
    assert body == ": heartbeat\n\n"
    assert store.cursors[0] == "0-0"


def test_terminal_event_keeps_subscription_open(monkeypatch):
    store = StoreDouble([item(status="COMPLETED")])
    _, body = asyncio.run(exchange(event_app(monkeypatch, store), disconnect_when=store.pending))
    assert '"status":"COMPLETED"' in body
    assert store.pending.is_set() and store.canceled.is_set()


def test_sse_frames_escape_message_newlines_and_have_headers(monkeypatch):
    start, body = asyncio.run(exchange(event_app(monkeypatch, StoreDouble([item()]))))
    headers = dict(start["headers"])
    assert headers[b"content-type"].startswith(b"text/event-stream")
    assert headers[b"cache-control"] == b"no-cache"
    assert headers[b"x-accel-buffering"] == b"no"
    assert body.startswith("id: 10-0\nevent: progress\ndata: ") and body.endswith("\n\n")
    assert len(body.splitlines()) == 4
    data = json.loads(body.splitlines()[2][6:])
    assert data["message"] == "one\ntwo\rthree"
    assert encode_progress(item()) == body


def test_uuid_is_normalized(monkeypatch):
    store = StoreDouble([item()])
    app = event_app(monkeypatch, store)
    start, _ = asyncio.run(exchange(app, path=f"/api/v1/jobs/{JOB.upper()}/events"))
    assert start["status"] == 200
    assert app.lookup_ids == [JOB] and store.initial_calls == [(JOB, "0-0")]


@pytest.mark.parametrize("header", [b"", b"$", b"1-0\n", b"-1-0", b"18446744073709551616-0"])
def test_invalid_id_or_header_returns_422(monkeypatch, header):
    app = event_app(monkeypatch, StoreDouble())
    start, _ = asyncio.run(exchange(app, headers=[(b"last-event-id", header)]))
    assert start["status"] == 422
    assert app.lookup_ids == []


def test_invalid_uuid_and_duplicate_header_return_422(monkeypatch):
    app = event_app(monkeypatch, StoreDouble())
    for arguments in ({"path": "/api/v1/jobs/not-a-uuid/events"}, {"headers": [(b"last-event-id", b"1-0"), (b"last-event-id", b"2-0")]}):
        start, _ = asyncio.run(exchange(app, **arguments))
        assert start["status"] == 422
    assert app.lookup_ids == []


def test_future_cursor_returns_422(monkeypatch):
    app = event_app(monkeypatch, StoreDouble(initial_error=InvalidEventCursor("Invalid event cursor")))
    start, _ = asyncio.run(exchange(app, headers=[(b"last-event-id", b"100-0")]))
    assert start["status"] == 422


@pytest.mark.parametrize("lookup,db,store,want", [
    (False, True, StoreDouble(), 404),
    (True, False, StoreDouble(), 503),
    (RuntimeError(SECRET), True, StoreDouble(), 503),
    (True, True, None, 503),
])
def test_unknown_job_and_unavailable_dependencies(monkeypatch, lookup, db, store, want):
    start, body = asyncio.run(exchange(event_app(monkeypatch, store, lookup=lookup, db=db)))
    assert start["status"] == want
    assert SECRET not in body


def test_initial_read_failure_returns_503_without_secrets(monkeypatch, caplog):
    app = event_app(monkeypatch, StoreDouble(initial_error=EventStoreUnavailable(SECRET)))
    start, body = asyncio.run(exchange(app))
    assert start["status"] == 503
    assert SECRET not in body + caplog.text


def test_later_failure_emits_one_sanitized_error_without_id(monkeypatch, caplog):
    store = StoreDouble([item()], later_error=EventStoreUnavailable(SECRET))
    start, body = asyncio.run(exchange(event_app(monkeypatch, store), frames=3))
    assert start["status"] == 200
    assert body.count("event: stream_error") == 1
    error = body.split("event: stream_error", 1)[1]
    assert 'data: {"detail":"Event stream is unavailable"}\n\n' in error
    assert "id:" not in error and SECRET not in body + caplog.text


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_disconnect_cancels_pending_read_without_closing_shared_client(monkeypatch, spec):
    store = StoreDouble([item()])
    _, body = asyncio.run(exchange(event_app(monkeypatch, store), spec=spec, disconnect_when=store.pending))
    assert "event: stream_error" not in body
    assert store.canceled.is_set() and store.close_calls == 0


def test_response_cancellation_propagates():
    async def check():
        store = StoreDouble()
        response = SSEStreamingResponse(stream_events(store, JOB, "0-0", []))
        async def receive():
            await asyncio.Future()
        async def send(message):
            pass
        task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
        await asyncio.wait_for(store.pending.wait(), 0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.canceled.is_set()
    asyncio.run(check())


def test_send_failure_closes_stream_and_disconnect_listener():
    async def check():
        canceled = asyncio.Event()
        store = StoreDouble([item()])
        response = SSEStreamingResponse(stream_events(store, JOB, "0-0", [item()]))
        async def receive():
            try:
                await asyncio.Future()
            finally:
                canceled.set()
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("closed connection")
        with pytest.raises(OSError):
            await asyncio.wait_for(response({"type":"http", "asgi":{"spec_version":"2.4"}}, receive, send), 0.2)
        assert canceled.is_set()
        assert response.body_iterator.ag_frame is None
    asyncio.run(check())
