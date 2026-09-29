"""Stage persistence boundary tests with scripted PostgreSQL responses."""

import asyncio
from datetime import datetime, timezone

import pytest
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.repository import JobRepository, advisory_lock_key
from musicsheet_api.jobs.stages import StageAttemptRepository


NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
JOB = {
    "id": "11111111-1111-4111-8111-111111111111", "user_id": None,
    "source_type": "UPLOAD", "source_url": None, "target_instrument": "piano",
    "status": "RUNNING", "current_stage": "DOWNLOAD", "stage_progress": 0,
    "overall_progress": 0, "error_code": None, "error_message": None,
    "created_at": NOW, "updated_at": NOW, "completed_at": None,
}
ATTEMPT = {
    "id": "22222222-2222-4222-8222-222222222222", "job_id": JOB["id"],
    "stage": "DOWNLOAD", "attempt": 1, "status": "RUNNING",
    "provider": None, "model_version": None, "started_at": NOW,
    "completed_at": None, "duration_ms": None, "error_code": None,
    "error_detail": None,
}


class Transaction:
    def __init__(self, connection: "Connection") -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.events.append("begin")

    async def __aexit__(self, exc_type: object, *args: object) -> None:
        self.connection.events.append("rollback" if exc_type else "commit")


class Connection:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.events: list[str] = []

    def transaction(self) -> Transaction:
        return Transaction(self)

    async def fetchrow(self, query: str, *args: object) -> object:
        self.calls.append((query, args))
        return self.responses.pop(0)

    async def execute(self, query: str, *args: object) -> str:
        self.calls.append((query, args))
        return "OK"


class Acquire:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> Connection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class Pool:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def acquire(self) -> Acquire:
        return Acquire(self.connection)


def repo(*responses: object) -> tuple[StageAttemptRepository, Connection]:
    connection = Connection(*responses)
    return StageAttemptRepository(Pool(connection)), connection  # type: ignore[arg-type]


def test_begin_allocates_first_attempt_and_claims_running_in_one_transaction() -> None:
    stages, connection = repo(JOB, None, ATTEMPT, JOB)
    result = asyncio.run(stages.begin_attempt(JOB["id"], PipelineStage.DOWNLOAD))
    assert result.action == "RUN"
    assert result.attempt is not None and result.attempt.attempt == 1
    assert result.attempt.status == "RUNNING"
    assert connection.events == ["begin", "commit"]
    assert "FOR UPDATE" in connection.calls[0][0]
    assert "start_job_attempts" in connection.calls[0][0]
    insert = next((q, args) for q, args in connection.calls if q.startswith("INSERT INTO stage_attempts"))
    assert 1 in insert[1] and "DOWNLOAD" in insert[1]


def test_begin_recovers_worker_loss_and_allocates_next_attempt() -> None:
    prior = {**ATTEMPT, "attempt": 3}
    recovered = {**prior, "status": "FAILED", "completed_at": NOW, "duration_ms": 10, "error_code": "WORKER_LOST"}
    next_attempt = {**ATTEMPT, "attempt": 4}
    stages, connection = repo(JOB, prior, recovered, next_attempt, JOB)
    result = asyncio.run(stages.begin_attempt(JOB["id"], PipelineStage.DOWNLOAD))
    assert result.action == "RUN" and result.attempt.attempt == 4
    recovery_query, recovery_args = connection.calls[2]
    assert "error_code = $2" in recovery_query
    assert recovery_args[1] == "WORKER_LOST"
    assert "duration_ms" in recovery_query


def test_begin_fourth_worker_loss_fails_without_fifth_execution() -> None:
    prior = {**ATTEMPT, "attempt": 4}
    recovered = {**prior, "status": "FAILED", "error_code": "WORKER_LOST", "completed_at": NOW}
    failed = {**JOB, "status": "FAILED", "error_code": "WORKER_LOST"}
    stages, connection = repo(JOB, prior, recovered, failed)
    result = asyncio.run(stages.begin_attempt(JOB["id"], PipelineStage.DOWNLOAD))
    assert result.action == "FAILED" and result.job.status is JobStatus.FAILED
    assert result.job.error_code == "WORKER_LOST"
    assert not any(q.startswith("INSERT INTO stage_attempts") for q, _ in connection.calls)


def test_begin_cancellation_wins_over_worker_loss_exhaustion() -> None:
    prior = {**ATTEMPT, "attempt": 4}
    canceled = {**JOB, "status": "CANCELED"}
    stages, connection = repo({**JOB, "status": "CANCEL_REQUESTED"}, prior,
                              {**prior, "status": "FAILED", "error_code": "CANCELED"}, canceled)
    result = asyncio.run(stages.begin_attempt(JOB["id"], PipelineStage.DOWNLOAD))
    assert result.action == "CANCELED" and result.job.status is JobStatus.CANCELED
    assert not any(q.startswith("INSERT INTO stage_attempts") for q, _ in connection.calls)


@pytest.mark.parametrize("job", [None, {**JOB, "status": "COMPLETED"}, {**JOB, "current_stage": "PREPROCESS"}])
def test_begin_skips_missing_terminal_or_advanced_job(job: object) -> None:
    stages, connection = repo(job)
    result = asyncio.run(stages.begin_attempt(JOB["id"], PipelineStage.DOWNLOAD))
    assert result.action == "NOOP"
    assert len(connection.calls) == 1


def test_begin_rejects_fifth_retry_execution() -> None:
    stages, connection = repo({**JOB, "status": "RETRYING"},
                              {**ATTEMPT, "status": "FAILED", "attempt": 4, "error_code": "TRANSIENT"},
                              {**JOB, "status": "FAILED", "error_code": "RETRY_EXHAUSTED"})
    result = asyncio.run(stages.begin_attempt(JOB["id"], PipelineStage.DOWNLOAD))
    assert result.action == "FAILED"
    assert result.job.error_code == "RETRY_EXHAUSTED"
    assert not any(q.startswith("INSERT INTO stage_attempts") for q, _ in connection.calls)


def test_finish_success_advances_stage_and_records_duration() -> None:
    complete = {**ATTEMPT, "status": "COMPLETED", "completed_at": NOW, "duration_ms": 13}
    next_job = {**JOB, "current_stage": "PREPROCESS", "overall_progress": 16}
    stages, connection = repo(JOB, ATTEMPT, complete, next_job)
    result = asyncio.run(stages.finish_attempt(
        JOB["id"], PipelineStage.DOWNLOAD, ATTEMPT["id"],
        outcome="COMPLETED", next_stage=PipelineStage.PREPROCESS,
        stage_progress=0, overall_progress=16,
    ))
    assert result.job.current_stage is PipelineStage.PREPROCESS
    assert result.attempt.status == "COMPLETED"
    assert connection.events == ["begin", "commit"]
    assert any("duration_ms" in q and q.startswith("UPDATE stage_attempts") for q, _ in connection.calls)


def test_finish_failure_persists_stable_code_not_driver_detail() -> None:
    failed_attempt = {**ATTEMPT, "status": "FAILED", "error_code": "STAGE_FAILED", "completed_at": NOW}
    failed_job = {**JOB, "status": "FAILED", "error_code": "STAGE_FAILED"}
    stages, connection = repo(JOB, ATTEMPT, failed_attempt, failed_job)
    result = asyncio.run(stages.finish_attempt(
        JOB["id"], PipelineStage.DOWNLOAD, ATTEMPT["id"],
        outcome="FAILED", error_code="STAGE_FAILED",
        stage_progress=20, overall_progress=3,
    ))
    assert result.job.error_code == "STAGE_FAILED"
    assert all("secret-host" not in q and "secret-host" not in str(args) for q, args in connection.calls)
    with pytest.raises(ValueError):
        asyncio.run(stages.finish_attempt(
            JOB["id"], PipelineStage.DOWNLOAD, ATTEMPT["id"],
            outcome="FAILED", error_code="secret-host:password",
            stage_progress=0, overall_progress=0,
        ))


def test_finish_retry_records_retrying_status() -> None:
    failed_attempt = {**ATTEMPT, "status": "FAILED", "error_code": "TRANSIENT"}
    retrying = {**JOB, "status": "RETRYING", "error_code": "TRANSIENT"}
    stages, _ = repo(JOB, ATTEMPT, failed_attempt, retrying)
    result = asyncio.run(stages.finish_attempt(
        JOB["id"], PipelineStage.DOWNLOAD, ATTEMPT["id"],
        outcome="RETRYING", error_code="TRANSIENT", stage_progress=20,
        overall_progress=3,
    ))
    assert result.job.status is JobStatus.RETRYING
    assert result.attempt.status == "FAILED"


def test_fourth_transient_failure_ends_job_without_another_retry() -> None:
    fourth = {**ATTEMPT, "attempt": 4}
    failed_attempt = {**fourth, "status": "FAILED", "error_code": "TRANSIENT"}
    failed_job = {**JOB, "status": "FAILED", "error_code": "RETRY_EXHAUSTED"}
    stages, connection = repo(JOB, fourth, failed_attempt, failed_job)
    result = asyncio.run(stages.finish_attempt(
        JOB["id"], PipelineStage.DOWNLOAD, fourth["id"],
        outcome="RETRYING", error_code="TRANSIENT",
        stage_progress=40, overall_progress=6,
    ))
    assert result.job.status is JobStatus.FAILED
    assert result.job.error_code == "RETRY_EXHAUSTED"
    assert result.attempt.error_code == "TRANSIENT"
    job_update = connection.calls[-1]
    assert "FAILED" in job_update[1]
    assert "RETRY_EXHAUSTED" in job_update[1]


@pytest.mark.parametrize(
    "stage,next_stage,progress",
    [(PipelineStage.DOWNLOAD, None, 16),
     (PipelineStage.DOWNLOAD, PipelineStage.RENDER, 16),
     (PipelineStage.RENDER, PipelineStage.DOWNLOAD, 100),
     (PipelineStage.RENDER, None, 99)],
)
def test_finish_rejects_invalid_success_stage_progression(
    stage: PipelineStage, next_stage: PipelineStage | None, progress: int
) -> None:
    stages, connection = repo()
    with pytest.raises(ValueError):
        asyncio.run(stages.finish_attempt(
            JOB["id"], stage, ATTEMPT["id"],
            outcome="COMPLETED", next_stage=next_stage,
            stage_progress=100, overall_progress=progress,
        ))
    assert connection.calls == []


def test_finish_cancellation_race_closes_attempt_and_job_as_canceled() -> None:
    canceled_attempt = {**ATTEMPT, "status": "FAILED", "error_code": "CANCELED"}
    canceled_job = {**JOB, "status": "CANCELED"}
    stages, connection = repo({**JOB, "status": "CANCEL_REQUESTED", "stage_progress": 12,
                               "overall_progress": 2}, ATTEMPT,
                     canceled_attempt, canceled_job)
    result = asyncio.run(stages.finish_attempt(
        JOB["id"], PipelineStage.DOWNLOAD, ATTEMPT["id"],
        outcome="FAILED", error_code="STAGE_FAILED", stage_progress=20,
        overall_progress=3,
    ))
    assert result.job.status is JobStatus.CANCELED
    assert result.attempt.error_code == "CANCELED"
    job_update_args = connection.calls[-1][1]
    assert job_update_args[5:7] == (12, 2)


def test_stage_and_start_locks_use_distinct_stable_signed_keys() -> None:
    connection = Connection()
    stages = StageAttemptRepository(Pool(connection))  # type: ignore[arg-type]
    jobs = JobRepository(Pool(connection))  # type: ignore[arg-type]

    async def lock_once() -> None:
        await stages.acquire_stage_lock(JOB["id"], PipelineStage.DOWNLOAD, connection)  # type: ignore[arg-type]
        await stages.release_stage_lock(JOB["id"], PipelineStage.DOWNLOAD, connection)  # type: ignore[arg-type]
        await jobs.acquire_start_lock(JOB["id"], connection)  # type: ignore[arg-type]
        await jobs.release_start_lock(JOB["id"], connection)  # type: ignore[arg-type]

    asyncio.run(lock_once())
    keys = [args[0] for _, args in connection.calls]
    assert keys == [advisory_lock_key(JOB["id"], "DOWNLOAD"), keys[0],
                    advisory_lock_key(JOB["id"], "START_JOB"), keys[2]]
    assert keys[0] != keys[2]
    assert all(-(2**63) <= key < 2**63 for key in keys)
    assert connection.calls[0][0] == "SELECT pg_advisory_lock($1)"


def test_stage_lock_waits_for_prior_session_release() -> None:
    lock = asyncio.Lock()

    class BlockingConnection(Connection):
        async def execute(self, query: str, *args: object) -> str:
            self.calls.append((query, args))
            if "pg_advisory_lock(" in query:
                await lock.acquire()
            elif "pg_advisory_unlock(" in query:
                lock.release()
            return "OK"

    first = BlockingConnection()
    second = BlockingConnection()
    stages = StageAttemptRepository(Pool(first))  # type: ignore[arg-type]

    async def check() -> None:
        await stages.acquire_stage_lock(JOB["id"], PipelineStage.DOWNLOAD, first)  # type: ignore[arg-type]
        waiter = asyncio.create_task(
            stages.acquire_stage_lock(JOB["id"], PipelineStage.DOWNLOAD, second)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0)
        assert not waiter.done()
        await stages.release_stage_lock(JOB["id"], PipelineStage.DOWNLOAD, first)  # type: ignore[arg-type]
        await asyncio.wait_for(waiter, timeout=1)
        await stages.release_stage_lock(JOB["id"], PipelineStage.DOWNLOAD, second)  # type: ignore[arg-type]

    asyncio.run(check())
