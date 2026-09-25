# Domain Spec: Note Events & 3-Tier Hierarchy

> **Canonical Owner:** `docs/domain/note-events.md`  
> **관련 문서:** [docs/domain/score-model.md](./score-model.md), [docs/ai/transcription.md](../ai/transcription.md)

---

## 1. 3계층 Note Event 아키텍처

AI 모델의 에러와 음악 기보/정제 알고리즘의 오류를 명확히 구분하고 역추적할 수 있도록 3단계로 엄격히 분리한다.

```text
[오디오]
   │
   ▼ AMT Model (ByteDance / Basic Pitch)
[RawNoteEvent] ── 순수 모델 출력 (연속 onset/offset, raw activation, pitch 0~127)
   │
   ▼ Dynamic Filter & Quality Check
[CleanNoteEvent] ── 유령 음표 제거, multi-stage confidence 누적, 플래그 부여
   │
   ▼ Smart Quantizer & Voice Split
[ScoreNote] ── Rational 박자/길이, 마디, 보표(Staff 1/2), 성부(Voice), 딴이름한소리
```

---

## 2. 계층별 스키마 정의

### 2.1 계층 1: `RawNoteEvent`
- **단일 진실 소스:** `duration`을 저장하지 않고 `onset_sec`와 `offset_sec`만 보존하여 모순을 방지한다.
- **피치 범위:** 0~127 (MIDI 전범위 허용, 악기별 제약은 Provider에서 검증).

```python
from typing import Optional
from pydantic import BaseModel, Field

class RawNoteEvent(BaseModel):
    note_id: str
    pitch: int = Field(..., ge=0, le=127)
    onset_sec: float = Field(..., ge=0.0)
    offset_sec: float = Field(..., ge=0.0)
    activation: Optional[float] = None
    velocity_prediction: Optional[float] = None
    amt_confidence: float = Field(..., ge=0.0, le=1.0)
    source_chunk: Optional[int] = None

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.offset_sec - self.onset_sec)
```

### 2.2 계층 2: `CleanNoteEvent`
- 피아노 솔로/분리 품질 점수와 리듬 적합도를 결합한 종합 Confidence를 유지한다.

```python
from typing import List, Optional
from pydantic import BaseModel, Field

class ConfidenceScores(BaseModel):
    amt: float
    separation_quality: Optional[float] = None
    rhythm_fit: Optional[float] = None
    final: float

class CleanNoteEvent(BaseModel):
    note_id: str
    pitch: int = Field(..., ge=0, le=127)
    onset_sec: float = Field(..., ge=0.0)
    offset_sec: float = Field(..., ge=0.0)
    velocity: int = Field(default=80, ge=1, le=127)
    confidence: ConfidenceScores
    flags: List[str] = Field(default_factory=list) # e.g., ['staccato', 'low_confidence', 'grace_candidate']

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.offset_sec - self.onset_sec)
```

### 2.3 서스테인 페달: `PedalEvent`
- 서스테인 페달(CC 64)은 음표가 아닌 별도의 Control Event로 분리 관리한다.

```python
from typing import Literal
from pydantic import BaseModel, Field

class PedalEvent(BaseModel):
    event_type: Literal["sustain", "soft", "sostenuto"] = "sustain"
    onset_sec: float
    offset_sec: float
    value: int = Field(127, ge=0, le=127) # MIDI CC 값
```
