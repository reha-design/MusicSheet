"""Public request and response models for job endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from musicsheet_common import ArtifactRole, JobStatus, PipelineStage


class YouTubeJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1, max_length=2048)
    target_instrument: Literal["piano"] = "piano"


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: Literal["YOUTUBE", "UPLOAD"]
    source_url: str | None
    target_instrument: str | None
    status: JobStatus
    current_stage: PipelineStage
    stage_progress: int | None
    overall_progress: int | None
    error_code: str | None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    role: ArtifactRole
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    producer: str | None
    producer_version: str | None
    created_at: datetime | None
    download_url: str
