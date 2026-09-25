from typing import List
from pydantic import BaseModel, Field

class TempoEvent(BaseModel):
    time_sec: float = Field(..., ge=0.0)
    bpm: float = Field(..., gt=0.0)

class MeterEvent(BaseModel):
    time_sec: float = Field(..., ge=0.0)
    numerator: int = Field(..., ge=1)
    denominator: int = Field(..., ge=1)

class BeatGrid(BaseModel):
    beats: List[float] = Field(default_factory=list, description="비트 시작 시점 (초)")
    downbeats: List[float] = Field(default_factory=list, description="마디 첫 박 (다운비트) 시작 시점 (초)")
    tempo_map: List[TempoEvent] = Field(default_factory=list)
    meter_map: List[MeterEvent] = Field(default_factory=list)
