# Backend Spec: Redis Streams & Event Streaming

> **Canonical Owner:** `docs/backend/redis-streams.md`  
> **관련 문서:** [docs/backend/api.md](./api.md), [docs/adr/002-redis-streams.md](../adr/002-redis-streams.md)
>
> **구현 상태:** 목표 설계입니다. 현재 저장소에는 SSE API나 이벤트 발행 코드가 없습니다.

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
- **예시 이벤트:** `XADD job:{job_id}:events MAXLEN ~ 100 * status RUNNING stage SEPARATE progress 40`

Redis Streams는 Pub/Sub과 달리 저장된 이벤트를 ID 기준으로 읽을 수 있습니다. 다만 trim된 이벤트는 복원할 수 없으므로 재접속 재생은 보존된 이벤트 범위에 한정됩니다. 모든 중간 이벤트를 영구 보장하지 않습니다.

---

## 3. SSE 재접속 동작

- 클라이언트는 마지막으로 받은 Stream ID를 SSE의 `id`로 보관하고, 재접속 시 `Last-Event-ID`로 보냅니다.
- API는 해당 ID 이후 현재 Stream에 남아 있는 이벤트를 재생한 뒤 새 이벤트를 계속 전달합니다.
- ID가 이미 trim된 범위보다 오래된 경우, 중간 이벤트가 누락될 수 있습니다. 이때 최신 작업 상태의 기준은 PostgreSQL을 조회하는 `GET /api/v1/jobs/{job_id}`이며, 클라이언트는 현재 상태를 다시 동기화해야 합니다.
- 최종 상태도 작업 레코드에 기록합니다. 이벤트 Stream은 상태의 영구 원본이 아닙니다.

```text
Worker ── XADD job:{job_id}:events ──► Application Redis Stream
                                           │
FastAPI SSE ◄── XREAD from Last-Event-ID ─┘

Redis broker (separate DB) ◄── Celery / Kombu task queues
PostgreSQL ── authoritative job state for reconnect sync
```
