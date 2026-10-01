# Backend Spec: Redis Streams & Event Streaming

> **Canonical Owner:** `docs/backend/redis-streams.md`  
> **관련 문서:** [docs/backend/api.md](./api.md), [docs/adr/002-redis-streams.md](../adr/002-redis-streams.md)
>
> **구현 상태:** W02의 이벤트 저장소와 SSE API가 구현되었습니다. 이 문서는 이벤트 계약의 기준입니다.

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
- **Stream field:** `data` 하나에 공용 `JobProgressEvent`의 JSON 전체를 저장합니다. 기존 이벤트 필드(`job_id`, `status`, `stage`, `stage_progress`, `overall_progress`, `message`, `timestamp`)를 그대로 사용합니다.
- **발행:** `JobEventStore.publish(event)`는 `XADD`와 `MAXLEN ~ 100`으로 이벤트를 추가하고 Stream ID를 문자열로 반환합니다.
- **읽기:** `JobEventStore.read_after(job_id, last_id)`는 최대 100개를 `XREAD`로 가져오며, 호출자는 응답의 Stream ID를 다음 커서로 사용합니다. 손상된 payload는 본문을 기록하지 않고 건너뛰며 ID는 보존합니다.
- **첫 읽기:** `Last-Event-ID`가 없으면 SSE 구독은 `0-0`부터 시작합니다. 재연결은 해당 ID 뒤의 현재 보존된 이벤트부터 읽습니다.
- **예시:** `XADD job:{job_id}:events MAXLEN ~ 100 * data '{"job_id":"...","status":"RUNNING","stage":"SEPARATE","stage_progress":40,"overall_progress":20,"message":"Separating audio","timestamp":"2026-09-28T00:00:00Z"}'`

Redis Streams는 Pub/Sub과 달리 저장된 이벤트를 ID 기준으로 읽을 수 있습니다. 다만 trim된 이벤트는 복원할 수 없으므로 재접속 재생은 보존된 이벤트 범위에 한정됩니다. 모든 중간 이벤트를 영구 보장하지 않습니다.

---

## 3. SSE 재접속 동작

- 클라이언트는 마지막으로 받은 Stream ID를 SSE의 `id`로 보관하고, 재접속 시 `Last-Event-ID`로 보냅니다.
- API는 해당 ID 이후 현재 Stream에 남아 있는 이벤트를 재생한 뒤 새 이벤트를 계속 전달합니다.
- ID가 이미 trim된 범위보다 오래된 경우, 중간 이벤트가 누락될 수 있습니다. 이때 최신 작업 상태의 기준은 PostgreSQL을 조회하는 `GET /api/v1/jobs/{job_id}`이며, 클라이언트는 현재 상태를 다시 동기화해야 합니다.
- 최종 상태도 작업 레코드에 기록합니다. 이벤트 Stream은 상태의 영구 원본이 아닙니다.
- SSE 프레임의 `id`에는 Redis Stream ID, `data`에는 `JobProgressEvent` JSON을 사용합니다. 15초 동안 유효 이벤트가 없으면 `: keep-alive` 주석 heartbeat를 보냅니다.
- 연결 시작 전 PostgreSQL에서 작업을 확인합니다. 작업이 없으면 `404`, PostgreSQL 또는 Redis를 사용할 수 없으면 일반 메시지의 `503`을 반환합니다. 잘못된 `Last-Event-ID`는 `400`입니다.
- 연결 도중 Redis 오류가 발생하면 민감한 오류 세부정보를 노출하지 않고 기록한 뒤 스트림을 닫습니다. 클라이언트가 연결을 닫으면 구독을 종료하며 공유 Redis 클라이언트는 API 수명주기가 닫습니다.
- 잘못된 저장 이벤트는 일반 경고만 기록하고 해당 Stream ID까지 커서를 진행해 재연결 시 반복되지 않도록 합니다.
- W02는 이벤트 저장과 구독만 제공합니다. Celery 작업에서 이벤트를 게시하는 연결은 W03 범위입니다.

```text
Worker ── XADD job:{job_id}:events ──► Application Redis Stream
                                           │
FastAPI SSE ◄── XREAD from Last-Event-ID ─┘

Redis broker (separate DB) ◄── Celery / Kombu task queues
PostgreSQL ── authoritative job state for reconnect sync
```
