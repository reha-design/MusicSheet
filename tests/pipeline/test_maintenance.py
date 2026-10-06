import asyncio
import copy
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from musicsheet_common import JobStatus
from musicsheet_pipeline.contracts import InfrastructureUnavailable, StageMessage
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.repository import PipelineRepository
from .support import JOB, OTHER, Connection


def api():
    from musicsheet_pipeline import maintenance, models
    return maintenance, models


def stalled(c, status="RUNNING"):
    c.db.jobs[JOB].update(status=status, updated_at=datetime.now(timezone.utc)-timedelta(hours=3),
                          active_attempt_id=OTHER, source_url="https://secret-sentinel")
    c.db.attempts[OTHER] = dict(id=OTHER, job_id=JOB, stage="DOWNLOAD", attempt=1,
        generation=1, status="RUNNING", started_at=datetime.now(timezone.utc)-timedelta(hours=3),
        completed_at=None, error_code=None, error_detail="secret-sentinel", output_artifact_ids=[])
    return observation(c)


def observation(c):
    _, m = api()
    j = c.db.jobs[JOB]
    return m.JobObservation(j["id"], j["status"], j["current_stage"], j["updated_at"], j["active_attempt_id"])


@pytest.mark.parametrize("field,value", [
    ("job_id", "secret-sentinel"), ("active_attempt_id", "secret-sentinel"),
    ("status", "secret-sentinel"), ("current_stage", "secret-sentinel"),
    ("updated_at", datetime(2026, 10, 6)), ("updated_at", "secret-sentinel"),
])
def test_observation_rejects_invalid_values_without_echo(field, value):
    _, m = api()
    args = dict(job_id=JOB, status="RUNNING", current_stage="DOWNLOAD",
                updated_at=datetime.now(timezone.utc), active_attempt_id=None)
    args[field] = value
    with pytest.raises(ValueError) as error:
        m.JobObservation(**args)
    assert "secret-sentinel" not in str(error.value)


@pytest.mark.parametrize("options", [
    {"stale_seconds": True}, {"stale_seconds": 0}, {"stale_seconds": -1},
    {"stale_seconds": 1.0}, {"stale_seconds": 2147483648},
    {"limit": False}, {"limit": 0}, {"limit": 1001}, {"limit": 1.0},
])
def test_scan_rejects_bounds_before_queries(options):
    maintenance, _ = api()
    async def check():
        c = Connection()
        with pytest.raises(ValueError):
            await maintenance.scan_stalled(c, **options)
        assert not c.queries
    asyncio.run(check())


def test_scan_filters_orders_limits_and_returns_safe_latest_summary():
    maintenance, _ = api()
    async def check():
        c = Connection()
        stalled(c)
        original = copy.deepcopy(c.db.jobs[JOB])
        for i, status in enumerate(["PENDING", "RETRYING", "CANCEL_REQUESTED", "COMPLETED", "FAILED", "CANCELED", "RUNNING"]):
            id = str(uuid4())
            c.db.jobs[id] = dict(original, id=id, status=status,
                updated_at=None if i == 6 else original["updated_at"]-timedelta(seconds=i+1))
        newer = str(uuid4())
        c.db.attempts[newer] = dict(c.db.attempts[OTHER], id=newer, attempt=2,
            status="FAILED", error_code="PROVIDER_FAILED", started_at=datetime.now(timezone.utc))
        null_started = str(uuid4())
        c.db.attempts[null_started] = dict(c.db.attempts[newer], id=null_started, attempt=3, started_at=None)
        rows = await maintenance.scan_stalled(c)
        assert [r.observation.status.value for r in rows] == ["CANCEL_REQUESTED", "RETRYING", "PENDING", "RUNNING"]
        assert rows[-1].latest_attempt.attempt == 2
        assert len(await maintenance.scan_stalled(c, limit=2)) == 2
        assert "secret-sentinel" not in json.dumps([r.to_dict() for r in rows])
        c.db.jobs[JOB]["updated_at"] = datetime.now(timezone.utc)
        assert len(await maintenance.scan_stalled(c)) == 3
    asyncio.run(check())


@pytest.mark.parametrize("status,terminal,code", [
    ("RUNNING", "FAILED", "WORKER_STALLED"), ("PENDING", "FAILED", "WORKER_STALLED"),
    ("RETRYING", "FAILED", "WORKER_STALLED"), ("CANCEL_REQUESTED", "CANCELED", "CANCELED"),
])
def test_recovery_closes_running_attempts_consumes_outbox_and_preserves_history(status, terminal, code):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c, status)
        second, completed = str(uuid4()), str(uuid4())
        c.db.attempts[second] = dict(c.db.attempts[OTHER], id=second, stage="PREPROCESS")
        c.db.attempts[completed] = dict(c.db.attempts[OTHER], id=completed, status="COMPLETED", output_artifact_ids=[OTHER])
        history, artifacts = copy.deepcopy(c.db.attempts[completed]), copy.deepcopy(c.db.artifacts)
        await enqueue_stage(c, StageMessage(JOB, "DOWNLOAD", 1))
        await enqueue_stage(c, StageMessage(JOB, "PREPROCESS", 1), delay_seconds=10)
        calls = []
        class Store:
            async def publish(self, event):
                assert not c.in_transaction and c.db.jobs[JOB]["status"] == terminal
                calls.append(event)
        result = await maintenance.fail_stalled(c, obs, event_store=Store())
        assert result.changed and result.reason == "CHANGED" and result.transition.job.status.value == terminal
        assert c.db.jobs[JOB]["active_attempt_id"] is None and c.db.jobs[JOB]["error_code"] == code
        assert c.db.jobs[JOB]["completed_at"] is not None
        for id in (OTHER, second):
            assert c.db.attempts[id]["status"] == "FAILED" and c.db.attempts[id]["error_code"] == code
            assert c.db.attempts[id]["error_detail"] is None and c.db.attempts[id]["completed_at"] is not None
        assert c.db.attempts[completed] == history and c.db.artifacts == artifacts
        assert all(r["published_at"] is not None for r in c.db.outbox.values())
        assert len(calls) == 1 and calls[0].status.value == terminal
        async with PipelineRepository(c).stage_session(StageMessage(JOB, "DOWNLOAD", 1)) as session:
            assert (await session.prepare(None)).action == "SKIP"
        assert not (await maintenance.fail_stalled(c, obs, event_store=Store())).changed
        assert len(calls) == 1 and not c.db.locks and not c.listeners
    asyncio.run(check())


@pytest.mark.parametrize("field,value", [
    ("updated_at", datetime.now(timezone.utc)), ("status", "CANCEL_REQUESTED"),
    ("current_stage", "PREPROCESS"), ("active_attempt_id", None),
])
def test_changed_observation_is_refused_without_writes(field, value):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c)
        c.db.jobs[JOB][field] = value
        before = copy.deepcopy((c.db.jobs, c.db.attempts, c.db.outbox))
        r = await maintenance.fail_stalled(c, obs)
        assert not r.changed and r.reason == "OBSERVATION_CHANGED"
        assert before == (c.db.jobs, c.db.attempts, c.db.outbox)
    asyncio.run(check())


@pytest.mark.parametrize("case,reason", [("missing", "NOT_FOUND"), ("terminal", "NOT_ELIGIBLE"), ("fresh", "NOT_STALE")])
def test_other_noop_reasons(case, reason):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c)
        if case == "missing":
            del c.db.jobs[JOB]
        elif case == "terminal":
            c.db.jobs[JOB]["status"] = "COMPLETED"
        else:
            obs = dataclasses.replace(obs, updated_at=datetime.now(timezone.utc))
            c.db.jobs[JOB]["updated_at"] = obs.updated_at
        before = copy.deepcopy((c.db.jobs, c.db.attempts, c.db.outbox))
        result = await maintenance.fail_stalled(c, obs)
        assert not result.changed and result.reason == reason
        assert before == (c.db.jobs, c.db.attempts, c.db.outbox)
    asyncio.run(check())


def test_worker_lock_refuses_recovery_without_transaction():
    maintenance, _ = api()
    async def check():
        worker = Connection()
        obs = stalled(worker)
        operator = Connection(worker.db)
        async with PipelineRepository(worker).stage_session(StageMessage(JOB, "DOWNLOAD", 1)):
            result = await maintenance.fail_stalled(operator, obs)
            assert not result.changed and result.reason == "LOCK_HELD" and operator.transactions == 0
        assert not worker.db.locks and not operator.listeners
    asyncio.run(check())


@pytest.mark.parametrize("value", [True, 0, 2147483648, 1.0])
def test_recovery_invalid_age_opens_no_lock(value):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c)
        with pytest.raises(ValueError):
            await maintenance.fail_stalled(c, obs, stale_seconds=value)
        assert not c.queries
    asyncio.run(check())


@pytest.mark.parametrize("fault", ["outbox", "commit"])
def test_last_write_and_commit_failure_roll_back_entire_recovery(fault):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c)
        await enqueue_stage(c, StageMessage(JOB, "DOWNLOAD", 1))
        before = copy.deepcopy((c.db.jobs, c.db.attempts, c.db.artifacts, c.db.outbox))
        if fault == "commit":
            c.fail_commit = True
        else:
            execute = c.execute
            async def fail(query, *args):
                if "maintenance.consume" in query:
                    raise OSError("secret-sentinel")
                return await execute(query, *args)
            c.execute = fail
        with pytest.raises(InfrastructureUnavailable):
            await maintenance.fail_stalled(c, obs)
        assert before == (c.db.jobs, c.db.attempts, c.db.artifacts, c.db.outbox)
        assert not c.db.locks and not c.listeners
    asyncio.run(check())


def test_redis_failure_cannot_reverse_committed_recovery(caplog):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c)
        class Store:
            async def publish(self, event):
                raise OSError("secret-sentinel")
        assert (await maintenance.fail_stalled(c, obs, event_store=Store())).changed
        assert c.db.jobs[JOB]["status"] == "FAILED" and "secret-sentinel" not in caplog.text
    asyncio.run(check())


@pytest.mark.parametrize("entry", ["public", "session"])
def test_outer_transaction_is_refused_before_sql_and_events(entry):
    maintenance, _ = api()
    async def check():
        c = Connection()
        obs = stalled(c)
        calls = []
        class Store:
            async def publish(self, event):
                calls.append(event)
        async def recover(session=None):
            before = len(c.queries)
            async with c.transaction():
                with pytest.raises(ValueError, match="idle connection"):
                    if session is None:
                        await maintenance.fail_stalled(c, obs, event_store=Store())
                    else:
                        await session.fail_stalled(obs, stale_seconds=7200)
            assert len(c.queries) == before and not calls
        if entry == "public":
            await recover()
        else:
            async with PipelineRepository(c).stage_session(StageMessage(JOB, "DOWNLOAD", 1)) as session:
                await recover(session)
        assert c.db.jobs[JOB]["status"] == "RUNNING" and not c.db.locks and not c.listeners
    asyncio.run(check())
