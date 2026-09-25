# Architecture Spec: Job Pipeline & Queue Routing

> **Canonical Owner:** `docs/architecture/job-pipeline.md`  
> **관련 문서:** [docs/domain/job-state.md](../domain/job-state.md), [docs/backend/celery.md](../backend/celery.md)
>
> **구현 상태:** 목표 파이프라인 설계입니다. 현재 저장소에는 pipeline worker가 없습니다.

---

## 1. 파이프라인 단계 및 워커 큐 매핑

GPU(RTX 3060 12GB)가 YouTube 다운로드나 PDF 렌더링 같은 CPU/Network 바운드 작업으로 인해 블로킹되는 현상을 방지하기 위해 큐를 물리적으로 분리한다.

```text
[입력 요청]
   │
   ▼ (cpu_io_queue)
[Stage 1: DOWNLOAD] ── yt-dlp 또는 업로드 파일 검증
   │
   ▼ (cpu_io_queue)
[Stage 2: PREPROCESS] ── FFmpeg로 Canonical WAV (44.1kHz) 및 모델별 변환
   │
   ▼ (gpu_ai_queue)
[Stage 3: SEPARATE] ── Demucs v4 음원 분리 및 Solo Piano QC / Bypass 검사
   │
   ▼ (gpu_ai_queue)
[Stage 4: TRANSCRIBE] ── AMT 추론 (Raw Note Events & Pedal 추출)
   │
   ▼ (cpu_render_queue)
[Stage 5: POSTPROCESS] ── Beat Tracking, Dynamic Filter, Smart Quantization
   │
   ▼ (cpu_render_queue)
[Stage 6: RENDER] ── music21 악보화 및 MuseScore CLI PDF 렌더링
   │
[완료: COMPLETED]
```

---

## 2. 큐 상세 사양

| Queue 이름 | 담당 태스크 | Worker Concurrency | 자원 제약 |
| :--- | :--- | :--- | :--- |
| `cpu_io_queue` | `download_source`, `preprocess_audio` | 4~8 | Network I/O, 디스크 쓰기 |
| `gpu_ai_queue` | `separate_audio`, `transcribe_amt` (ByteDance / Basic Pitch) | 1 | CUDA VRAM (최대 12GB 안전 한도 유지) |
| `cpu_render_queue` | `quantize_and_score`, `render_pdf` | 2~4 | CPU Multi-core, 메모리 |

---

## 3. 멱등성 및 장애 복구 원칙

1. **태스크 재진입성:** 모든 Celery 태스크는 `acks_late=True`로 동작하며, 재실행되어도 동일한 결과 아티팩트를 덮어쓰거나 이미 유효한 아티팩트가 존재하면 연산을 건너뛴다.
2. **협력적 취소(Cooperative Cancellation):** 사용자가 작업 취소를 요청하면 `JobStatus`가 `CANCEL_REQUESTED`로 변경되며, 다음 Stage 진입 전 또는 긴 추론 루프 사이에서 워커가 이를 감지하여 안전하게 `CANCELED` 상태로 종료한다.
