from typing import Optional
from pydantic import BaseModel, Field

class SeparationQuality(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0, description="종합 분리 품질 점수")
    bleed_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    artifact_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    silence_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_solo_piano: bool = Field(False, description="피아노 솔로 감지 여부 (True 시 분리 Bypass 가능)")
