# AI Spec: Rhythm & Beat Tracking

> **Canonical Owner:** `docs/ai/rhythm.md`  
> **관련 문서:** [docs/ai/quantization.md](./quantization.md), [docs/ai/model-adapters.md](./model-adapters.md)

---

## 1. 라이선스 전략 및 Provider 선정

- `madmom` 라이브러리는 학술적으로 우수하나 **CC BY-NC-SA 4.0** 상업적 라이선스 제한이 존재한다.
- 따라서 상업적 배포가 가능한 라이선스를 우선 채택한다:
  1. **1순위 Baseline:** `librosa.beat.beat_track` (ISC / MIT 계열, 완전 자유 라이선스)
  2. **2순위 Neural Tracker:** `Beat This!` (MIT License, 최신 신경망 기반 비트/다운비트 추적기)

---

## 2. 동적 `BeatGrid` 명세 (Rubato & 박자 변화 대응)

단일 고정 BPM으로 제한하지 않고, 템포 맵과 미터 맵을 배열로 관리하여 템포 루바토와 박자 변경을 유연하게 수용한다.

```python
from typing import List
from pydantic import BaseModel

class TempoEvent(BaseModel):
    time_sec: float
    bpm: float

class MeterEvent(BaseModel):
    time_sec: float
    numerator: int       # 예: 4, 3, 6
    denominator: int     # 예: 4, 8

class BeatGrid(BaseModel):
    beats: List[float]                  # 모든 비트 시작 초
    downbeats: List[float]              # 마디 첫 박(다운비트) 시작 초
    tempo_map: List[TempoEvent]         # 템포 변경 이벤트 리스트
    meter_map: List[MeterEvent]         # 박자표 변경 이벤트 리스트
```
