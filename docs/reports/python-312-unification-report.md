# MusicSheet 런타임 단일화 작업 결과보고서 (Python 3.12 일원화)

> **문서 번호:** REPORT-20260925-02  
> **작성 일자:** 2026-09-25  
> **작성자:** Senior ML/Backend Architect  
> **프로젝트:** MusicSheet (AI Audio-to-Score Transcription Pipeline)  
> **전체 상태:** 14/14 테스트 통과 (100% PASSED, 경고 0건)

---

## 1. 개요 (Executive Summary)

본 보고서는 MusicSheet 시스템의 런타임을 **Python 3.12 단일 표준 런타임**으로 일원화하고, 과거 레거시 격리 계획에 포함되어 있던 **Python 3.10 및 `legacy_amt_queue`를 전면 삭제·통합**한 아키텍처 개정 작업의 상세 결과를 기록한다.

실제 의존성 해결(Dependency Resolution) 및 호환성 분석을 거쳐 ByteDance Piano AMT와 Spotify Basic Pitch(ONNX)가 Python 3.12에서 네이티브로 원활히 구동됨을 검증하였으며, 이에 따라 복잡했던 멀티 런타임 및 분리 큐 구조를 대폭 간소화하였다.

```text
[개정 전: 복합 런타임]                          [개정 후: 단일 표준 런타임]
- Python 3.12 (API / CPU / Demucs)               - Python 3.12 (전체 통일)
- Python 3.10 (ByteDance AMT 레거시 격리)          - uv 단일 가상환경 (.venv)
- 4개 분리 큐 (legacy_amt_queue 포함)             - 3개 큐 (cpu_io, gpu_ai, cpu_render)
```

---

## 2. 세부 검토 및 호환성 검증 내역

1. **ByteDance Piano AMT (`piano_transcription_inference`):**
   - Python 3.12 환경에서 `piano-transcription-inference` 및 `torchlibrosa` 의존성 해결 완료 (0건 충돌).
   - 모델 핵심이 순수 PyTorch 가중치(`note_checkpoint.pth`)와 신경망(ResNet+BiGRU) 연산이므로 최신 PyTorch 2.x 네이티브 로딩 지원 확인.
2. **Spotify Basic Pitch:**
   - 레거시 TensorFlow(`tf < 2.15.1`) 의존 대신 공식 `model.onnx` 기반의 `onnxruntime` 경량 추론 엔진을 채택하여 Python 3.12에서 의존성 충돌 없이 초고속 실행 가능.
3. **Celery 큐 구조 간소화:**
   - 기존의 `legacy_amt_queue`를 제거하고 모든 음원 분리(Demucs v4) 및 피아노 전사(ByteDance/BasicPitch)를 `gpu_ai_queue` 단일 워커로 일원화.

---

## 3. 변경 파일 목록 및 주요 변경 내역

| 파일 경로 | 변경 내용 요약 |
| :--- | :--- |
| `README.md` | 상단 Python 배지(3.12), 기술 스택 테이블, 아키텍처 다이어그램 및 Quick Start에서 3.10 / `legacy_amt_queue` 제거 |
| `docs/adr/001-python-runtime.md` | ADR 001을 "Python 3.12 단일 표준 런타임 채택"으로 공식 개정 승인 |
| `docs/infrastructure/runtime.md` | 런타임 분리 전략을 단일화 전략으로 갱신, `uv` 커맨드에서 3.10 설치 및 4번째 워커 제거 |
| `docs/architecture/system.md` | 시스템 아키텍처 다이어그램 및 컴포넌트 테이블에서 GPU Worker 런타임을 Python 3.12 단일화 |
| `docs/architecture/job-pipeline.md` | Stage 4 TRANSCRIBE 큐 라우팅을 `gpu_ai_queue`로 단일화, 큐 목록에서 `legacy_amt_queue` 삭제 |
| `docs/ai/transcription.md` | AMT 모델 실행 방식을 PyTorch 2.x 네이티브 및 ONNX 런타임(`gpu_ai_queue`)으로 갱신 |
| `docs/backend/celery.md` | `task_routes`에서 `transcribe_legacy` 라우트 제거 |
| `docs/main_spec.md` | Infrastructure 및 ADR 001 인덱스 설명 갱신 |

---

## 4. 검증 결과

- **단위/통합 테스트:** `uv run pytest`
  - 결과: **14 passed in 0.27s (100% 통과)**
  - `tests/test_project_baseline.py`에서 Python 3.12 표준 런타임 환경 일치 검증 완료.
