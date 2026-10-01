"""Durable Celery entry points; broker payloads contain only the job ID."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from celery.exceptions import Ignore
from celery.utils.time import get_exponential_backoff_interval
from musicsheet_common import JobProgressEvent, JobStatus, PipelineStage

from musicsheet_api.config import Settings
from musicsheet_api.jobs.artifacts import ArtifactRepository
from musicsheet_api.jobs.events import JobEventStore
from musicsheet_api.jobs.repository import JobRepository
from musicsheet_api.jobs.stages import StageAttemptRepository
from musicsheet_api.pipeline.celery_app import celery_app
from musicsheet_api.pipeline.workflow import (
    STAGES, JobCancellationRequested, PermanentStageError, RetryableStageError,
    StageContext, StageHandler, build_stage_chain, overall_progress,
)


logger = logging.getLogger(__name__)
REGISTERED_HANDLERS: dict[PipelineStage, StageHandler] = {}
_STAGE_MESSAGES = {
    PipelineStage.DOWNLOAD: "Preparing source audio",
    PipelineStage.PREPROCESS: "Preparing audio",
    PipelineStage.SEPARATE: "Separating audio",
    PipelineStage.TRANSCRIBE: "Transcribing music",
    PipelineStage.POSTPROCESS: "Preparing score",
    PipelineStage.RENDER: "Rendering score",
}
_TERMINAL_MESSAGES = {
    JobStatus.CANCELED: "Job canceled",
    JobStatus.FAILED: "Stage failed",
    JobStatus.COMPLETED: "Job completed",
}
_RETRYABLE_STORAGE_ERRORS = (
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
    asyncpg.TooManyConnectionsError,
    ConnectionError,
    TimeoutError,
)


def _is_transient_storage_error(error: Exception) -> bool:
    """Classify connection loss, not arbitrary SQL or API programming faults."""
    if isinstance(error, _RETRYABLE_STORAGE_ERRORS):
        return True
    return type(error) is asyncpg.InterfaceError and str(error) in (
        "pool is closed", "pool is closing", "connection is closed",
    )


def _storage_error_or_raise(error: Exception) -> None:
    if _is_transient_storage_error(error):
        raise RetryableStageError("STAGE_STORAGE_UNAVAILABLE") from None
    raise error


def _retry_task_error(task, error: Exception, *, retry_count: int | None = None) -> None:
    """Retry typed transient persistence faults without a Celery delivery cap."""
    try:
        if isinstance(error, RetryableStageError):
            raise error
        _storage_error_or_raise(error)
    except RetryableStageError as safe_error:
        retries = task.request.retries if retry_count is None else retry_count
        countdown = get_exponential_backoff_interval(
            factor=1, retries=max(0, retries), maximum=60, full_jitter=True,
        )
        raise task.retry(
            exc=safe_error, countdown=countdown, max_retries=None,
        )


@dataclass
class WorkerRuntime:
    pool: Any
    jobs: JobRepository
    attempts: StageAttemptRepository
    artifacts: ArtifactRepository
    events: JobEventStore | None
    last_attempt_number: int = 0


@asynccontextmanager
async def _worker_runtime():
    """Each synchronous task owns and closes its async clients on one event loop."""
    settings = Settings.from_env()
    if not settings.database_url:
        raise RuntimeError("Worker database is not configured")
    pool = await asyncpg.create_pool(
        dsn=settings.database_url, min_size=1, max_size=3,
        timeout=2,
    )
    try:
        redis_client = aioredis.Redis.from_url(
            settings.redis_url or "redis://localhost:6379/2",
            socket_connect_timeout=2, socket_timeout=2,
        )
        try:
            yield WorkerRuntime(
                pool, JobRepository(pool), StageAttemptRepository(pool),
                ArtifactRepository(pool), JobEventStore(redis_client),
            )
        finally:
            await redis_client.aclose()
    finally:
        await pool.close()


async def _emit(runtime: WorkerRuntime, job, stage: PipelineStage, progress: int,
                total: int) -> None:
    if runtime.events is None or job is None:
        return
    message = _TERMINAL_MESSAGES.get(job.status, _STAGE_MESSAGES[stage])
    try:
        await runtime.events.publish(JobProgressEvent(
            job_id=job.id, status=job.status, stage=stage,
            stage_progress=progress, overall_progress=total, message=message,
        ))
    except Exception:
        logger.warning("Job progress event publication failed")


class ProgressReporter:
    """Synchronous handler callback that persists progress on the task event loop."""

    def __init__(self, runtime: WorkerRuntime, job_id: str, stage: PipelineStage,
                 loop: asyncio.AbstractEventLoop, *, overall_progress: int = 0) -> None:
        self._runtime = runtime
        self._job_id = job_id
        self._stage = stage
        self._loop = loop
        self.last_stage_progress = 0
        self.last_overall_progress = overall_progress

    def __call__(self, stage_progress: int) -> None:
        total = overall_progress(self._stage, stage_progress)
        future = asyncio.run_coroutine_threadsafe(self._save(stage_progress, total), self._loop)
        try:
            future.result(timeout=30)
        except FutureTimeout:
            future.cancel()
            raise RetryableStageError("PROGRESS_TIMEOUT") from None

    async def _save(self, progress: int, total: int) -> None:
        try:
            job = await self._runtime.jobs.get_job(self._job_id)
        except Exception as error:
            _storage_error_or_raise(error)
        if job is None or job.status is JobStatus.CANCEL_REQUESTED:
            raise JobCancellationRequested()
        if job.status is not JobStatus.RUNNING or job.current_stage is not self._stage:
            raise JobCancellationRequested()
        try:
            changed = await self._runtime.jobs.transition_job(
                self._job_id, expected_stage=self._stage,
                from_statuses=(JobStatus.RUNNING,), to_status=JobStatus.RUNNING,
                stage_progress=progress, overall_progress=total,
            )
        except Exception as error:
            _storage_error_or_raise(error)
        if changed is None:
            raise JobCancellationRequested()
        self.last_stage_progress = progress
        self.last_overall_progress = total
        await _emit(self._runtime, changed, self._stage, progress, total)


async def _execute_stage(
    job_id: str, stage: PipelineStage, runtime: WorkerRuntime,
    handlers: Mapping[PipelineStage, StageHandler],
) -> str:
    """A stage claim serializes duplicate deliveries through its handler and close."""
    async with runtime.pool.acquire() as connection:
        await runtime.attempts.acquire_stage_lock(job_id, stage, connection)
        try:
            began = await runtime.attempts.begin_attempt(job_id, stage)
            if began.action != "RUN":
                if began.action in ("CANCELED", "FAILED") and began.job is not None:
                    await _emit(runtime, began.job, stage,
                                began.job.stage_progress or 0,
                                began.job.overall_progress or 0)
                return began.action
            assert began.attempt is not None and began.job is not None
            runtime.last_attempt_number = began.attempt.attempt
            await _emit(runtime, began.job, stage, 0, began.job.overall_progress or 0)
            outcome = "COMPLETED"
            code = None
            reporter = ProgressReporter(
                runtime, job_id, stage, asyncio.get_running_loop(),
                overall_progress=began.job.overall_progress or 0,
            )
            try:
                handler = handlers.get(stage)
                if handler is None:
                    raise PermanentStageError("STAGE_NOT_CONFIGURED")
                try:
                    artifacts = tuple(await runtime.artifacts.list_for_job(job_id))
                except Exception as error:
                    _storage_error_or_raise(error)
                context = StageContext(job=began.job, stage=stage, artifacts=artifacts)
                await asyncio.to_thread(handler.run, context, reporter)
            except JobCancellationRequested:
                outcome = "CANCELED"
            except RetryableStageError as error:
                outcome, code = "RETRYING", error.code
            except PermanentStageError as error:
                outcome, code = "FAILED", error.code
            except Exception:
                logger.warning("Job stage handler failed")
                outcome, code = "FAILED", "STAGE_UNEXPECTED"

            next_stage = STAGES[STAGES.index(stage) + 1] if outcome == "COMPLETED" and stage is not PipelineStage.RENDER else None
            progress = 100 if outcome == "COMPLETED" else reporter.last_stage_progress
            total = overall_progress(stage, progress) if outcome == "COMPLETED" else reporter.last_overall_progress
            closed = await runtime.attempts.finish_attempt(
                job_id, stage, began.attempt.id, outcome=outcome,
                stage_progress=progress, overall_progress=total,
                next_stage=next_stage, error_code=code,
            )
            if closed.action == "NOOP":
                return "NOOP"
            await _emit(runtime, closed.job, stage,
                        closed.job.stage_progress or 0,
                        closed.job.overall_progress or 0)
            if outcome == "RETRYING" and closed.job.status is JobStatus.RETRYING:
                return "RETRY"
            return closed.job.status.value if closed.job.status in (
                JobStatus.CANCELED, JobStatus.FAILED, JobStatus.COMPLETED
            ) else "COMPLETED"
        finally:
            await runtime.attempts.release_stage_lock(job_id, stage, connection)


async def _start_workflow(
    job_id: str, runtime: WorkerRuntime, publish: Callable[[Any], Any],
) -> str:
    async with runtime.pool.acquire() as connection:
        await runtime.jobs.acquire_start_lock(job_id, connection)
        try:
            claim = await runtime.jobs.claim_start_job(job_id)
            if claim.action != "PUBLISH":
                if claim.action in ("CANCELED", "FAILED") and claim.job is not None:
                    await _emit(runtime, claim.job, claim.job.current_stage,
                                claim.job.stage_progress or 0,
                                claim.job.overall_progress or 0)
                return claim.action
            await _emit(runtime, claim.job, claim.job.current_stage,
                        claim.job.stage_progress or 0,
                        claim.job.overall_progress or 0)
            try:
                await asyncio.to_thread(publish, build_stage_chain(job_id))
            except Exception:
                logger.warning("Job workflow publication failed")
                changed = await runtime.jobs.fail_workflow_dispatch(job_id)
                if changed is not None and changed.status in (JobStatus.CANCELED, JobStatus.FAILED):
                    await _emit(runtime, changed, changed.current_stage,
                                changed.stage_progress or 0,
                                changed.overall_progress or 0)
                return changed.status.value if changed is not None else "NOOP"
            await runtime.jobs.mark_workflow_dispatched(job_id)
            return "PUBLISHED"
        finally:
            await runtime.jobs.release_start_lock(job_id, connection)


def _run_stage_task(task, job_id: str, stage: PipelineStage) -> None:
    async def run():
        async with _worker_runtime() as runtime:
            result = await _execute_stage(job_id, stage, runtime, REGISTERED_HANDLERS)
            return result, runtime.last_attempt_number

    try:
        result, attempt = asyncio.run(run())
    except Exception as error:
        _retry_task_error(task, error)
    if result == "RETRY":
        _retry_task_error(
            task, RetryableStageError("STAGE_RETRY"), retry_count=attempt - 1,
        )
    if result not in ("COMPLETED", "CONTINUE"):
        raise Ignore()


@celery_app.task(
    name="musicsheet.pipeline.start_job", bind=True,
    max_retries=None, retry_backoff=True, retry_backoff_max=60, retry_jitter=True,
)
def start_job(self, job_id: str) -> None:
    async def run():
        async with _worker_runtime() as runtime:
            return await _start_workflow(job_id, runtime, lambda workflow: workflow.apply_async())

    try:
        asyncio.run(run())
    except Exception as error:
        _retry_task_error(self, error)


def _stage_task(name: str, stage: PipelineStage):
    @celery_app.task(
        name=f"musicsheet.pipeline.{name}", bind=True,
        # PostgreSQL attempt rows, including worker-loss deliveries, enforce four executions.
        max_retries=None, retry_backoff=True, retry_backoff_max=60, retry_jitter=True,
    )
    def task(self, job_id: str) -> None:
        _run_stage_task(self, job_id, stage)

    return task


download_source = _stage_task("download_source", PipelineStage.DOWNLOAD)
preprocess_audio = _stage_task("preprocess_audio", PipelineStage.PREPROCESS)
separate_audio = _stage_task("separate_audio", PipelineStage.SEPARATE)
transcribe_amt = _stage_task("transcribe_amt", PipelineStage.TRANSCRIBE)
quantize_and_score = _stage_task("quantize_and_score", PipelineStage.POSTPROCESS)
render_pdf = _stage_task("render_pdf", PipelineStage.RENDER)
