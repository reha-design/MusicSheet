"""Internal PostgreSQL snapshots, separate from public HTTP schemas."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

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


def validate_stale_seconds(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("Invalid stale duration")


@dataclass(frozen=True)
class JobObservation:
    job_id: str
    status: JobStatus
    current_stage: PipelineStage
    updated_at: datetime
    active_attempt_id: str | None

    def __post_init__(self):
        try:
            for name in ("job_id", "active_attempt_id"):
                value = getattr(self, name)
                if value is None and name == "active_attempt_id":
                    continue
                if not isinstance(value, (str, UUID)):
                    raise ValueError
                object.__setattr__(self, name, str(UUID(str(value))))
            object.__setattr__(self, "status", JobStatus(self.status))
            object.__setattr__(self, "current_stage", PipelineStage(self.current_stage))
            if not isinstance(self.updated_at, datetime) or self.updated_at.utcoffset() is None:
                raise ValueError
        except Exception:
            raise ValueError("Invalid job observation") from None

    def to_dict(self):
        return dict(job_id=self.job_id, status=self.status.value,
                    current_stage=self.current_stage.value, updated_at=self.updated_at.isoformat(),
                    active_attempt_id=self.active_attempt_id)


@dataclass(frozen=True)
class AttemptSummary:
    stage: str
    attempt: int
    generation: int
    status: str
    error_code: str | None


@dataclass(frozen=True)
class StalledJob:
    observation: JobObservation
    latest_attempt: AttemptSummary | None

    @classmethod
    def from_row(cls, row):
        observation = JobObservation(row["id"], row["status"], row["current_stage"],
                                     row["updated_at"], row["active_attempt_id"])
        latest = None if row["latest_stage"] is None else AttemptSummary(
            *(row["latest_"+name] for name in AttemptSummary.__dataclass_fields__))
        return cls(observation, latest)

    def to_dict(self):
        from dataclasses import asdict
        return dict(self.observation.to_dict(), latest_attempt=asdict(self.latest_attempt) if self.latest_attempt else None)


@dataclass(frozen=True)
class RecoveryResult:
    changed: bool
    reason: Literal["CHANGED", "LOCK_HELD", "NOT_FOUND", "NOT_ELIGIBLE", "OBSERVATION_CHANGED", "NOT_STALE"]
    transition: Transition | None = None
