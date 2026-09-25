# AI Spec: Automatic Music Transcription (AMT)

> **Canonical Owner:** `docs/ai/transcription.md`  
> **관련 문서:** [docs/domain/note-events.md](../domain/note-events.md), [docs/infrastructure/runtime.md](../infrastructure/runtime.md)

---

## 1. AMT 모델 비교 및 선정

| 모델 | 대상 악기 | 주요 특징 | 권장 실행 런타임 |
| :--- | :--- | :--- | :--- |
| **ByteDance Piano AMT** (Kong et al.) | 피아노 전용 | SOTA급 화음 분해, 벨로시티 및 서스테인 페달 지원 | **Python 3.10 격리 런타임** (`legacy_amt_queue`) |
| **Spotify Basic Pitch** | 범용 악기 / 피아노 | 가볍고 빠름, 피치 벤딩 지원, 최신 환경 호환 | **Python 3.12 메인 런타임** (`gpu_ai_queue`) |

---

## 2. 모델별 입력 Sample Rate 처리

일괄 44.1kHz로 강제하지 않고, 모델이 요구하는 규격으로 개별 변환하여 불필요한 리샘플링 왜곡을 방지한다.

```text
Canonical Audio (44.1kHz Stereo)
  ├── Separator Input: 44.1kHz Stereo
  ├── ByteDance AMT Input: 16.0kHz Mono (`amt_16k_mono.wav`)
  └── Basic Pitch Input: 22.05kHz Mono (`amt_22k_mono.wav`)
```

---

## 3. 출력 데이터 처리
- 모델의 추론 결과는 온셋, 오프셋, 액티베이션 확률, 피아노 건반 번호(21~108)로 수집되어 [docs/domain/note-events.md](../domain/note-events.md)의 `RawNoteEvent`로 즉시 직렬화된다.
- 서스테인 페달 신호는 별도의 `PedalEvent`로 추출된다.
