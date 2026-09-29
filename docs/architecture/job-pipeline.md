# Architecture Spec: Job Pipeline & Queue Routing

> **Canonical Owner:** `docs/architecture/job-pipeline.md`  
> **관련 문서:** [docs/domain/job-state.md](../domain/job-state.md), [docs/backend/celery.md](../backend/celery.md)
>
> **구현 상태:** W03가 등록·상태 저장·Celery queue/chain orchestration을 구현했습니다. 각 단계의 실제 파일 다운로드, 오디오 변환, 모델 추론 및 렌더링 handler는 W04–W08에서 구현합니다. 현재 handler가 없는 단계는 완료 처리하지 않고 `STAGE_NOT_CONFIGURED`로 실패합니다.

---

## 1. 파이프라인 단계 및 워커 큐 매핑

GPU(RTX 3060 12GB)가 YouTube 다운로드나 PDF 렌더링 같은 CPU/Network 바운드 작업으로 인해 블로킹되는 현상을 방지하기 위해 큐를 물리적으로 분리한다.

아래 단계 설명은 목표 product data flow입니다. W03의 현재 구현은 stage task, queue routing, PostgreSQL lifecycle을 제공하며 실제 단계 handler는 후속 W04–W08 작업에서 등록합니다.

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

큐는 작업의 논리적 라우팅과 자원 동시성 정책을 나타내며 Python 환경을 결정하지 않는다. 큐를 처리하는 backend consumer는 검증된 in-process provider를 호출하거나, 다른 런타임이 필요한 모델의 독립 worker를 프로세스 계약으로 실행한다. 모델 package를 Python 3.13 backend에 설치하는 것은 해당 조합을 검증한 뒤에만 허용한다.

### 구현 모듈

Celery 앱과 queue 설정은 `services/api/src/musicsheet_api/pipeline/celery_app.py`, dispatcher는 `pipeline/dispatcher.py`, immutable six-stage chain과 handler protocol은 `pipeline/workflow.py`, task 실행은 `pipeline/tasks.py`, stale-job 운영 명령은 `pipeline/maintenance.py`에 있습니다. API는 job과 upload artifact commit 이후 `start_job(job_id)`를 발행합니다. Broker, result backend, SSE event Streams는 각각 Redis DB `/0`, `/1`, `/2`를 사용합니다. Visibility timeout 기본값은 `CELERY_VISIBILITY_TIMEOUT=3600`초이며, 자세한 worker 설정은 [Celery 명세](../backend/celery.md)를 따릅니다.

---

## 3. 멱등성 및 장애 복구 원칙

1. **태스크 재진입성:** 모든 Celery 태스크는 `acks_late=True`로 동작하며, 재실행되어도 동일한 결과 아티팩트를 덮어쓰거나 이미 유효한 아티팩트가 존재하면 연산을 건너뛴다.
2. **협력적 취소(Cooperative Cancellation):** 사용자가 작업 취소를 요청하면 `JobStatus`가 `CANCEL_REQUESTED`로 변경되며, 다음 Stage 진입 전 또는 긴 추론 루프 사이에서 워커가 이를 감지하여 안전하게 `CANCELED` 상태로 종료한다.
3. **Attempt 이력:** 각 단계 실행은 PostgreSQL `stage_attempts`에 기록합니다. job row transaction에서 단계/status를 비교한 뒤 attempt를 생성하며, 완료/실패 시 attempt 종료와 job 상태 변경을 같은 transaction에서 수행합니다.
4. **W03 재진입성 경계:** Worker delivery는 at-least-once입니다. 각 handler는 안정적인 `(job_id, stage)` key와 artifact SHA-256을 기준으로 기존 유효 출력을 확인해야 합니다. W04–W08 검증은 출력 파일 또는 외부 효과가 생성된 다음 attempt/job 완료가 PostgreSQL에 기록되기 전에 process가 종료되는 경우, 재전달이 중복 결과나 잘못된 완료를 만들지 않는지 확인합니다.
5. **Stale 작업 운영 복구:** claim transaction 전 worker loss는 durable attempt counter를 올리지 않을 수 있습니다. 내부 `musicsheet-orchestration-maintenance scan`은 `updated_at`이 visibility timeout의 두 배 이상 오래된 nonterminal job을 찾습니다. 운영자는 실제 worker가 비활성임을 확인하고 scan에서 관찰한 timestamp/status를 전달해 guarded recovery를 실행합니다. Recovery는 시작·현재 단계 advisory lock을 nonblocking으로 얻고 job row에서 관찰값과 age를 재확인하며, 열린 attempt와 job 상태를 한 transaction으로 처리합니다. 활성 lock 또는 변경된 snapshot이면 쓰기를 거부하고 재조회하도록 안내합니다. 상세 절차는 [Celery 운영 복구 절차](../backend/celery.md#4-pre-claim-worker-loss-운영-복구)에 있습니다.
