from typing import Literal, Optional
from pydantic import BaseModel, Field

class ScoreNote(BaseModel):
    note_id: str
    pitch: int = Field(..., ge=0, le=127, description="MIDI Pitch (0~127)")
    measure: int = Field(..., ge=1, description="마디 번호 (1-based)")
    
    # 마디 시작점 기준 박자 위치 (유리수: 0/1 = 1박, 1/2 = 2분음표 위치)
    beat_numerator: int = Field(..., ge=0)
    beat_denominator: int = Field(..., ge=1)
    
    # 음표 길이 (유리수: 1/4 = 4분음표, 1/16 = 16분음표, 1/12 = 8분셋잇단음표)
    duration_numerator: int = Field(..., ge=1)
    duration_denominator: int = Field(..., ge=1)
    
    staff: int = Field(1, ge=1, le=2, description="1: Treble (높은음자리), 2: Bass (낮은음자리)")
    voice: int = Field(1, ge=1, description="Staff 내 Polyphonic 성부 (1, 2, ...)")
    hand: Optional[Literal["left", "right"]] = None
    
    tie_start: bool = False
    tie_stop: bool = False
    enharmonic_spelling: Optional[str] = None
