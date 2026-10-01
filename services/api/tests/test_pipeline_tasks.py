"""Worker orchestration behavior with persistence and broker boundaries replaced."""

import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event

import pytest
import asyncpg
from celery.contrib.testing.worker import start_worker
from celery.exceptions import Ignore, Retry
from celery.signals import task_postrun
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.jobs.repository import StartClaimResult
from musicsheet_api.jobs.stages import StageAttemptRecord, StageBeginResult, StageFinishResult
from musicsheet_api.pipeline.tasks import (
    REGISTERED_HANDLERS,
    WorkerRuntime,
    ProgressReporter,
    _execute_stage,
    _start_workflow,
    start_job,
    _worker_runtime,
    download_source,
)
from musicsheet_api.pipeline.workflow import (
    JobCancellationRequested,
    PermanentStageError,
    RetryableStageError,
    build_stage_chain,
)
from musicsheet_api.pipeline.celery_app import celery_app


def job(status=JobStatus.RUNNING, stage=PipelineStage.DOWNLOAD, progress=0):
    now = datetime.now(timezone.utc)
    return JobRecord(
        "job-123", None, "UPLOAD", None, "piano", status, stage,
        progress, progress // 6, None, None, now, now, None,
    )


class Pool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


class Jobs:
    def __init__(self, initial=None, log=None):
        self.job = initial or job()
        self.log = log if log is not None else []
        self.claim = StartClaimResult("PUBLISH", self.job, 1)
        self.dispatched = False

    async def get_job(self, job_id):
        assert job_id == "job-123"
        return self.job

    async def transition_job(self, job_id, *, expected_stage, from_statuses, to_status,
                             stage_progress, overall_progress, **kwargs):
        assert job_id == "job-123"
        if self.job.status not in from_statuses or self.job.current_stage != expected_stage:
            return None
        self.log.append("db-progress")
        self.job = replace(self.job, status=to_status, stage_progress=stage_progress,
                           overall_progress=overall_progress)
        return self.job

    async def acquire_start_lock(self, job_id, connection):
        self.log.append("start-lock")

    async def release_start_lock(self, job_id, connection):
        self.log.append("start-unlock")

    async def claim_start_job(self, job_id):
        self.log.append("start-claim")
        return self.claim

    async def mark_workflow_dispatched(self, job_id):
        self.log.append("start-mark")
        self.dispatched = True
        return self.job

    async def fail_workflow_dispatch(self, job_id):
        self.log.append("start-fail")
        self.job = replace(self.job, status=JobStatus.FAILED,
                           error_code="WORKFLOW_DISPATCH_FAILED")
        return self.job


class Attempts:
    def __init__(self, jobs, action="RUN", number=1):
        self.jobs = jobs
        self.action = action
        self.number = number
        self.outcomes = []
        self.attempt = StageAttemptRecord(
            "attempt-1", "job-123", PipelineStage.DOWNLOAD, number, "RUNNING",
            None, None, None, None, None, None, None,
        )

    async def acquire_stage_lock(self, job_id, stage, connection):
        self.jobs.log.append("stage-lock")

    async def release_stage_lock(self, job_id, stage, connection):
        self.jobs.log.append("stage-unlock")

    async def begin_attempt(self, job_id, stage):
        self.jobs.log.append("stage-begin")
        return StageBeginResult(self.action, self.jobs.job,
                                self.attempt if self.action == "RUN" else None)

    async def finish_attempt(self, job_id, stage, attempt_id, *, outcome,
                             stage_progress, overall_progress, next_stage=None,
                             error_code=None):
        self.jobs.log.append("stage-finish")
        self.outcomes.append((outcome, error_code, stage_progress, overall_progress, next_stage))
        status = {
            "COMPLETED": JobStatus.COMPLETED if stage is PipelineStage.RENDER else JobStatus.RUNNING,
            "RETRYING": JobStatus.FAILED if self.number == 4 else JobStatus.RETRYING,
            "FAILED": JobStatus.FAILED,
            "CANCELED": JobStatus.CANCELED,
        }[outcome]
        if self.jobs.job.status is JobStatus.CANCEL_REQUESTED:
            status = JobStatus.CANCELED
            persisted_code = "CANCELED"
        elif outcome == "RETRYING" and self.number == 4:
            persisted_code = "RETRY_EXHAUSTED"
        else:
            persisted_code = error_code
        self.jobs.job = replace(self.jobs.job, status=status,
                                current_stage=next_stage or stage,
                                stage_progress=stage_progress,
                                overall_progress=overall_progress,
                                error_code=persisted_code)
        return StageFinishResult("UPDATED", self.jobs.job, self.attempt)


class Artifacts:
    async def list_for_job(self, job_id):
        assert job_id == "job-123"
        return []


class Events:
    def __init__(self, log):
        self.log = log
        self.published = []
        self.raise_error = False

    async def publish(self, event):
        self.log.append("event")
        self.published.append(event)
        if self.raise_error:
            raise ConnectionError("secret Redis connection information")
        return "1-0"


def runtime(*, status=JobStatus.RUNNING, action="RUN", number=1):
    log = []
    jobs = Jobs(job(status=status), log)
    attempts = Attempts(jobs, action=action, number=number)
    events = Events(log)
    return WorkerRuntime(Pool(), jobs, attempts, Artifacts(), events), log


def test_missing_handler_fails_persisted_attempt_with_stable_code() -> None:
    rt, log = runtime()
    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt, {}))

    assert result == "FAILED"
    assert rt.attempts.outcomes[0][:2] == ("FAILED", "STAGE_NOT_CONFIGURED")
    assert rt.jobs.job.status is JobStatus.FAILED
    assert log.index("stage-begin") < log.index("stage-finish") < len(log) - 2
    assert log[-2:] == ["event", "stage-unlock"]
    assert log[-1] == "stage-unlock"


def test_successful_handler_loads_records_and_advances_after_persisting() -> None:
    rt, log = runtime()

    class Handler:
        def run(self, context, report_progress):
            assert context.job.id == "job-123"
            assert context.idempotency_key == ("job-123", PipelineStage.DOWNLOAD)
            assert context.artifacts == ()
            report_progress(50)

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == "COMPLETED"
    assert rt.attempts.outcomes == [("COMPLETED", None, 100, 16, PipelineStage.PREPROCESS)]
    assert [(event.stage_progress, event.overall_progress) for event in rt.events.published] == [
        (0, 0), (50, 8), (100, 16),
    ]
    assert log[log.index("db-progress") + 1] == "event"
    assert log[-1] == "stage-unlock"


@pytest.mark.parametrize("number, expected", [(1, "RETRY"), (4, "FAILED")])
def test_transient_handler_error_uses_persisted_attempt_limit(number, expected) -> None:
    rt, _ = runtime(number=number)

    class Handler:
        def run(self, context, report_progress):
            raise RetryableStageError("SOURCE_UNAVAILABLE")

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == expected
    assert rt.attempts.outcomes[0][0] == "RETRYING"
    assert rt.jobs.job.status is (JobStatus.RETRYING if number == 1 else JobStatus.FAILED)


def test_cancellation_at_progress_checkpoint_closes_attempt() -> None:
    rt, _ = runtime()

    class Handler:
        def run(self, context, report_progress):
            rt.jobs.job = replace(rt.jobs.job, status=JobStatus.CANCEL_REQUESTED)
            report_progress(30)

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == "CANCELED"
    assert rt.attempts.outcomes[0][:2] == ("CANCELED", None)
    assert rt.jobs.job.status is JobStatus.CANCELED
    assert all(event.stage_progress != 30 for event in rt.events.published)


@pytest.mark.parametrize("action", ["NOOP", "CANCELED", "FAILED"])
def test_stage_claim_nonrun_result_never_enters_handler(action) -> None:
    rt, log = runtime(action=action)

    class Handler:
        def run(self, context, report_progress):
            raise AssertionError("must not run")

    assert asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                      {PipelineStage.DOWNLOAD: Handler()})) == action
    assert not rt.attempts.outcomes
    assert log[-1] == "stage-unlock"


def test_event_failure_keeps_committed_failure_and_releases_stage_lock(caplog) -> None:
    rt, log = runtime()
    rt.events.raise_error = True

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt, {}))

    assert result == "FAILED"
    assert rt.jobs.job.status is JobStatus.FAILED
    assert log[-1] == "stage-unlock"
    assert "secret Redis" not in caplog.text


def test_start_publishes_one_chain_after_claim_and_marks_dispatch() -> None:
    rt, log = runtime()
    published = []

    def publish(workflow):
        published.append(workflow)
        log.append("chain-publish")

    assert asyncio.run(_start_workflow("job-123", rt, publish)) == "PUBLISHED"
    assert len(published) == 1
    assert log.index("start-claim") < log.index("chain-publish") < log.index("start-mark")
    assert log[-1] == "start-unlock"


@pytest.mark.parametrize("action", ["NOOP", "CANCELED", "FAILED"])
def test_start_nonpublish_claim_never_sends_chain(action) -> None:
    rt, log = runtime()
    rt.jobs.claim = StartClaimResult(action, rt.jobs.job, 4)

    assert asyncio.run(_start_workflow("job-123", rt, lambda workflow: pytest.fail("published"))) == action
    assert log[-1] == "start-unlock"


def test_start_chain_publish_error_transitions_only_if_repository_allows(caplog) -> None:
    rt, log = runtime()

    def reject(workflow):
        raise ConnectionError("secret broker URL")

    assert asyncio.run(_start_workflow("job-123", rt, reject)) == "FAILED"
    assert rt.jobs.job.error_code == "WORKFLOW_DISPATCH_FAILED"
    assert log.index("start-claim") < log.index("start-fail")
    assert "secret broker" not in caplog.text


def test_worker_app_loads_all_stage_tasks_without_importing_api_app() -> None:
    script = (
        "from musicsheet_api.pipeline.celery_app import celery_app; "
        "celery_app.loader.import_default_modules(); "
        "names = set(celery_app.tasks); "
        "assert all('musicsheet.pipeline.' + name in names for name in "
        "('start_job','download_source','preprocess_audio','separate_audio',"
        "'transcribe_amt','quantize_and_score','render_pdf'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("action", ["NOOP", "CANCELED", "FAILED"])
def test_stage_task_suppresses_chain_continuation_on_non_success(monkeypatch, action) -> None:
    rt, _ = runtime(action=action)

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    with pytest.raises(Ignore):
        download_source.run("job-123")


def test_stage_task_returns_normally_for_proven_completed_stage(monkeypatch) -> None:
    rt, _ = runtime(action="CONTINUE")
    rt.jobs.job = job(stage=PipelineStage.PREPROCESS)

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)

    assert download_source.run("job-123") is None


@pytest.mark.parametrize("failure_point", ["lock", "begin", "finish"])
def test_transient_stage_database_errors_retry_after_default_celery_limit(monkeypatch, failure_point) -> None:
    rt, _ = runtime()
    handler_calls = []

    class Handler:
        def run(self, context, report_progress):
            handler_calls.append(context.stage)

    error = asyncpg.ConnectionFailureError("secret database host")
    if failure_point == "lock":
        async def fail_lock(*args):
            raise error
        rt.attempts.acquire_stage_lock = fail_lock
    elif failure_point == "begin":
        async def fail_begin(*args, **kwargs):
            raise error
        rt.attempts.begin_attempt = fail_begin
    else:
        async def fail_finish(*args, **kwargs):
            raise error
        rt.attempts.finish_attempt = fail_finish

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD, Handler())
    download_source.push_request(id="preclaim-retry", retries=5, called_directly=False,
                                 is_eager=True, args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry) as raised:
            download_source.run("job-123")
    finally:
        download_source.pop_request()

    assert download_source.max_retries is None
    assert isinstance(raised.value.exc, RetryableStageError)
    assert raised.value.exc.code == "STAGE_STORAGE_UNAVAILABLE"
    assert "secret database host" not in str(raised.value.exc)
    assert handler_calls == ([] if failure_point != "finish" else [PipelineStage.DOWNLOAD])
    assert rt.attempts.outcomes == []


def test_stage_preclaim_retry_continues_after_database_recovers(monkeypatch) -> None:
    rt, _ = runtime()
    original_begin = rt.attempts.begin_attempt
    failures = 1
    handler_calls = []

    async def begin(job_id, stage):
        nonlocal failures
        if failures:
            failures -= 1
            raise asyncpg.ConnectionFailureError("temporary database outage")
        return await original_begin(job_id, stage)

    rt.attempts.begin_attempt = begin

    class Handler:
        def run(self, context, report_progress):
            handler_calls.append(context.stage)

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD, Handler())
    download_source.push_request(id="stage-before-recovery", retries=5,
                                 called_directly=False, is_eager=True,
                                 args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry):
            download_source.run("job-123")
    finally:
        download_source.pop_request()
    assert handler_calls == [] and rt.attempts.outcomes == []

    download_source.push_request(id="stage-after-recovery", retries=6,
                                 called_directly=False, is_eager=True,
                                 args=("job-123",), kwargs={})
    try:
        assert download_source.run("job-123") is None
    finally:
        download_source.pop_request()
    assert handler_calls == [PipelineStage.DOWNLOAD]
    assert rt.attempts.outcomes[0][0] == "COMPLETED"


def test_transient_start_database_error_retries_after_default_celery_limit_and_recovers(monkeypatch) -> None:
    rt, _ = runtime()
    publish_calls = []
    failures = 1

    async def fail_claim(job_id):
        nonlocal failures
        if failures:
            failures -= 1
            raise asyncpg.ConnectionFailureError("secret database host")
        return StartClaimResult("PUBLISH", rt.jobs.job, 1)

    rt.jobs.claim_start_job = fail_claim

    class Workflow:
        def apply_async(self):
            publish_calls.append("published")

    monkeypatch.setattr("musicsheet_api.pipeline.tasks.build_stage_chain",
                        lambda job_id: Workflow())

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    start_job.push_request(id="start-preclaim-retry", retries=5, called_directly=False,
                          is_eager=True, args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry) as raised:
            start_job.run("job-123")
    finally:
        start_job.pop_request()

    assert start_job.max_retries is None
    assert isinstance(raised.value.exc, RetryableStageError)
    assert raised.value.exc.code == "STAGE_STORAGE_UNAVAILABLE"
    assert "secret database host" not in str(raised.value.exc)
    assert publish_calls == [] and rt.jobs.dispatched is False

    start_job.push_request(id="start-recovered", retries=6, called_directly=False,
                          is_eager=True, args=("job-123",), kwargs={})
    try:
        assert start_job.run("job-123") is None
    finally:
        start_job.pop_request()
    assert publish_calls == ["published"] and rt.jobs.dispatched is True


def test_transient_worker_runtime_creation_error_retries_for_start_and_stage(monkeypatch) -> None:
    @asynccontextmanager
    async def unavailable_runtime():
        raise asyncpg.ConnectionFailureError("secret database host")
        yield  # pragma: no cover

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", unavailable_runtime)
    for task in (start_job, download_source):
        task.push_request(id=f"runtime-retry-{task.name}", retries=5,
                          called_directly=False, is_eager=True,
                          args=("job-123",), kwargs={})
        try:
            with pytest.raises(Retry) as raised:
                task.run("job-123")
        finally:
            task.pop_request()
        assert isinstance(raised.value.exc, RetryableStageError)
        assert raised.value.exc.code == "STAGE_STORAGE_UNAVAILABLE"


def test_transient_start_bookkeeping_error_retries_without_losing_accepted_chain(monkeypatch) -> None:
    rt, _ = runtime()
    publish_calls = []
    mark_failures = 1

    async def claim(job_id):
        return StartClaimResult("PUBLISH", rt.jobs.job, 1)

    async def mark(job_id):
        nonlocal mark_failures
        if mark_failures:
            mark_failures -= 1
            raise asyncpg.ConnectionFailureError("secret database host")
        rt.jobs.dispatched = True
        return rt.jobs.job

    rt.jobs.claim_start_job = claim
    rt.jobs.mark_workflow_dispatched = mark

    class Workflow:
        def apply_async(self):
            publish_calls.append("published")

    monkeypatch.setattr("musicsheet_api.pipeline.tasks.build_stage_chain",
                        lambda job_id: Workflow())

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    start_job.push_request(id="start-mark-retry", retries=0, called_directly=False,
                          is_eager=True, args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry) as raised:
            start_job.run("job-123")
    finally:
        start_job.pop_request()
    assert isinstance(raised.value.exc, RetryableStageError)
    assert len(publish_calls) == 1 and rt.jobs.dispatched is False

    start_job.push_request(id="start-mark-recovered", retries=1, called_directly=False,
                          is_eager=True, args=("job-123",), kwargs={})
    try:
        assert start_job.run("job-123") is None
    finally:
        start_job.pop_request()
    assert len(publish_calls) == 2 and rt.jobs.dispatched is True


def test_retry_after_committed_finish_response_loss_continues_without_rerunning_handler(monkeypatch) -> None:
    rt, _ = runtime()
    advanced_job = job(stage=PipelineStage.PREPROCESS, progress=16)
    completed_download = StageAttemptRecord(
        "attempt-1", "job-123", PipelineStage.DOWNLOAD, 1, "COMPLETED",
        None, None, None, datetime.now(timezone.utc), 1, None, None,
    )
    original_attempt = rt.attempts.attempt
    begin_calls = 0
    finish_calls = 0
    handler_calls = []

    async def begin(job_id, stage):
        nonlocal begin_calls
        begin_calls += 1
        if begin_calls == 1:
            return StageBeginResult("RUN", rt.jobs.job, original_attempt)
        return StageBeginResult("CONTINUE", advanced_job, completed_download)

    async def finish(job_id, stage, attempt_id, **kwargs):
        nonlocal finish_calls
        finish_calls += 1
        rt.jobs.job = advanced_job  # The transaction committed; only its response was lost.
        raise asyncpg.ConnectionFailureError("connection dropped after commit")

    rt.attempts.begin_attempt = begin
    rt.attempts.finish_attempt = finish

    class Handler:
        def run(self, context, report_progress):
            handler_calls.append(context.stage)

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD, Handler())

    download_source.push_request(id="finish-commit-lost-response", retries=0,
                                 called_directly=False, is_eager=True,
                                 args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry):
            download_source.run("job-123")
    finally:
        download_source.pop_request()
    assert handler_calls == [PipelineStage.DOWNLOAD] and finish_calls == 1

    download_source.push_request(id="finish-commit-recovered", retries=1,
                                 called_directly=False, is_eager=True,
                                 args=("job-123",), kwargs={})
    try:
        assert download_source.run("job-123") is None
    finally:
        download_source.pop_request()
    assert handler_calls == [PipelineStage.DOWNLOAD]


def test_retry_after_rolled_back_finish_recovers_open_attempt_without_exceeding_budget(monkeypatch) -> None:
    rt, _ = runtime()
    attempt_three = replace(rt.attempts.attempt, attempt=3)
    attempt_four = replace(rt.attempts.attempt, id="attempt-4", attempt=4)
    begin_calls = 0
    finish_calls = 0
    handler_calls = []

    async def begin(job_id, stage):
        nonlocal begin_calls
        begin_calls += 1
        assert rt.jobs.job.current_stage is PipelineStage.DOWNLOAD
        return StageBeginResult("RUN", rt.jobs.job,
                                attempt_three if begin_calls == 1 else attempt_four)

    async def finish(job_id, stage, attempt_id, **kwargs):
        nonlocal finish_calls
        finish_calls += 1
        if finish_calls == 1:
            # The transaction rolled back: job stage and prior RUNNING attempt remain unchanged.
            raise asyncpg.ConnectionFailureError("connection lost before commit")
        advanced = replace(rt.jobs.job, current_stage=PipelineStage.PREPROCESS,
                           stage_progress=100, overall_progress=16)
        rt.jobs.job = advanced
        return StageFinishResult("UPDATED", advanced, attempt_four)

    rt.attempts.begin_attempt = begin
    rt.attempts.finish_attempt = finish

    class Handler:
        def run(self, context, report_progress):
            handler_calls.append(context.stage)

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD, Handler())

    download_source.push_request(id="finish-rollback", retries=0, called_directly=False,
                                 is_eager=True, args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry):
            download_source.run("job-123")
    finally:
        download_source.pop_request()
    assert rt.jobs.job.current_stage is PipelineStage.DOWNLOAD

    download_source.push_request(id="finish-rollback-recovered", retries=1,
                                 called_directly=False, is_eager=True,
                                 args=("job-123",), kwargs={})
    try:
        assert download_source.run("job-123") is None
    finally:
        download_source.pop_request()
    assert handler_calls == [PipelineStage.DOWNLOAD, PipelineStage.DOWNLOAD]
    assert begin_calls == 2 and finish_calls == 2


@pytest.mark.parametrize("cancel_requested", [False, True])
def test_completed_stage_redelivery_publishes_real_celery_success_callback(monkeypatch, cancel_requested) -> None:
    rt, _ = runtime()
    starting_status = JobStatus.CANCEL_REQUESTED if cancel_requested else JobStatus.RUNNING
    rt.jobs.job = job(status=starting_status, stage=PipelineStage.PREPROCESS)
    observed_stages = []
    preprocess_ran = Event()
    preprocess_reached = Event()
    preprocess_canceled = Event()
    preprocess_finished = Event()
    separate_reached = Event()
    preprocess_task_states = []
    completed_download = StageAttemptRecord(
        "download-complete", "job-123", PipelineStage.DOWNLOAD, 1, "COMPLETED",
        None, None, None, datetime.now(timezone.utc), 1, None, None,
    )
    preprocess_attempt = StageAttemptRecord(
        "preprocess-running", "job-123", PipelineStage.PREPROCESS, 1, "RUNNING",
        None, None, None, None, None, None, None,
    )

    async def begin(job_id, stage):
        observed_stages.append(stage)
        if stage is PipelineStage.DOWNLOAD:
            return StageBeginResult("CONTINUE", rt.jobs.job, completed_download)
        if stage is PipelineStage.PREPROCESS:
            preprocess_reached.set()
            if cancel_requested:
                canceled = replace(rt.jobs.job, status=JobStatus.CANCELED, error_code="CANCELED")
                rt.jobs.job = canceled
                preprocess_canceled.set()
                return StageBeginResult("CANCELED", canceled)
            return StageBeginResult("RUN", rt.jobs.job, preprocess_attempt)
        if stage is PipelineStage.SEPARATE:
            separate_reached.set()
        return StageBeginResult("NOOP", rt.jobs.job)

    async def finish(job_id, stage, attempt_id, **kwargs):
        advanced = replace(rt.jobs.job, current_stage=PipelineStage.SEPARATE,
                           stage_progress=100, overall_progress=33)
        rt.jobs.job = advanced
        return StageFinishResult("UPDATED", advanced, preprocess_attempt)

    rt.attempts.begin_attempt = begin
    rt.attempts.finish_attempt = finish

    class Handler:
        def run(self, context, report_progress):
            assert context.stage is PipelineStage.PREPROCESS
            assert not cancel_requested
            preprocess_ran.set()

    class CompletedHandlerMustNotRun:
        def run(self, context, report_progress):
            raise AssertionError("completed stage handler must not run on callback recovery")

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD,
                        CompletedHandlerMustNotRun())
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.PREPROCESS, Handler())
    def on_task_postrun(sender=None, state=None, **kwargs):
        if sender is not None and sender.name == "musicsheet.pipeline.preprocess_audio":
            preprocess_task_states.append(state)
            preprocess_finished.set()

    task_postrun.connect(on_task_postrun, weak=False)
    old_broker, old_backend = celery_app.conf.broker_url, celery_app.conf.result_backend
    celery_app.conf.update(broker_url="memory://", result_backend="cache+memory://",
                           task_always_eager=False, task_eager_propagates=False)
    try:
        with start_worker(
            celery_app, pool="solo",
            queues=("cpu_io_queue", "gpu_ai_queue", "cpu_render_queue"),
            perform_ping_check=False, loglevel="ERROR",
        ):
            build_stage_chain("job-123").apply_async()
            assert preprocess_reached.wait(timeout=5)
            if cancel_requested:
                assert preprocess_canceled.wait(timeout=5)
                assert preprocess_finished.wait(timeout=5)
                assert preprocess_task_states == ["IGNORED"]
                assert not preprocess_ran.is_set()
                assert rt.jobs.job.status is JobStatus.CANCELED
            else:
                assert preprocess_ran.wait(timeout=5)
                assert separate_reached.wait(timeout=5)
    finally:
        task_postrun.disconnect(on_task_postrun)
        celery_app.conf.update(broker_url=old_broker, result_backend=old_backend,
                               task_always_eager=False)

    expected_stages = [PipelineStage.DOWNLOAD, PipelineStage.PREPROCESS]
    if not cancel_requested:
        expected_stages.append(PipelineStage.SEPARATE)
    assert observed_stages[:len(expected_stages)] == expected_stages


def test_eager_chain_never_runs_a_handler_after_first_stage_noop(monkeypatch) -> None:
    rt, _ = runtime(action="NOOP")
    handler_calls = []

    class Handler:
        def run(self, context, report_progress):
            handler_calls.append(context.stage)

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD, Handler())
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.PREPROCESS, Handler())
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)
    monkeypatch.setitem(celery_app.conf, "task_eager_propagates", False)

    build_stage_chain("job-123").apply_async()

    # Celery's eager canvas iterates its tasks even after Ignore; the guarded
    # stage claim still prevents any handler side effect.
    assert handler_calls == []


@pytest.mark.parametrize("invalid", [-1, 101, False, 33.5, "50"])
def test_progress_reporter_rejects_invalid_input_before_database_write(invalid) -> None:
    rt, log = runtime()

    async def invoke():
        reporter = ProgressReporter(rt, "job-123", PipelineStage.DOWNLOAD,
                                    asyncio.get_running_loop())
        await asyncio.to_thread(reporter, invalid)

    with pytest.raises(ValueError):
        asyncio.run(invoke())
    assert "db-progress" not in log
    assert "event" not in log


def test_progress_event_uses_fixed_public_stage_message() -> None:
    rt, _ = runtime()

    class Handler:
        def run(self, context, report_progress):
            report_progress(40)

    asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                               {PipelineStage.DOWNLOAD: Handler()}))

    assert {event.message for event in rt.events.published} == {"Preparing source audio"}


def test_schema_v1_claim_failure_releases_lock_before_any_handler_effect() -> None:
    rt, log = runtime()
    called = []

    async def old_schema(job_id, stage):
        raise RuntimeError("undefined_column: start_job_attempts")

    rt.attempts.begin_attempt = old_schema

    class Handler:
        def run(self, context, report_progress):
            called.append(True)

    with pytest.raises(RuntimeError, match="undefined_column"):
        asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                   {PipelineStage.DOWNLOAD: Handler()}))
    assert called == []
    assert log[-1] == "stage-unlock"


def test_accepted_chain_then_reported_error_does_not_force_terminal_failure() -> None:
    rt, log = runtime()
    accepted = []

    async def worker_already_claimed(job_id):
        log.append("start-fail-guarded")
        return rt.jobs.job

    rt.jobs.fail_workflow_dispatch = worker_already_claimed

    def accepted_then_error(workflow):
        accepted.append(workflow)
        raise ConnectionError("after acceptance")

    assert asyncio.run(_start_workflow("job-123", rt, accepted_then_error)) == "RUNNING"
    assert len(accepted) == 1
    assert rt.jobs.job.status is JobStatus.RUNNING
    assert log[-1] == "start-unlock"


@pytest.mark.parametrize("accepted_before_loss", [False, True])
def test_start_worker_loss_before_or_after_broker_acceptance_uses_durable_claim(
    accepted_before_loss,
) -> None:
    rt, log = runtime()
    claims = iter([1, 2, 3, 4])
    published = []

    async def claim(job_id):
        number = next(claims)
        log.append(f"claim-{number}")
        return StartClaimResult("PUBLISH", rt.jobs.job, number)

    rt.jobs.claim_start_job = claim

    def crash(workflow):
        if accepted_before_loss:
            published.append(workflow)
        raise SystemExit("worker lost")

    for number in range(1, 5):
        with pytest.raises(SystemExit):
            asyncio.run(_start_workflow("job-123", rt, crash))
        assert f"claim-{number}" in log
        assert log[-1] == "start-unlock"
    assert len(published) == (4 if accepted_before_loss else 0)
    async def exhausted(job_id):
        return StartClaimResult("FAILED", replace(rt.jobs.job, status=JobStatus.FAILED,
                                                  error_code="WORKFLOW_WORKER_LOST"), 4)

    rt.jobs.claim_start_job = exhausted
    assert asyncio.run(_start_workflow("job-123", rt, lambda workflow: pytest.fail("published"))) == "FAILED"


def test_worker_runtime_closes_owned_pool_if_redis_client_creation_fails(monkeypatch) -> None:
    closed = []

    class OwnedPool:
        async def close(self):
            closed.append("pool")

    async def create_pool(**kwargs):
        return OwnedPool()

    class SettingsStub:
        database_url = "postgresql://example.invalid/db"
        redis_url = "redis://example.invalid/2"

    def refuse_redis(*args, **kwargs):
        raise ValueError("bad Redis URL")

    monkeypatch.setattr("musicsheet_api.pipeline.tasks.Settings.from_env", lambda: SettingsStub())
    monkeypatch.setattr("musicsheet_api.pipeline.tasks.asyncpg.create_pool", create_pool)
    monkeypatch.setattr("musicsheet_api.pipeline.tasks.aioredis.Redis.from_url", refuse_redis)

    async def open_resources():
        async with _worker_runtime():
            pass

    with pytest.raises(ValueError, match="bad Redis URL"):
        asyncio.run(open_resources())
    assert closed == ["pool"]


def test_persisted_attempt_limit_allows_retry_despite_high_celery_counter(monkeypatch) -> None:
    rt, _ = runtime(number=1)

    class Handler:
        def run(self, context, report_progress):
            raise RetryableStageError("SOURCE_UNAVAILABLE")

    @asynccontextmanager
    async def resources():
        yield rt

    monkeypatch.setattr("musicsheet_api.pipeline.tasks._worker_runtime", resources)
    monkeypatch.setitem(REGISTERED_HANDLERS, PipelineStage.DOWNLOAD, Handler())
    download_source.push_request(id="redelivery-1", retries=10, called_directly=False,
                                 is_eager=True,
                                 args=("job-123",), kwargs={})
    try:
        with pytest.raises(Retry):
            download_source.run("job-123")
    finally:
        download_source.pop_request()
    assert rt.attempts.outcomes[0][0] == "RETRYING"


def test_worker_pool_allows_advisory_lock_wait_beyond_query_timeout(monkeypatch) -> None:
    captured = {}

    class OwnedPool:
        async def close(self):
            pass

    class RedisClient:
        async def aclose(self):
            pass

    async def create_pool(**kwargs):
        captured.update(kwargs)
        return OwnedPool()

    class SettingsStub:
        database_url = "postgresql://example.invalid/db"
        redis_url = "redis://example.invalid/2"

    monkeypatch.setattr("musicsheet_api.pipeline.tasks.Settings.from_env", lambda: SettingsStub())
    monkeypatch.setattr("musicsheet_api.pipeline.tasks.asyncpg.create_pool", create_pool)
    monkeypatch.setattr("musicsheet_api.pipeline.tasks.aioredis.Redis.from_url",
                        lambda *args, **kwargs: RedisClient())

    async def open_resources():
        async with _worker_runtime():
            pass

    asyncio.run(open_resources())
    assert "command_timeout" not in captured


@pytest.mark.parametrize("number, expected", [(1, "RETRY"), (4, "FAILED")])
def test_transient_artifact_query_error_persists_retry_with_safe_code(number, expected, caplog) -> None:
    rt, log = runtime(number=number)
    handler_calls = []

    async def unavailable(job_id):
        raise asyncpg.ConnectionFailureError("secret database hostname")

    rt.artifacts.list_for_job = unavailable

    class Handler:
        def run(self, context, report_progress):
            handler_calls.append(True)

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == expected
    assert handler_calls == []
    assert rt.attempts.outcomes[0][:2] == ("RETRYING", "STAGE_STORAGE_UNAVAILABLE")
    assert rt.jobs.job.status is (JobStatus.RETRYING if number == 1 else JobStatus.FAILED)
    assert rt.jobs.job.error_code == ("STAGE_STORAGE_UNAVAILABLE" if number == 1 else "RETRY_EXHAUSTED")
    assert log[-2:] == ["event", "stage-unlock"]
    assert "secret database" not in caplog.text
    assert all("secret database" not in event.message for event in rt.events.published)


@pytest.mark.parametrize("number, expected", [(1, "RETRY"), (4, "FAILED")])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_progress_checkpoint_db_error_persists_retry(number, expected, operation, caplog) -> None:
    rt, _ = runtime(number=number)
    original_get = rt.jobs.get_job
    original_transition = rt.jobs.transition_job
    calls = 0

    async def unavailable_once(job_id):
        nonlocal calls
        calls += 1
        if operation == "read" and calls == 1:
            raise asyncpg.ConnectionFailureError("secret pool connection")
        return await original_get(job_id)

    async def write_unavailable_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if operation == "write" and calls == 2:
            raise asyncpg.ConnectionFailureError("secret pool connection")
        return await original_transition(*args, **kwargs)

    rt.jobs.get_job = unavailable_once
    rt.jobs.transition_job = write_unavailable_once

    class Handler:
        def run(self, context, report_progress):
            report_progress(50)

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == expected
    assert rt.attempts.outcomes[0][:2] == ("RETRYING", "STAGE_STORAGE_UNAVAILABLE")
    assert rt.jobs.job.error_code == ("STAGE_STORAGE_UNAVAILABLE" if number == 1 else "RETRY_EXHAUSTED")
    assert all(event.stage_progress != 50 for event in rt.events.published)
    assert "secret pool" not in caplog.text


def test_transient_artifact_error_cannot_override_committed_cancellation() -> None:
    rt, _ = runtime()

    async def cancel_then_disconnect(job_id):
        rt.jobs.job = replace(rt.jobs.job, status=JobStatus.CANCEL_REQUESTED)
        raise ConnectionResetError("secret socket")

    rt.artifacts.list_for_job = cancel_then_disconnect

    class Handler:
        def run(self, context, report_progress):
            pytest.fail("handler must not start")

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == "CANCELED"
    assert rt.attempts.outcomes[0][:2] == ("RETRYING", "STAGE_STORAGE_UNAVAILABLE")
    assert rt.jobs.job.status is JobStatus.CANCELED
    assert rt.jobs.job.error_code == "CANCELED"


def test_permanent_sql_artifact_error_is_not_retried() -> None:
    rt, _ = runtime()

    async def invalid_query(job_id):
        raise asyncpg.UndefinedColumnError("programming defect")

    rt.artifacts.list_for_job = invalid_query

    class Handler:
        def run(self, context, report_progress):
            pytest.fail("handler must not start")

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == "FAILED"
    assert rt.attempts.outcomes[0][:2] == ("FAILED", "STAGE_UNEXPECTED")


@pytest.mark.parametrize("error", [
    asyncpg.InterfaceError("pool is closed"),
    asyncpg.InterfaceError("connection is closed"),
    asyncpg.CannotConnectNowError("database restarting"),
    TimeoutError("database timeout"),
])
def test_recognized_pool_or_connection_error_is_retryable(error) -> None:
    rt, _ = runtime()

    async def unavailable(job_id):
        raise error

    rt.artifacts.list_for_job = unavailable

    class Handler:
        def run(self, context, report_progress):
            pytest.fail("handler must not start")

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))
    assert result == "RETRY"
    assert rt.attempts.outcomes[0][:2] == ("RETRYING", "STAGE_STORAGE_UNAVAILABLE")


def test_programming_interface_error_is_permanent() -> None:
    rt, _ = runtime()

    async def programmer_error(job_id):
        raise asyncpg.InterfaceError("another operation is in progress")

    rt.artifacts.list_for_job = programmer_error

    class Handler:
        def run(self, context, report_progress):
            pytest.fail("handler must not start")

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))
    assert result == "FAILED"
    assert rt.attempts.outcomes[0][:2] == ("FAILED", "STAGE_UNEXPECTED")


def test_storage_retry_uses_last_committed_snapshot_without_extra_job_read() -> None:
    rt, _ = runtime()

    async def unavailable(job_id):
        raise asyncpg.ConnectionFailureError("temporary database outage")

    rt.artifacts.list_for_job = unavailable
    rt.jobs.get_job = unavailable

    class Handler:
        def run(self, context, report_progress):
            pytest.fail("handler must not start")

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == "RETRY"
    assert rt.attempts.outcomes[0] == (
        "RETRYING", "STAGE_STORAGE_UNAVAILABLE", 0, 0, None,
    )


def test_closed_connection_during_progress_db_access_is_retryable() -> None:
    rt, _ = runtime()

    async def closed_connection(job_id):
        raise asyncpg.InterfaceError("connection is closed")

    rt.jobs.get_job = closed_connection

    class Handler:
        def run(self, context, report_progress):
            report_progress(25)

    result = asyncio.run(_execute_stage("job-123", PipelineStage.DOWNLOAD, rt,
                                        {PipelineStage.DOWNLOAD: Handler()}))

    assert result == "RETRY"
    assert rt.attempts.outcomes[0][:2] == ("RETRYING", "STAGE_STORAGE_UNAVAILABLE")
