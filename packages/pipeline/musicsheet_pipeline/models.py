"""Internal PostgreSQL snapshots, separate from public HTTP schemas."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from musicsheet_common import JobStatus, PipelineStage, ArtifactRef
from .contracts import StageInput

TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED}


@dataclass(frozen=True)
class PipelineJob:
    id: str
    source_type: str
    source_url: str | None = field(repr=False)
    target_instrument: str | None
    status: JobStatus
    current_stage: PipelineStage
    stage_progress: int
    overall_progress: int
    active_attempt_id: str | None
    error_code: str | None
    error_message: str | None
    completed_at: datetime | None

    @classmethod
    def from_row(cls, row):
        values = {name: row[name] for name in cls.__dataclass_fields__}
        values["status"] = JobStatus(values["status"])
        values["current_stage"] = PipelineStage(values["current_stage"])
        values["stage_progress"] = values["stage_progress"] or 0
        values["overall_progress"] = values["overall_progress"] or 0
        return cls(**values)


@dataclass(frozen=True)
class Transition:
    job: PipelineJob
    changed: bool = True


@dataclass(frozen=True)
class PreparedStage:
    action: Literal["RUN", "DUPLICATE", "SKIP"]
    context: StageInput | None = None
    transition: Transition | None = None
    completed_outputs: tuple[ArtifactRef, ...] = ()
