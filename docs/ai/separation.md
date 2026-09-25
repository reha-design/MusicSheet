# AI Spec: Source Separation & Quality Check

> **Canonical Owner:** `docs/ai/separation.md`  
> **관련 문서:** [docs/ai/model-adapters.md](./model-adapters.md), [docs/domain/artifacts.md](../domain/artifacts.md)

---

## 1. 음원 분리 모델: Meta Demucs v4 (`htdemucs_6s`)

- **타겟 스템:** Drums, Bass, Other, Vocals, Guitar, **Piano**
- **입력 규격:** 44.1kHz Stereo WAV (`separator_input.wav`)
- **VRAM 소모:** 약 3.5GB (FP16 추론, 12GB 환경에서 여유 있게 동작)
- **주의점:** Meta Demucs 저장소는 아카이빙 상태이므로, 시스템에 영구 결속하지 않고 `AudioSeparator` 인터페이스 뒤에 배치한다.

---

## 2. Separation QC & Solo Piano Bypass 전략

음원 분리 모델을 무조건 거치면 아티팩트와 출혈음(Bleeding)이 발생하여 피아노 단독 연주의 경우 오히려 전사 품질이 악화된다.

```text
[입력 음원]
    │
    ▼ Solo Piano 판별 & QC 분석
[Separation Quality Check]
    │
    ├─► [PASS: 피아노 솔로 감지 / 높은 신뢰도] ──► Demucs 생략 (Bypass: 원본 ➔ AMT)
    │
    └─► [LOW CONF / 혼합 밴드 음원] ────────► Demucs 6s 분리 실행 ➔ Piano Stem
```

### Quality Check 스키마
```python
from typing import Optional
from pydantic import BaseModel, Field

class SeparationQuality(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0, description="종합 품질 점수")
    bleed_score: Optional[float] = None
    artifact_score: Optional[float] = None
    silence_ratio: Optional[float] = None
    is_solo_piano: bool = False
```
