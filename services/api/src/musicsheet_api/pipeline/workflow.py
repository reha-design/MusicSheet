"""Stage workflow contract."""

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Protocol

from celery import chain

from musicsheet_common import PipelineStage
from musicsheet_api.jobs.artifacts import ArtifactRecord
from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.pipeline.celery_app import celery_app

STAGE_TASK_NAMES = (
    "download_source", "preprocess_audio", "separate_audio", "transcribe_amt",
    "quantize_and_score", "render_pdf",
)
STAGE_QUEUES = (
    "cpu_io_queue", "cpu_io_queue", "gpu_ai_queue", "gpu_ai_queue",
    "cpu_render_queue", "cpu_render_queue",
)
STAGES = tuple(PipelineStage)


@dataclass(frozen=True)
class StageContext:
    job: JobRecord
    stage: PipelineStage
    artifacts: tuple[ArtifactRecord, ...]

    @property
    def idempotency_key(self) -> tuple[str, PipelineStage]:
        return self.job.id, self.stage


class StageHandler(Protocol):
    """A re-entrant stage implementation supplied by W04–W08."""

    def run(self, context: StageContext, report_progress: Callable[[int], None]) -> None: ...


class StageError(Exception):
    """Stable code only; driver details must not reach job rows or events."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("stage error code must be a stable uppercase identifier")
        super().__init__(code)
        self.code = code


class RetryableStageError(StageError):
    pass


class PermanentStageError(StageError):
    pass


class JobCancellationRequested(Exception):
    pass


def build_stage_chain(job_id: str):
    """Use immutable signatures so every broker message carries only job_id."""
    return chain(*(
        celery_app.signature(f"musicsheet.pipeline.{name}", args=(job_id,), immutable=True,
                             queue=queue)
        for name, queue in zip(STAGE_TASK_NAMES, STAGE_QUEUES, strict=True)
    ))


def overall_progress(stage: PipelineStage, stage_progress: int) -> int:
    if type(stage_progress) is not int or not 0 <= stage_progress <= 100:
        raise ValueError("stage_progress must be an integer from 0 to 100")
    return (STAGES.index(stage) * 100 + stage_progress) // len(STAGES)
