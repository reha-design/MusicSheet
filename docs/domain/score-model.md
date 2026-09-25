# Domain Spec: Score Model & Notation Representation

> **Canonical Owner:** `docs/domain/score-model.md`  
> **관련 문서:** [docs/domain/note-events.md](./note-events.md), [docs/ai/quantization.md](../ai/quantization.md)

---

## 1. `ScoreNote` 명세 (계층 3)

문자열(예: `"16th"`) 대신 **유리수(Rational Number)**를 사용하여 셋잇단음표, 복합 박자 및 정밀한 악보 기보를 지원한다.

```python
from typing import Optional, Literal
from pydantic import BaseModel, Field

class ScoreNote(BaseModel):
    note_id: str
    pitch: int = Field(..., ge=0, le=127)
    measure: int = Field(..., ge=1, description="마디 번호")
    
    # 마디 시작점 기준 박자 위치 (유리수: 0/1 = 1박, 1/2 = 2분음표 위치)
    beat_numerator: int
    beat_denominator: int
    
    # 음표 길이 (유리수: 1/4 = 4분음표, 1/16 = 16분음표, 1/12 = 8분셋잇단음표)
    duration_numerator: int
    duration_denominator: int
    
    # 보표 및 성부 분리
    staff: int = Field(1, description="1: Treble (높은음자리), 2: Bass (낮은음자리)")
    voice: int = Field(1, description="Staff 내 Polyphonic 성부 (1, 2, ...)")
    hand: Optional[Literal["left", "right"]] = None
    
    # 타이(Tie) 연결 여부
    tie_start: bool = False
    tie_stop: bool = False
    
    # 조표(Key) 맥락에 따른 딴이름한소리 표기 (예: C#4 vs Db4)
    enharmonic_spelling: Optional[str] = None
```

---

## 2. Staff vs Voice vs Hand 원칙

- **Staff (보표):** 피아노의 큰보표(Grand Staff)에서 1은 높은음자리표(Treble), 2는 낮은음자리표(Bass)를 의미한다.
- **Voice (성부):** 동일한 Staff 안에서도 동시에 진행되는 서로 다른 리듬 라인을 표현하기 위해 1, 2 등으로 분리한다.
- **Hand (손):** 연주자의 왼손/오른손을 나타내며, 필요 시 보표 간 교차 연주(Cross-staff) 표현에 활용된다.
- **Enharmonic Spelling:** 원시 피치(61)는 사전에 고정하지 않고, 조표(Key Context) 분석 결과에 따라 C#4 또는 Db4로 기보 단계에서 결정한다.
