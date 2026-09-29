"""Observable contracts for the Celery stage chain and handler boundary."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.pipeline.workflow import (
    STAGE_TASK_NAMES,
    PermanentStageError,
    RetryableStageError,
    StageContext,
    build_stage_chain,
    overall_progress,
)


def test_stage_chain_has_six_immutable_job_id_only_signatures_on_named_queues() -> None:
    workflow = build_stage_chain("job-123")

    assert [signature.task for signature in workflow.tasks] == [
        "musicsheet.pipeline.download_source",
        "musicsheet.pipeline.preprocess_audio",
        "musicsheet.pipeline.separate_audio",
        "musicsheet.pipeline.transcribe_amt",
        "musicsheet.pipeline.quantize_and_score",
        "musicsheet.pipeline.render_pdf",
    ]
    assert [signature.options["queue"] for signature in workflow.tasks] == [
        "cpu_io_queue", "cpu_io_queue", "gpu_ai_queue", "gpu_ai_queue",
        "cpu_render_queue", "cpu_render_queue",
    ]
    assert all(signature.args == ("job-123",) and signature.kwargs == {} for signature in workflow.tasks)
    assert all(signature.immutable for signature in workflow.tasks)
    assert len(STAGE_TASK_NAMES) == 6


@pytest.mark.parametrize(
    ("stage", "stage_progress", "expected"),
    [
        (PipelineStage.DOWNLOAD, 0, 0),
        (PipelineStage.DOWNLOAD, 100, 16),
        (PipelineStage.PREPROCESS, 50, 25),
        (PipelineStage.SEPARATE, 100, 50),
        (PipelineStage.TRANSCRIBE, 50, 58),
        (PipelineStage.POSTPROCESS, 100, 83),
        (PipelineStage.RENDER, 100, 100),
    ],
)
def test_overall_progress_uses_equal_stage_weights(stage, stage_progress, expected) -> None:
    assert overall_progress(stage, stage_progress) == expected


@pytest.mark.parametrize("invalid", [-1, 101, 10.5, True, "10"])
def test_overall_progress_rejects_noninteger_or_out_of_range(invalid) -> None:
    with pytest.raises(ValueError):
        overall_progress(PipelineStage.DOWNLOAD, invalid)


def test_stage_context_exposes_stable_operation_key_and_persisted_records() -> None:
    now = datetime.now(timezone.utc)
    job = JobRecord(
        "job-123", None, "UPLOAD", None, "piano", JobStatus.RUNNING,
        PipelineStage.DOWNLOAD, 0, 0, None, None, now, now, None,
    )
    context = StageContext(job=job, stage=PipelineStage.DOWNLOAD, artifacts=())

    assert context.idempotency_key == ("job-123", PipelineStage.DOWNLOAD)
    assert context.job is job
    assert context.artifacts == ()


@pytest.mark.parametrize("exception", [PermanentStageError, RetryableStageError])
@pytest.mark.parametrize("code", ["", "driver password=secret", "BAD-CODE", "X" * 65])
def test_handler_error_codes_must_be_stable_public_identifiers(exception, code) -> None:
    with pytest.raises(ValueError):
        exception(code)
