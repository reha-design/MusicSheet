# Backend Spec: Redis Streams & Event Streaming

> **Canonical Owner:** `docs/backend/redis-streams.md`  
> **관련 문서:** [docs/backend/api.md](./api.md), [docs/adr/002-redis-streams.md](../adr/002-redis-streams.md)

---

## 1. Redis Streams 채택 이유 (Pub/Sub과의 차이)

- **Redis Pub/Sub:** At-most-once 전송. 브라우저가 잠시 연결 끊기면 발생한 진행률 이벤트를 영구 유실함.
- **Redis Streams:** 메시지 영속화 및 `Last-Event-ID` 지원. 재접속 시 끊긴 지점부터 완벽히 복원(Replay) 가능.

---

## 2. 스트림 키 및 이벤트 구조

- **Stream Key:** `job:{job_id}:events`
- **Max Length:** `MAXLEN ~ 100` (한 작업당 최대 100개 이벤트 유지 후 자동 트림)

```text
Worker ──(XADD job:{job_id}:events * status RUNNING stage SEPARATE progress 40)──► Redis
                                                                                     │
FastAPI SSE Endpoint ◄──(XREAD stream job:{job_id}:events {last_id})─────────────────┘
```
