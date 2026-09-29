"""Repository contract tests using a controlled PostgreSQL boundary."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from uuid import UUID

import pytest

from musicsheet_common import JobStatus, PipelineStage
from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.jobs.repository import JobRepository


class WorkflowTransaction:
    def __init__(self, connection: "WorkflowConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.events.append("begin")

    async def __aexit__(self, *args: object) -> None:
        self.connection.events.append("commit")


class WorkflowConnection:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.events: list[str] = []

    def transaction(self) -> WorkflowTransaction:
        return WorkflowTransaction(self)

    async def fetchrow(self, query: str, *args: object) -> object:
        self.calls.append((query, args))
        return self.responses.pop(0)

    async def fetchval(self, query: str, *args: object) -> object:
        self.calls.append((query, args))
        return self.responses.pop(0)

    async def execute(self, query: str, *args: object) -> str:
        self.calls.append((query, args))
        return "OK"


def workflow_repo(*responses: object) -> tuple[JobRepository, WorkflowConnection]:
    connection = WorkflowConnection(*responses)
    return JobRepository(FakePool(connection)), connection  # type: ignore[arg-type]


def test_start_claim_increments_only_after_job_lock_and_before_publish() -> None:
    repo, connection = workflow_repo(
        {**ROW, "start_job_attempts": 0, "workflow_dispatched_at": None},
        False,
        {**ROW, "status": "RUNNING", "start_job_attempts": 1},
    )
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert result.action == "PUBLISH"
    assert result.attempts == 1
    assert result.job.status is JobStatus.RUNNING
    assert connection.events == ["begin", "commit"]
    assert "FOR UPDATE" in connection.calls[0][0]
    assert "start_job_attempts = start_job_attempts + 1" in connection.calls[-1][0]


def test_start_claim_fourth_attempt_is_last_publish() -> None:
    repo, _ = workflow_repo(
        {**ROW, "status": "RUNNING", "start_job_attempts": 3, "workflow_dispatched_at": None},
        False,
        {**ROW, "status": "RUNNING", "start_job_attempts": 4},
    )
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert (result.action, result.attempts) == ("PUBLISH", 4)


def test_start_claim_fifth_delivery_fails_without_publishing() -> None:
    repo, connection = workflow_repo(
        {**ROW, "status": "RUNNING", "start_job_attempts": 4, "workflow_dispatched_at": None},
        False,
        {**ROW, "status": "FAILED", "error_code": "WORKFLOW_WORKER_LOST"},
    )
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert result.action == "FAILED"
    assert result.job.error_code == "WORKFLOW_WORKER_LOST"
    assert all("start_job_attempts = start_job_attempts + 1" not in q for q, _ in connection.calls)


def test_start_claim_cancellation_wins_over_exhaustion() -> None:
    repo, _ = workflow_repo(
        {**ROW, "status": "CANCEL_REQUESTED", "start_job_attempts": 4, "workflow_dispatched_at": None},
        {**ROW, "status": "CANCELED"},
    )
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert result.action == "CANCELED"
    assert result.job.status is JobStatus.CANCELED


def _assert_open_attempt_canceled_in_transaction(connection: WorkflowConnection) -> None:
    assert connection.events == ["begin", "commit"]
    assert "FOR UPDATE" in connection.calls[0][0]
    assert len(connection.calls) == 3
    attempt_query, attempt_args = connection.calls[1]
    job_query, job_args = connection.calls[2]
    assert attempt_query.startswith("UPDATE stage_attempts SET status = 'FAILED'")
    assert "error_code = $2" in attempt_query
    assert "completed_at = CURRENT_TIMESTAMP" in attempt_query
    assert "duration_ms =" in attempt_query
    assert "WHERE job_id = $1 AND status = 'RUNNING'" in attempt_query
    assert attempt_args == (ROW["id"], "CANCELED")
    assert job_query.startswith("UPDATE jobs SET status = 'CANCELED'")
    assert job_args == (ROW["id"],)


def test_start_claim_cancellation_closes_open_attempt_atomically() -> None:
    repo, connection = workflow_repo(
        {**ROW, "status": "CANCEL_REQUESTED", "start_job_attempts": 4,
         "workflow_dispatched_at": None},
        {**ROW, "status": "CANCELED"},
    )
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert result.action == "CANCELED"
    assert result.job.status is JobStatus.CANCELED
    _assert_open_attempt_canceled_in_transaction(connection)


@pytest.mark.parametrize("initial", [None, "published", "stage_started"])
def test_start_claim_missing_published_or_stage_started_is_noop(initial: str | None) -> None:
    if initial is None:
        responses = (None,)
    elif initial == "published":
        responses = ({**ROW, "status": "RUNNING", "start_job_attempts": 1, "workflow_dispatched_at": NOW},)
    else:
        responses = ({**ROW, "status": "RUNNING", "start_job_attempts": 1, "workflow_dispatched_at": None}, True)
    repo, connection = workflow_repo(*responses)
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert result.action == "NOOP"
    assert not any("start_job_attempts = start_job_attempts + 1" in q for q, _ in connection.calls)


def test_workflow_dispatch_marking_requires_claim_and_unpublished_state() -> None:
    repo, connection = workflow_repo({**ROW, "status": "RUNNING"})
    updated = asyncio.run(repo.mark_workflow_dispatched(ROW["id"]))
    assert updated.status is JobStatus.RUNNING
    query, args = connection.calls[0]
    assert "workflow_dispatched_at = CURRENT_TIMESTAMP" in query
    assert "workflow_dispatched_at IS NULL" in query
    assert "start_job_attempts > 0" in query
    assert args == (ROW["id"],)


def test_workflow_publish_failure_does_not_override_cancellation() -> None:
    repo, connection = workflow_repo(
        {**ROW, "status": "CANCEL_REQUESTED", "start_job_attempts": 1, "workflow_dispatched_at": None},
        {**ROW, "status": "CANCELED"},
    )
    result = asyncio.run(repo.fail_workflow_dispatch(ROW["id"]))
    assert result.status is JobStatus.CANCELED
    assert not any("WORKFLOW_DISPATCH_FAILED" in args for _, args in connection.calls)


def test_workflow_publish_failure_cancellation_closes_open_attempt_atomically() -> None:
    repo, connection = workflow_repo(
        {**ROW, "status": "CANCEL_REQUESTED", "start_job_attempts": 1,
         "workflow_dispatched_at": None},
        {**ROW, "status": "CANCELED"},
    )
    result = asyncio.run(repo.fail_workflow_dispatch(ROW["id"]))
    assert result.status is JobStatus.CANCELED
    _assert_open_attempt_canceled_in_transaction(connection)


def test_workflow_publish_failure_does_not_override_recorded_publish() -> None:
    published = {**ROW, "status": "RUNNING", "start_job_attempts": 1,
                 "workflow_dispatched_at": NOW}
    repo, connection = workflow_repo(published)
    result = asyncio.run(repo.fail_workflow_dispatch(ROW["id"]))
    assert result.status is JobStatus.RUNNING
    assert len(connection.calls) == 1


def test_workflow_publish_failure_does_not_override_started_stage() -> None:
    running = {**ROW, "status": "RUNNING", "start_job_attempts": 1,
               "workflow_dispatched_at": None}
    repo, connection = workflow_repo(running, True)
    result = asyncio.run(repo.fail_workflow_dispatch(ROW["id"]))
    assert result.status is JobStatus.RUNNING
    assert len(connection.calls) == 2


def test_api_dispatch_failure_marks_only_pending_job() -> None:
    failed = {**ROW, "status": "FAILED", "error_code": "DISPATCH_FAILED"}
    repo, connection = workflow_repo(failed)
    result = asyncio.run(repo.fail_pending_dispatch(ROW["id"]))
    assert result is not None and result.status is JobStatus.FAILED
    assert result.error_code == "DISPATCH_FAILED"
    query, args = connection.calls[0]
    assert "status = 'PENDING'" in query
    assert "status = 'FAILED'" in query
    assert "error_code = 'DISPATCH_FAILED'" in query
    assert "completed_at = CURRENT_TIMESTAMP" in query
    assert args == (ROW["id"],)
    assert len(connection.calls) == 1


@pytest.mark.parametrize("current_status", [
    "RUNNING", "CANCEL_REQUESTED", "COMPLETED", "FAILED", "CANCELED",
])
def test_api_dispatch_failure_preserves_worker_claim_cancel_and_terminal(current_status: str) -> None:
    current = {**ROW, "status": current_status}
    repo, connection = workflow_repo(None, current)
    result = asyncio.run(repo.fail_pending_dispatch(ROW["id"]))
    assert result is not None and result.status.value == current_status
    assert result.error_code is None
    assert len(connection.calls) == 2
    assert "status = 'PENDING'" in connection.calls[0][0]
    assert connection.calls[1][0].startswith("SELECT")
    assert connection.calls[1][1] == (ROW["id"],)


def test_api_dispatch_failure_missing_job_returns_none() -> None:
    repo, _ = workflow_repo(None, None)
    assert asyncio.run(repo.fail_pending_dispatch(ROW["id"])) is None


def test_start_task_cannot_revive_api_dispatch_failed_job() -> None:
    failed = {**ROW, "status": "FAILED", "error_code": "DISPATCH_FAILED",
              "start_job_attempts": 0, "workflow_dispatched_at": None}
    repo, connection = workflow_repo(failed)
    result = asyncio.run(repo.claim_start_job(ROW["id"]))
    assert result.action == "NOOP"
    assert result.job is not None and result.job.error_code == "DISPATCH_FAILED"
    assert len(connection.calls) == 1
    assert all(not query.startswith("UPDATE") for query, _ in connection.calls)


def test_conditional_transition_checks_stage_and_allowed_source_statuses() -> None:
    repo, connection = workflow_repo({**ROW, "status": "RETRYING"})
    result = asyncio.run(repo.transition_job(
        ROW["id"], expected_stage=PipelineStage.DOWNLOAD,
        from_statuses=(JobStatus.RUNNING,), to_status=JobStatus.RETRYING,
        stage_progress=50, overall_progress=8,
    ))
    assert result.status is JobStatus.RETRYING
    query, args = connection.calls[0]
    assert "current_stage" in query and "status = ANY" in query
    assert "DOWNLOAD" in args and ["RUNNING"] in args


def test_conditional_transition_cannot_revive_committed_cancellation() -> None:
    repo, connection = workflow_repo()
    with pytest.raises(ValueError):
        asyncio.run(repo.transition_job(
            ROW["id"], expected_stage=PipelineStage.DOWNLOAD,
            from_statuses=(JobStatus.CANCEL_REQUESTED,),
            to_status=JobStatus.RUNNING, stage_progress=0, overall_progress=0,
        ))
    assert connection.calls == []


def test_conditional_transition_rejects_unstable_error_code_before_sql() -> None:
    repo, connection = workflow_repo()
    with pytest.raises(ValueError):
        asyncio.run(repo.transition_job(
            ROW["id"], expected_stage=PipelineStage.DOWNLOAD,
            from_statuses=(JobStatus.RUNNING,), to_status=JobStatus.FAILED,
            stage_progress=0, overall_progress=0,
            error_code="secret-host:password",
        ))
    assert connection.calls == []


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)
ROW = {
    "id": "11111111-1111-4111-8111-111111111111",
    "user_id": None,
    "source_type": "YOUTUBE",
    "source_url": "https://example.test/watch?v=1",
    "target_instrument": "piano",
    "status": "PENDING",
    "current_stage": "DOWNLOAD",
    "stage_progress": 0,
    "overall_progress": 0,
    "error_code": None,
    "error_message": None,
    "created_at": NOW,
    "updated_at": NOW,
    "completed_at": None,
}


class FakeConnection:
    def __init__(self, *rows: dict[str, object] | None) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        self.calls.append((query, args))
        return self.rows.pop(0)


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


def repository(*rows: dict[str, object] | None) -> tuple[JobRepository, FakeConnection]:
    connection = FakeConnection(*rows)
    return JobRepository(FakePool(connection)), connection


def test_create_job_uses_schema_defaults() -> None:
    repo, connection = repository(ROW)

    record = asyncio.run(repo.create_job(source_type="YOUTUBE", source_url=ROW["source_url"]))

    assert isinstance(record, JobRecord)
    assert record.status is JobStatus.PENDING
    assert record.current_stage is PipelineStage.DOWNLOAD
    assert record.target_instrument == "piano"
    with pytest.raises(FrozenInstanceError):
        record.source_type = "UPLOAD"
    query, args = connection.calls[0]
    assert query.startswith("INSERT INTO jobs")
    assert "RETURNING" in query
    assert all(f"${i}" in query for i in range(1, 6))
    assert UUID(args[0]).version == 4
    assert args[1:] == (None, "YOUTUBE", ROW["source_url"], "piano")


def test_create_job_preserves_null_target_instrument() -> None:
    repo, connection = repository({**ROW, "target_instrument": None})

    record = asyncio.run(repo.create_job(source_type="UPLOAD", source_url=None, target_instrument=None))

    assert record.target_instrument is None
    assert connection.calls[0][1][-1] is None


def test_create_job_accepts_preallocated_id_and_connection() -> None:
    class NoAcquirePool:
        def acquire(self) -> None:
            raise AssertionError("a supplied transaction connection must be reused")

    job_id = "22222222-2222-4222-8222-222222222222"
    connection = FakeConnection({**ROW, "id": job_id})
    repo = JobRepository(NoAcquirePool())  # type: ignore[arg-type]

    record = asyncio.run(
        repo.create_job(
            source_type="UPLOAD",
            source_url=None,
            job_id=job_id,
            connection=connection,  # type: ignore[arg-type]
        )
    )

    assert record.id == job_id
    query, args = connection.calls[0]
    assert query.startswith("INSERT INTO jobs")
    assert args[0] == job_id
    assert args[2:5] == ("UPLOAD", None, "piano")


def test_create_job_rejects_unknown_source_type() -> None:
    repo, connection = repository()

    with pytest.raises(ValueError):
        asyncio.run(repo.create_job(source_type="OTHER", source_url=None))

    assert connection.calls == []


def test_repository_passes_user_values_as_bound_parameters() -> None:
    attack = "x'); DROP TABLE jobs; --"
    repo, connection = repository({**ROW, "source_url": attack, "user_id": attack, "target_instrument": attack})

    asyncio.run(repo.create_job(source_type="YOUTUBE", source_url=attack, user_id=attack, target_instrument=attack))

    query, args = connection.calls[0]
    assert attack not in query
    assert args[1:] == (attack, "YOUTUBE", attack, attack)


def test_get_job_returns_record_or_none() -> None:
    repo, connection = repository(ROW, None)

    found = asyncio.run(repo.get_job(ROW["id"]))
    missing = asyncio.run(repo.get_job("missing"))

    assert found is not None and found.id == ROW["id"]
    assert missing is None
    assert connection.calls[0][1] == (ROW["id"],)
    assert connection.calls[1][1] == ("missing",)


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "RETRYING"])
def test_request_cancel_updates_eligible_job_atomically(status: str) -> None:
    updated = {
        **ROW,
        "status": "CANCEL_REQUESTED",
        "stage_progress": 35,
        "overall_progress": 60,
        "updated_at": NOW,
    }
    repo, connection = repository(updated)

    record = asyncio.run(repo.request_cancel(ROW["id"]))

    assert record is not None
    assert record.status is JobStatus.CANCEL_REQUESTED
    assert (record.stage_progress, record.overall_progress) == (35, 60)
    query, args = connection.calls[0]
    assert query.startswith("UPDATE jobs SET status = $2")
    assert "status = ANY($3::VARCHAR[])" in query
    assert args == (ROW["id"], "CANCEL_REQUESTED", ["PENDING", "RUNNING", "RETRYING"])


def test_request_cancel_is_idempotent() -> None:
    current = {**ROW, "status": "CANCEL_REQUESTED"}
    repo, connection = repository(None, current)

    record = asyncio.run(repo.request_cancel(ROW["id"]))

    assert record is not None and record.status is JobStatus.CANCEL_REQUESTED
    assert len(connection.calls) == 2
    assert connection.calls[1][0].startswith("SELECT")


def test_request_cancel_returns_terminal_job_without_overwriting() -> None:
    terminal = {**ROW, "status": "COMPLETED"}
    repo, connection = repository(None, terminal)

    record = asyncio.run(repo.request_cancel(ROW["id"]))

    assert record is not None and record.status is JobStatus.COMPLETED
    query, _ = connection.calls[0]
    assert "status = ANY($3::VARCHAR[])" in query
    assert len(connection.calls) == 2


def test_request_cancel_returns_none_for_unknown_job() -> None:
    repo, connection = repository(None, None)

    assert asyncio.run(repo.request_cancel("missing")) is None
    assert len(connection.calls) == 2


def test_concurrent_cancel_does_not_overwrite_terminal_state() -> None:
    class TerminalRaceConnection(FakeConnection):
        async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
            self.calls.append((query, args))
            if query.startswith("UPDATE jobs"):
                return None
            return {**ROW, "status": "FAILED"}

    connection = TerminalRaceConnection()
    repo = JobRepository(FakePool(connection))

    record = asyncio.run(repo.request_cancel(ROW["id"]))

    assert record is not None and record.status is JobStatus.FAILED
    update, args = connection.calls[0]
    assert "status = ANY($3::VARCHAR[])" in update
    assert args[0] == ROW["id"]
    assert args[2] == ["PENDING", "RUNNING", "RETRYING"]


@pytest.mark.parametrize("status,terminal", [(JobStatus.RUNNING, False), (JobStatus.COMPLETED, True), (JobStatus.FAILED, True), (JobStatus.CANCELED, True)])
def test_update_progress_updates_timestamps_and_terminal_time(status: JobStatus, terminal: bool) -> None:
    updated = {**ROW, "status": status.value, "current_stage": "RENDER", "stage_progress": 45, "overall_progress": 70, "updated_at": NOW, "completed_at": NOW if terminal else None}
    repo, connection = repository(updated)

    record = asyncio.run(repo.update_progress(job_id=ROW["id"], status=status, current_stage=PipelineStage.RENDER, stage_progress=45, overall_progress=70))

    assert record is not None
    assert record.status is status
    assert record.completed_at == (NOW if terminal else None)
    query, args = connection.calls[0]
    assert "updated_at = CURRENT_TIMESTAMP" in query
    assert "completed_at = CASE" in query
    assert args == (ROW["id"], status.value, "RENDER", 45, 70, None, None)


@pytest.mark.parametrize("value", [-1, 101, True, False, 1.5, "50"])
@pytest.mark.parametrize("field", ["stage_progress", "overall_progress"])
def test_update_progress_rejects_out_of_range_and_boolean_values(field: str, value: object) -> None:
    repo, connection = repository()
    kwargs = {"job_id": ROW["id"], "status": JobStatus.RUNNING, "current_stage": PipelineStage.DOWNLOAD, "stage_progress": 0, "overall_progress": 100}
    kwargs[field] = value

    with pytest.raises(ValueError):
        asyncio.run(repo.update_progress(**kwargs))

    assert connection.calls == []


def test_update_progress_returns_none_for_missing_job() -> None:
    repo, connection = repository(None)

    result = asyncio.run(repo.update_progress(job_id="missing", status=JobStatus.RUNNING, current_stage=PipelineStage.DOWNLOAD, stage_progress=0, overall_progress=100))

    assert result is None
    assert connection.calls[0][1][0] == "missing"


def test_records_map_status_and_stage_enums() -> None:
    repo, _ = repository({**ROW, "status": "RETRYING", "current_stage": "TRANSCRIBE", "stage_progress": None, "overall_progress": None})

    record = asyncio.run(repo.get_job(ROW["id"]))

    assert record is not None
    assert record.status is JobStatus.RETRYING
    assert record.current_stage is PipelineStage.TRANSCRIBE
    assert record.stage_progress is None
    assert record.overall_progress is None


@pytest.mark.parametrize("field,value", [("status", "SURPRISE"), ("current_stage", "SURPRISE")])
def test_repository_rejects_unknown_database_enum_values(field: str, value: str) -> None:
    repo, _ = repository({**ROW, field: value})

    with pytest.raises(ValueError):
        asyncio.run(repo.get_job(ROW["id"]))


def test_database_failure_propagates() -> None:
    class BrokenConnection(FakeConnection):
        async def fetchrow(self, query: str, *args: object) -> None:
            raise RuntimeError("database unavailable")

    repo = JobRepository(FakePool(BrokenConnection()))

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(repo.get_job(ROW["id"]))
