# AI Spec: Automatic Music Transcription (AMT)

> **Canonical Owner:** `docs/ai/transcription.md`  
> **관련 문서:** [docs/domain/note-events.md](../domain/note-events.md), [docs/infrastructure/runtime.md](../infrastructure/runtime.md)

---

## 1. AMT 모델 비교 및 선정

| 모델 | 대상 악기 | 주요 특징 | 실행 방식 및 큐 |
| :--- | :--- | :--- | :--- |
| **ByteDance Piano AMT** (Kong et al.) | 피아노 전용 | 벨로시티·서스테인 페달 출력 후보. 실제 지원 범위는 동일한 fixture로 검증 필요 | Python·PyTorch·CUDA 조합 미확정. 호환성 검증 후 실행 환경과 큐 결정 |
| **Spotify Basic Pitch** | 범용 악기 / 피아노 | 다성부 전사와 pitch bend MIDI 출력. worker JSON note contract는 pitch bend detail을 보존하지 않음 | Windows Python 3.12 + ONNX CPU 독립 CLI PoC 검증 완료. upstream 공식 지원, API/Celery 연결, 기본 provider 채택은 별도 |

### 실행환경 경계

- 백엔드·API·공용 스키마는 루트 Python 3.13 uv workspace에 둡니다. 모델 추론 의존성은 필요한 경우 별도 uv 프로젝트와 프로세스로 격리합니다.
- Python·OS wheel·프레임워크·native library·CUDA 조합을 함께 검증한 모델끼리는 AI 실행환경을 공유할 수 있습니다. 모델마다 무조건 환경을 하나씩 만들지는 않습니다.
- Basic Pitch worker는 `services/ml/basic-pitch-worker`의 독립 Python 3.12 프로젝트에서 설치와 실제 추론을 검증했습니다. 22,050 Hz mono CC0 piano fixture 결과는 root Python 3.13 `TranscriptionResult`에서도 검증됐습니다. 재현 환경과 결과는 [Basic Pitch worker smoke 보고서](../reports/basic-pitch-worker-smoke-report.md)를 참조합니다.
- PR [#201](https://github.com/spotify/basic-pitch/pull/201)은 2026-09-26 확인 시 미병합이므로 이 PoC는 upstream의 공식 Python 3.12 지원을 의미하지 않습니다. Python 3.13 workspace나 기존 런타임 결정을 바꾸지 않습니다.
- 검증 범위는 독립 CLI, ONNX CPU 추론, version 1 JSON 및 MIDI 산출입니다. 정확도 benchmark, API/Celery pipeline 연동과 기본 provider 승격은 별도 작업/결정으로 남습니다. 2026-09-25 호환성 보고서는 PoC 전 평가이며 최신 실행 증거는 smoke 보고서에 있습니다.

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
- 모델의 추론 결과는 온셋, 오프셋, 모델별 activation 및 pitch로 수집되어 [docs/domain/note-events.md](../domain/note-events.md)의 `RawNoteEvent`로 직렬화된다. Activation은 보정된 확률이라고 검증되기 전까지 확률로 부르거나 해석하지 않는다.
- 페달을 실제로 출력하는 provider만 별도의 `PedalEvent`를 만든다. Basic Pitch는 별도 페달 출력을 확인하기 전까지 `supports_pedal=false`와 빈 페달 목록을 사용한다.
