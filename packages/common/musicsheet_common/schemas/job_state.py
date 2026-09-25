from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"

class PipelineStage(str, Enum):
    DOWNLOAD = "DOWNLOAD"
    PREPROCESS = "PREPROCESS"
    SEPARATE = "SEPARATE"
    TRANSCRIBE = "TRANSCRIBE"
    POSTPROCESS = "POSTPROCESS"
    RENDER = "RENDER"

class JobProgressEvent(BaseModel):
    job_id: str
    status: JobStatus
    stage: PipelineStage
    stage_progress: int = Field(..., ge=0, le=100, description="단계별 진행률 (0~100)")
    overall_progress: int = Field(..., ge=0, le=100, description="전체 진행률 (0~100)")
    message: str = Field(..., description="사용자 노출용 안내 메시지")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
