"""Stalled-job maintenance and operator-recovery contract tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from importlib import import_module, util
from pathlib import Path
import tomllib

import pytest
from celery.exceptions import Ignore
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.repository import advisory_lock_key


def _maintenance_api():
    assert util.find_spec("musicsheet_api.pipeline.maintenance") is not None, (
        "the stalled-job maintenance module is not implemented"
    )
    module = import_module("musicsheet_api.pipeline.maintenance")
    assert hasattr(module, "JobMaintenance"), "JobMaintenance is not implemented"
    return module


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.transaction_job = (
            dict(self.connection.job) if self.connection.job is not None else None
        )
        self.connection.transaction_attempts = [
            dict(item) for item in self.connection.attempts
        ]
        self.connection.log.append("begin")

    async def __aexit__(self, exc_type, exc, tb):
        self.connection.log.append("rollback" if exc_type else "commit")
        if exc_type:
            self.connection.job = self.connection.transaction_job
            self.connection.attempts = self.connection.transaction_attempts


class MaintenanceConnection:
    def __init__(self, job, attempts=(), *, now=None, held_locks=()):
        self.job = dict(job) if job is not None else None
        self.attempts = [dict(item) for item in attempts]
        self.now = now or datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
        self.held_locks = set(held_locks)
        self.owned_locks = set()
        self.log = []
        self.queries = []
        self.reject_job_update = False

    def transaction(self):
        return Transaction(self)

    async def fetchval(self, query, *args):
        self.queries.append((query, args))
        if "pg_try_advisory_lock" in query:
            key = args[0]
            if key in self.held_locks:
                return False
            self.owned_locks.add(key)
            return True
        if "CURRENT_TIMESTAMP" in query:
            return self.now - timedelta(seconds=args[0])
        raise AssertionError(f"unexpected fetchval query: {query}")

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        cutoff = args[0]
        if self.job is None or self.job["updated_at"] > cutoff:
            return []
        if self.job["status"] in ("COMPLETED", "FAILED", "CANCELED"):
            return []
        latest = max(self.attempts, key=lambda row: row["attempt"], default=None)
        row = {
            "id": self.job["id"],
            "status": self.job["status"],
            "current_stage": self.job["current_stage"],
            "updated_at": self.job["updated_at"],
            "start_job_attempts": self.job.get("start_job_attempts", 0),
            "latest_attempt_stage": latest["stage"] if latest else None,
            "latest_attempt_number": latest["attempt"] if latest else None,
            "latest_attempt_status": latest["status"] if latest else None,
            "latest_attempt_error_code": latest.get("error_code") if latest else None,
        }
        return [row]

    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        if "SELECT current_stage" in query:
            return None if self.job is None else {"current_stage": self.job["current_stage"]}
        if "FOR UPDATE" in query:
            return None if self.job is None else dict(self.job)
        if query.startswith("UPDATE jobs SET status"):
            job_id, status, error_code, error_message, observed_status, observed_at = args
            if self.reject_job_update:
                return None
            if (
                self.job is None
                or self.job["id"] != job_id
                or self.job["status"] != observed_status
                or self.job["updated_at"] != observed_at
            ):
                return None
            self.job.update(
                status=status,
                error_code=error_code,
                error_message=error_message,
                updated_at=self.now,
                completed_at=self.now,
            )
            return dict(self.job)
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def execute(self, query, *args):
        self.queries.append((query, args))
        if "pg_advisory_unlock" in query:
            self.owned_locks.discard(args[0])
            return "SELECT 1"
        if query.startswith("UPDATE stage_attempts"):
            job_id, code = args
            for attempt in self.attempts:
                if attempt["job_id"] == job_id and attempt["status"] == "RUNNING":
                    attempt.update(
                        status="FAILED", error_code=code, error_detail=None,
                        completed_at=self.now, duration_ms=0,
                    )
            self.log.append("close-attempts")
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute query: {query}")


class Events:
    def __init__(self, connection, *, fail=False):
        self.connection = connection
        self.fail = fail
        self.published = []

    async def publish(self, event):
        assert self.connection.log[-1] == "commit"
        self.published.append(event)
        if self.fail:
            raise ConnectionError("sensitive redis endpoint")
        return "1-0"


def _job(*, status="RUNNING", updated_at=None, stage="DOWNLOAD"):
    now = datetime(2026, 9, 29, 8, tzinfo=timezone.utc)
    return {
        "id": "job-123", "user_id": None, "source_type": "UPLOAD",
        "source_url": "https://private.invalid/source", "target_instrument": "piano",
        "status": status, "current_stage": stage, "stage_progress": 35,
        "overall_progress": 5, "error_code": None, "error_message": None,
        "created_at": now, "updated_at": updated_at or now - timedelta(hours=3),
        "completed_at": None, "start_job_attempts": 2,
    }


def _attempt(status="RUNNING"):
    return {
        "id": "attempt-1", "job_id": "job-123", "stage": "DOWNLOAD",
        "attempt": 2, "status": status, "error_code": None,
        "error_detail": "driver secret must never be surfaced",
    }


def test_maintenance_module_and_console_entry_point_exist() -> None:
    module = _maintenance_api()
    api_project = Path(__file__).parents[1] / "pyproject.toml"
    with api_project.open("rb") as source:
        scripts = tomllib.load(source)["project"]["scripts"]
    assert scripts.get("musicsheet-orchestration-maintenance") == (
        "musicsheet_api.pipeline.maintenance:main"
    )
    assert callable(module.main)


def test_scan_uses_twice_visibility_timeout_and_returns_safe_fields() -> None:
    api = _maintenance_api()
    connection = MaintenanceConnection(_job(), [_attempt()])
    service = api.JobMaintenance(connection, events=None, visibility_timeout=3600)

    rows = asyncio.run(service.scan())

    assert len(rows) == 1
    assert rows[0].job_id == "job-123"
    assert rows[0].status is JobStatus.RUNNING
    assert rows[0].current_stage is PipelineStage.DOWNLOAD
    assert rows[0].start_job_attempts == 2
    assert rows[0].latest_attempt.attempt == 2
    assert rows[0].latest_attempt.status == "RUNNING"
    assert "source_url" not in rows[0].to_dict()
    assert "error_detail" not in rows[0].to_dict()
    assert connection.queries[0][1] == (7200,)
    scan_sql = connection.queries[1][0]
    assert "source_url" not in scan_sql
    assert "error_detail" not in scan_sql


@pytest.mark.parametrize("held_scope", ["START_JOB", PipelineStage.DOWNLOAD.value])
def test_recovery_refuses_either_held_advisory_lock(held_scope) -> None:
    api = _maintenance_api()
    job = _job()
    key = advisory_lock_key(job["id"], held_scope)
    connection = MaintenanceConnection(job, held_locks=(key,))
    service = api.JobMaintenance(connection, events=None, visibility_timeout=3600)

    result = asyncio.run(service.fail_stalled(
        job["id"], job["updated_at"], JobStatus.RUNNING,
    ))

    assert result.changed is False
    assert result.reason == "LOCK_HELD"
    assert connection.job["status"] == "RUNNING"
    assert "begin" not in connection.log
    assert not connection.owned_locks


@pytest.mark.parametrize("change", ["timestamp", "status"])
def test_recovery_refuses_changed_observation_and_requests_rescan(change) -> None:
    api = _maintenance_api()
    observed = _job()
    current = dict(observed)
    if change == "timestamp":
        current["updated_at"] += timedelta(minutes=1)
    else:
        current["status"] = "CANCEL_REQUESTED"
    connection = MaintenanceConnection(current)
    service = api.JobMaintenance(connection, events=None, visibility_timeout=3600)

    result = asyncio.run(service.fail_stalled(
        observed["id"], observed["updated_at"], JobStatus.RUNNING,
    ))

    assert result.changed is False
    assert result.reason == "OBSERVATION_CHANGED"
    assert "begin" in connection.log and "commit" in connection.log
    assert connection.job["status"] == current["status"]


def test_recovery_refuses_observed_job_that_is_no_longer_stale() -> None:
    api = _maintenance_api()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    job = _job(updated_at=now - timedelta(hours=1))
    connection = MaintenanceConnection(job, now=now)
    service = api.JobMaintenance(connection, events=None, visibility_timeout=3600)

    result = asyncio.run(service.fail_stalled(
        job["id"], job["updated_at"], JobStatus.RUNNING,
    ))

    assert result.changed is False
    assert result.reason == "NOT_STALE"
    assert connection.job["status"] == "RUNNING"


def test_cancellation_after_scan_requires_rescan_then_wins_and_closes_attempt() -> None:
    api = _maintenance_api()
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    job = _job(updated_at=now - timedelta(hours=3))
    connection = MaintenanceConnection(job, [_attempt()], now=now)
    events = Events(connection)
    service = api.JobMaintenance(connection, events=events, visibility_timeout=3600)
    observed_timestamp = job["updated_at"]

    # Model DELETE racing the operator's first scan: it changes both status and updated_at.
    connection.job.update(status="CANCEL_REQUESTED", updated_at=now)
    refused = asyncio.run(service.fail_stalled(
        job["id"], observed_timestamp, JobStatus.RUNNING,
    ))
    assert refused.changed is False
    assert refused.reason == "OBSERVATION_CHANGED"
    assert connection.job["status"] == "CANCEL_REQUESTED"

    # The operator waits through the stale threshold, rescans, and retries the new row version.
    connection.now = now + timedelta(hours=2, seconds=1)
    rescanned = asyncio.run(service.scan())
    assert len(rescanned) == 1
    assert rescanned[0].status is JobStatus.CANCEL_REQUESTED
    result = asyncio.run(service.fail_stalled(
        job["id"], rescanned[0].updated_at, rescanned[0].status,
    ))

    assert result.changed is True
    assert result.job.status is JobStatus.CANCELED
    assert connection.attempts[0]["status"] == "FAILED"
    assert connection.attempts[0]["error_code"] == "CANCELED"
    last_close = max(i for i, entry in enumerate(connection.log) if entry == "close-attempts")
    last_commit = max(i for i, entry in enumerate(connection.log) if entry == "commit")
    assert last_close < last_commit
    assert events.published[0].status is JobStatus.CANCELED
    assert events.published[0].message == "Job canceled"


def test_failure_recovery_is_atomic_and_event_redis_failure_is_sanitized(caplog) -> None:
    api = _maintenance_api()
    connection = MaintenanceConnection(_job(), [_attempt()])
    events = Events(connection, fail=True)
    service = api.JobMaintenance(connection, events=events, visibility_timeout=3600)

    result = asyncio.run(service.fail_stalled(
        connection.job["id"], connection.job["updated_at"], JobStatus.RUNNING,
    ))

    assert result.changed is True
    assert result.job.status is JobStatus.FAILED
    assert result.job.error_code == "WORKER_PRECLAIM_STALLED"
    assert result.job.error_message == "Workflow could not be recovered"
    assert connection.attempts[0]["status"] == "FAILED"
    assert connection.attempts[0]["error_code"] == "WORKER_LOST"
    assert connection.log.index("close-attempts") < connection.log.index("commit")
    assert events.published[0].status is JobStatus.FAILED
    assert "sensitive redis endpoint" not in caplog.text
    assert not connection.owned_locks


def test_job_compare_and_set_miss_rolls_back_open_attempt_close() -> None:
    api = _maintenance_api()
    connection = MaintenanceConnection(_job(), [_attempt()])
    connection.reject_job_update = True
    service = api.JobMaintenance(connection, events=None, visibility_timeout=3600)

    result = asyncio.run(service.fail_stalled(
        connection.job["id"], connection.job["updated_at"], JobStatus.RUNNING,
    ))

    assert result.changed is False
    assert result.reason == "OBSERVATION_CHANGED"
    assert connection.job["status"] == "RUNNING"
    assert connection.attempts[0]["status"] == "RUNNING"
    assert connection.log[-1] == "rollback"


def test_cli_requires_the_observed_status_for_compare_and_set() -> None:
    api = _maintenance_api()
    parser = api.create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "fail-stalled", "--job-id", "job-123", "--observed-updated-at",
            "2026-09-29T08:00:00+00:00",
        ])
    args = parser.parse_args([
        "fail-stalled", "--job-id", "job-123", "--observed-updated-at",
        "2026-09-29T08:00:00+00:00", "--observed-status", "RUNNING",
    ])
    assert args.observed_status == "RUNNING"


def test_later_stage_delivery_acknowledges_recovered_terminal_job(monkeypatch) -> None:
    import musicsheet_api.pipeline.tasks as tasks

    api = _maintenance_api()
    connection = MaintenanceConnection(_job())
    recovered = asyncio.run(api.JobMaintenance(
        connection, events=None, visibility_timeout=3600,
    ).fail_stalled(
        "job-123", connection.job["updated_at"], JobStatus.RUNNING,
    ))
    assert recovered.changed is True

    class Runtime:
        job = recovered.job
        last_attempt_number = 0

    @asynccontextmanager
    async def fake_runtime():
        yield Runtime()

    async def terminal_noop(job_id, stage, runtime, handlers):
        assert runtime.job.status is JobStatus.FAILED
        return "NOOP"

    monkeypatch.setattr(tasks, "_worker_runtime", fake_runtime)
    monkeypatch.setattr(tasks, "_execute_stage", terminal_noop)

    with pytest.raises(Ignore):
        tasks._run_stage_task(tasks.download_source, "job-123", PipelineStage.DOWNLOAD)
