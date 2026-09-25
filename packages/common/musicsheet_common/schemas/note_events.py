from typing import List, Literal, Optional
from pydantic import BaseModel, Field

class RawNoteEvent(BaseModel):
    note_id: str
    pitch: int = Field(..., ge=0, le=127, description="MIDI Pitch (0~127)")
    onset_sec: float = Field(..., ge=0.0, description="시작 시점 (초)")
    offset_sec: float = Field(..., ge=0.0, description="종료 시점 (초)")
    activation: Optional[float] = Field(None, ge=0.0, le=1.0)
    velocity_prediction: Optional[float] = Field(None, ge=0.0, le=127.0)
    amt_confidence: float = Field(..., ge=0.0, le=1.0)
    source_chunk: Optional[int] = None

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.offset_sec - self.onset_sec)

class ConfidenceScores(BaseModel):
    amt: float = Field(..., ge=0.0, le=1.0)
    separation_quality: Optional[float] = Field(None, ge=0.0, le=1.0)
    rhythm_fit: Optional[float] = Field(None, ge=0.0, le=1.0)
    final: float = Field(..., ge=0.0, le=1.0)

class CleanNoteEvent(BaseModel):
    note_id: str
    pitch: int = Field(..., ge=0, le=127)
    onset_sec: float = Field(..., ge=0.0)
    offset_sec: float = Field(..., ge=0.0)
    velocity: int = Field(default=80, ge=1, le=127)
    confidence: ConfidenceScores
    flags: List[str] = Field(default_factory=list)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.offset_sec - self.onset_sec)

class PedalEvent(BaseModel):
    event_type: Literal["sustain", "soft", "sostenuto"] = "sustain"
    onset_sec: float = Field(..., ge=0.0)
    offset_sec: float = Field(..., ge=0.0)
    value: int = Field(127, ge=0, le=127)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.offset_sec - self.onset_sec)
