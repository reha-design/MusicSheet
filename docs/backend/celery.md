# Backend Spec: Celery Orchestration

> **Canonical Owner:** `docs/backend/celery.md`  
> **관련 문서:** [docs/architecture/job-pipeline.md](../architecture/job-pipeline.md)
>
> **구현 상태:** W03 오케스트레이션은 `services/api/src/musicsheet_api/pipeline/`에 구현되어 있습니다. 실제 미디어·모델·렌더 핸들러는 W04–W08 범위이며, 아직 등록되지 않은 핸들러는 `STAGE_NOT_CONFIGURED`로 실패합니다. Redis Streams 이벤트 저장소는 `REDIS_URL`의 DB `/2`, Celery 브로커는 DB `/0`, 결과 backend는 DB `/1`을 사용합니다. [Redis 이벤트 명세](./redis-streams.md)를 참조하세요.

---

## 1. Celery 기본 설정

`services/api/src/musicsheet_api/pipeline/celery_app.py`의 `create_celery_app()`은 import 시 broker 연결을 열지 않습니다. 설정 기본값은 `CELERY_BROKER_URL=redis://localhost:6379/0`, `CELERY_RESULT_BACKEND=redis://localhost:6379/1`, `REDIS_URL=redis://localhost:6379/2`, `CELERY_VISIBILITY_TIMEOUT=3600`초입니다. 명시된 환경변수는 기본값을 덮어씁니다. Redis DB 분리는 Celery 메시지와 SSE 이벤트 키를 서로 격리합니다.

W03는 `musicsheet_api.pipeline.tasks`에 `musicsheet.pipeline.start_job`과 여섯 단계 task를 등록합니다. API는 DB commit 후 job ID만 발행하고, Celery chain은 immutable task signature를 사용합니다. PostgreSQL이 작업 상태와 attempt 이력의 기준입니다. Celery result backend 값은 작업 상태로 사용하지 않습니다.

---

## 2. 큐, 순서 및 실행 명령

| 순서 | Celery task | 단계 | Queue | 권장 concurrency |
| ---: | --- | --- | --- | ---: |
| 시작 | `musicsheet.pipeline.start_job` | workflow 발행 | `cpu_io_queue` | 4–8 |
| 1 | `musicsheet.pipeline.download_source` | `DOWNLOAD` | `cpu_io_queue` | 4–8 |
| 2 | `musicsheet.pipeline.preprocess_audio` | `PREPROCESS` | `cpu_io_queue` | 4–8 |
| 3 | `musicsheet.pipeline.separate_audio` | `SEPARATE` | `gpu_ai_queue` | 1 |
| 4 | `musicsheet.pipeline.transcribe_amt` | `TRANSCRIBE` | `gpu_ai_queue` | 1 |
| 5 | `musicsheet.pipeline.quantize_and_score` | `POSTPROCESS` | `cpu_render_queue` | 2–4 |
| 6 | `musicsheet.pipeline.render_pdf` | `RENDER` | `cpu_render_queue` | 2–4 |

세 queue에 worker를 각각 띄우려면 `services/api`에서 Python 3.13 환경과 Redis/PostgreSQL 설정을 준비하고, worker 시작 전에 migration을 적용합니다.

```powershell
uv run --locked --python 3.13 musicsheet-migrate
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q cpu_io_queue -c 4 -l info
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q gpu_ai_queue -c 1 -l info
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q cpu_render_queue -c 2 -l info
```

`cpu_io_queue`는 4–8, `gpu_ai_queue`는 1, `cpu_render_queue`는 2–4 concurrency를 사용합니다. 명령 예시는 각 queue에서 각각 4, 1, 2로 시작합니다. 모델 런타임이나 긴 실제 단계가 추가되면 GPU 자원과 `CELERY_VISIBILITY_TIMEOUT`을 운영 환경에 맞게 조정합니다.

## 3. 상태, 재시도 및 취소

- 각 단계는 PostgreSQL에서 예상 상태와 단계가 일치할 때만 attempt를 claim하고 handler를 호출합니다. attempt는 `RUNNING`, `COMPLETED`, `FAILED`를 기록하고, 한 단계는 최대 네 번 실행됩니다. transient 오류는 exponential backoff, 최대 60초, jitter를 사용하며 네 번째 실패는 `RETRY_EXHAUSTED`로 종료합니다. worker-loss 재전달도 같은 영속 attempt 한도를 사용합니다.
- `start_job`은 `start_job_attempts`를 PostgreSQL에 먼저 commit한 뒤 chain을 발행하며, workflow 발행 claim은 최대 네 번입니다. 네 번 모두 발행 timestamp나 stage attempt를 기록하지 못하면 후속 전달은 `FAILED/WORKFLOW_WORKER_LOST`로 끝납니다. Broker가 메시지를 수락한 직후 worker가 timestamp commit 전에 죽어 chain이 중복 발행될 수 있으므로 단계 advisory lock과 guarded stage claim이 중복 side effect를 막습니다.
- `task_acks_late`와 `task_reject_on_worker_lost`가 켜져 있습니다. job/stage별 PostgreSQL session advisory lock으로 중복 실행은 기다리게 하고, lock을 얻은 뒤 job 상태를 다시 확인합니다. 완료·취소·실패된 job 또는 이미 지나간 단계는 부작용 없이 종료됩니다.
- 단계 완료와 다음 `current_stage`는 Celery가 successor callback을 발행하기 전에 PostgreSQL에 함께 commit됩니다. 이 구간에서 worker가 죽고 완료된 이전 단계가 재전달되면, 저장된 attempt가 `COMPLETED`이고 job이 더 뒤의 비terminal 단계에 있을 때 handler는 재실행하지 않고 task를 정상 반환해 Celery가 남은 chain을 이어가게 합니다. terminal/missing job이나 완료 근거가 없는 상태는 no-op으로 callback을 멈춥니다. 인식된 PostgreSQL 연결·pool 오류는 stage/start claim과 완료 저장을 포함한 task 경계에서 typed Celery retry로 전달되고, task `max_retries=None`, exponential backoff, 최대 60초, jitter를 사용합니다. 이 task 전달 재시도 횟수는 PostgreSQL의 실행 한도와 별개입니다. durable stage/start claim 전의 DB 장애는 계속 재시도될 수 있고 persisted claim counter를 올리지 않습니다. claim 이후에는 stage와 start task 각각 PostgreSQL의 기존 4회 실행 한도를 사용하며, pre-claim 재시도와 DB 복구 운영은 아래 runbook을 따릅니다.
- 각 단계 시작과 긴 작업의 progress checkpoint에서 `CANCEL_REQUESTED`를 확인합니다. 취소 요청이 실패 전이에 먼저 commit되면 열린 attempt를 `FAILED/CANCELED`로 닫고 job을 `CANCELED`로 만듭니다. 이미 완료된 terminal 상태는 덮어쓰지 않습니다.
- Celery broker 연결/읽기 timeout은 2초이며 publish는 처음 한 번과 최대 세 번 재시도합니다. API 경로는 동기 publish를 thread에서 기다리고, 실패 시 `PENDING`만 `FAILED/DISPATCH_FAILED`로 compare-and-set합니다. API가 상태 저장에 실패하면 `503` 본문은 `{"detail":{"message":"Job dispatch status is unavailable","job_id":"<job-id>"}}` 형태이며, 호출자는 그 ID로 `GET /api/v1/jobs/{job_id}`를 조회합니다.
- 실행 핸들러가 아직 등록되지 않은 단계는 `PermanentStageError("STAGE_NOT_CONFIGURED")`로 실패합니다. W03는 queue/state orchestration만 제공하며 downloader, 전처리, AI inference, quantization, score renderer를 구현하거나 성공으로 가장하지 않습니다.

## 4. Pre-claim worker loss 운영 복구

task 경계에서 인식한 PostgreSQL 연결·pool 오류는 Celery가 unlimited task-level retry로 backoff하며 재시도합니다. 반복 장애는 영속 stage/start claim 수를 올리지 않으므로, DB 장애만으로는 아래 stale-job 복구를 실행하지 않습니다. 먼저 PostgreSQL 연결을 복구하고, 관련 Celery worker가 실행 중이지 않은지 확인한 다음 scan으로 실제 pre-claim worker loss를 식별합니다. 작업이 broker 전달 이후 PostgreSQL claim transaction이 commit되기 전에 worker를 잃으면 durable attempt counter가 증가하지 않아 Redis/Celery가 재전달을 반복할 수 있습니다. `services/api/src/musicsheet_api/pipeline/maintenance.py`의 `musicsheet-orchestration-maintenance scan`은 `updated_at`이 `2 × CELERY_VISIBILITY_TIMEOUT` 이상 오래된 nonterminal job을 안전한 요약 필드(job ID, status, stage, dispatch count, 최신 attempt)로 보여줍니다. 기본값에서는 기준이 2시간입니다. source URL/path, driver 오류 상세는 출력하지 않습니다.

운영자는 반복되는 Celery worker-loss 로그와 stale scan을 확인하고, 대상 job을 처리할 worker가 더는 실행 중이 아님을 먼저 확인한 뒤 그 scan 행을 골라 `fail-stalled`에 job ID, 관찰한 timestamp와 status를 그대로 넘깁니다. 쓰기 경로는 시작 task와 현재 단계의 PostgreSQL advisory lock을 nonblocking으로 얻고, job row lock 안에서 관찰 값과 stale 기준을 재검증합니다. lock이 잡혀 있거나 snapshot이 바뀌었거나 충분히 stale하지 않으면 쓰지 않고 다시 scan하도록 알립니다. 취소가 먼저 commit됐으면 `CANCELED`, 아니면 `FAILED/WORKER_PRECLAIM_STALLED`로 바꾸고 열린 attempt를 같은 transaction에서 닫은 뒤 terminal event를 best-effort 발행합니다. 뒤늦게 도착한 Celery delivery는 terminal job을 다시 읽고 acknowledge/no-op 합니다.

예를 들어 scan이 아래 값을 출력했다면 해당 값을 그대로 전달합니다.

```powershell
# scan row: job_id=550e8400-e29b-41d4-a716-446655440000, updated_at=2026-09-29T08:00:00+00:00, status=RUNNING
uv run --locked --python 3.13 musicsheet-orchestration-maintenance fail-stalled --job-id "550e8400-e29b-41d4-a716-446655440000" --observed-updated-at "2026-09-29T08:00:00+00:00" --observed-status "RUNNING"
```

W04–W08 handler 테스트는 출력 파일이나 외부 효과가 기록된 뒤 stage 완료 상태가 PostgreSQL에 저장되기 전에 worker가 죽는 경우를 반드시 포함해야 합니다. 재전달은 at-least-once이므로 `(job_id, stage)` idempotency key와 artifact SHA-256을 이용해 기존의 유효한 출력 결과를 재사용하고, 완료 전 출력 효과를 안전하게 반복·복구해야 합니다.
