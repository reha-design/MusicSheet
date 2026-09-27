"""Typed job row returned by the persistence layer."""

from dataclasses import dataclass
from datetime import datetime

from musicsheet_common import JobStatus, PipelineStage


@dataclass(frozen=True)
class JobRecord:
    id: str
    user_id: str | None
    source_type: str
    source_url: str | None
    target_instrument: str | None
    status: JobStatus
    current_stage: PipelineStage
    stage_progress: int | None
    overall_progress: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None
