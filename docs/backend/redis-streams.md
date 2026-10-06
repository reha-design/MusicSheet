# Backend Spec: Redis Streams & Event Streaming

> **Canonical Owner:** `docs/backend/redis-streams.md`  
> **관련 문서:** [docs/backend/api.md](./api.md), [docs/adr/002-redis-streams.md](../adr/002-redis-streams.md)
>
> **구현 상태:** Redis 이벤트 저장소와 SSE API를 구현했습니다. 실제 worker 발행은 W03 연결 범위입니다. [W02 실행 계획](../plans/redis-streams-sse-implementation-plan.md)을 따릅니다.

---

## 1. Redis 역할 구분

같은 Redis 서버를 사용하더라도 SSE 이벤트 저장과 Celery 작업 브로커는 별도 역할입니다.

| 기능 | 연결 설정 예시 | 자료구조 / 용도 |
| :--- | :--- | :--- |
| Celery broker | `CELERY_BROKER_URL=redis://localhost:6379/0` | Kombu Redis transport가 작업 큐를 관리 |
| Celery result backend | `CELERY_RESULT_BACKEND=redis://localhost:6379/1` | Celery task 결과 저장 |
| 애플리케이션 이벤트 저장 | `REDIS_URL=redis://localhost:6379/2` | 이 명세의 Redis Streams, SSE 이벤트 이력 |

Celery의 Redis transport는 이 이벤트 스트림을 사용하지 않습니다. Kombu transport는 일반 task queue를 Redis 리스트 기반으로 처리합니다. [Celery Redis broker 문서](https://docs.celeryq.dev/en/latest/getting-started/backends-and-brokers/redis.html), [Kombu Redis transport 구현](https://github.com/celery/kombu/blob/main/kombu/transport/redis.py)

예시 URL의 DB 번호는 같은 Redis 인스턴스 안에서 키를 논리적으로 나눕니다. 이는 별도 서버나 리소스 격리를 뜻하지 않습니다. 환경 변수 예시는 저장소 루트의 `.env.example`을 기준으로 합니다.

---

## 2. 이벤트 키와 보존 범위

- **Stream key:** `job:{job_id}:events`
- **보존 한도:** `MAXLEN ~ 100`으로 작업별 최근 약 100개 이벤트를 유지합니다.
- **저장 형식:** `XADD job:{job_id}:events MAXLEN ~ 100 * payload <JobProgressEvent JSON>`.
- `JobProgressEvent`는 공용 모델의 `job_id`, `status`, `stage`, `stage_progress`, `overall_progress`, `message`, `timestamp`를 사용합니다. job ID는 UUID canonical 문자열로 정규화합니다.
- 발행/읽기에서 모델을 검증하고 요청한 job과 payload의 job을 대조합니다. 검증 실패 원문과 Redis 예외는 클라이언트나 로그에 노출하지 않습니다.
- 발행 모듈은 PostgreSQL 상태를 변경하지 않습니다. 향후 W03 호출자가 상태를 영속화한 뒤 발행하며, DB/Redis 이중 쓰기의 원자성은 보장하지 않습니다.

Redis Streams는 Pub/Sub과 달리 저장된 이벤트를 ID 기준으로 읽을 수 있습니다. 다만 trim된 이벤트는 복원할 수 없으므로 재접속 재생은 보존된 이벤트 범위에 한정됩니다. 모든 중간 이벤트를 영구 보장하지 않습니다.

---

## 3. SSE 재접속 동작

- 클라이언트는 마지막으로 받은 Stream ID를 SSE의 `id`로 보관하고, 재접속 시 `Last-Event-ID`로 보냅니다.
- API는 해당 ID 이후 현재 Stream에 남아 있는 이벤트를 재생한 뒤 새 이벤트를 계속 전달합니다.
- 최초 구독은 `0-0`부터 보존 이벤트를 읽습니다. cursor는 unsigned 64-bit ASCII 숫자의 `<milliseconds>-<sequence>`이며 미래 ID는 거부합니다. 삭제된 entry의 ID도 Stream의 `last-generated-id`보다 미래가 아니면 유효합니다.
- 비차단 첫 읽기 후 동일 cursor로 `XREAD COUNT 100 BLOCK 15000`을 이어갑니다. `$`나 consumer groups를 사용하지 않으므로 각 구독자는 독립적으로 같은 이력을 받습니다.
- ID가 이미 trim된 범위보다 오래된 경우, 중간 이벤트가 누락될 수 있습니다. 이때 최신 작업 상태의 기준은 PostgreSQL을 조회하는 `GET /api/v1/jobs/{job_id}`이며, 클라이언트는 현재 상태를 다시 동기화해야 합니다.
- 최종 상태도 작업 레코드에 기록합니다. 이벤트 Stream은 상태의 영구 원본이 아닙니다.

```text
Worker ── XADD job:{job_id}:events ──► Application Redis Stream
                                           │
FastAPI SSE ◄── XREAD from Last-Event-ID ─┘

Redis broker (separate DB) ◄── Celery / Kombu task queues
PostgreSQL ── authoritative job state for reconnect sync
```
