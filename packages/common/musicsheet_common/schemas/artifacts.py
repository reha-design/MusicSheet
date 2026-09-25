from enum import Enum
from pydantic import BaseModel, Field

class ArtifactRole(str, Enum):
    SOURCE_ORIGINAL = "SOURCE_ORIGINAL"
    CANONICAL_AUDIO = "CANONICAL_AUDIO"
    MODEL_INPUT = "MODEL_INPUT"
    SEPARATED_AUDIO = "SEPARATED_AUDIO"
    RAW_TRANSCRIPTION = "RAW_TRANSCRIPTION"
    CLEANED_TRANSCRIPTION = "CLEANED_TRANSCRIPTION"
    QUANTIZED_SCORE = "QUANTIZED_SCORE"
    CONTROL_EVENTS = "CONTROL_EVENTS"
    MIDI = "MIDI"
    MUSICXML = "MUSICXML"
    PDF = "PDF"

class ArtifactRef(BaseModel):
    id: str
    job_id: str
    role: ArtifactRole
    filename: str
    uri: str
    mime_type: str
    size_bytes: int = Field(..., ge=0)
    sha256: str = Field(..., min_length=64, max_length=64, description="SHA-256 해시 (64자)")
    producer: str
    producer_version: str
