# W02 — Redis Streams 및 SSE 설계

> 작성일: 2026-10-02 · Revision 1 · 상태: 사용자 설계 승인, 실행 계획 검토 단계
> 승인 근거: 설계 검토 요청에 대한 사용자의 2026-10-02 “다음작업진행” 응답.
> 구현 시작 전 별도 실행 계획의 독립 리뷰가 필요하다. 이 문서는 계획 점수나 구현 리뷰를 대신하지 않는다.

## 목적과 기준

작업 진행 이벤트를 Redis에 저장하고 `GET /api/v1/jobs/{job_id}/events`로 전달한다. 연결이 끊긴 클라이언트는 `Last-Event-ID` 이후 보존된 이벤트를 복원할 수 있다. 작업 상태의 영구 원본은 PostgreSQL이다.

사용자의 “다음 작업 진행” 요청과 [roadmap](../../roadmap.md)의 다음 후보 W02를 근거로 범위를 정했다. [Redis Streams 명세](../../backend/redis-streams.md), [API 명세](../../backend/api.md), [작업 상태](../../domain/job-state.md), 승인된 [ADR 002](../../adr/002-redis-streams.md)를 따른다. 아래의 최초 접속, heartbeat, 오류 계약은 기존 명세의 빈 부분을 채우는 제안이다.

## 접근 방식

기존 `redis.asyncio.Redis`와 FastAPI `StreamingResponse`를 사용한다. Redis 의존성이 이미 API 프로젝트에 있어 추가 런타임 의존성 없이 구현할 수 있다.

대안인 Pub/Sub은 재생 요구사항을 충족하지 않는다. Consumer Group은 한 이벤트를 구독자 사이에 분배하므로 모든 브라우저가 같은 이력을 보는 이 기능에 맞지 않는다. 각 SSE 연결은 자체 cursor로 `XREAD`를 사용한다.

## 이벤트 계약과 발행 경계

- 공용 `JobProgressEvent`의 필드와 enum을 그대로 사용한다: `job_id`, `status`, `stage`, `stage_progress`, `overall_progress`, `message`, `timestamp`.
- Stream 키는 `job:{job_id}:events`; JSON 문자열 하나를 `payload` 필드에 저장한다. 기존 명세의 필드별 `XADD` 예시는 실제 envelope 계약과 맞도록 구현 전에 갱신한다.
- 발행은 `XADD ... MAXLEN ~ 100 * payload <JSON>`이며 반환값은 Redis Stream ID다. 약 100개 보존은 정확한 100개 제한이 아니다.
- 발행 입력과 읽은 payload를 공용 모델로 검증하고, 읽을 때 payload의 `job_id`가 요청한 작업과 일치하는지도 확인한다. 검증 실패는 원문을 클라이언트나 로그에 노출하지 않는다.
- 발행 API는 PostgreSQL을 갱신하지 않는다. 향후 W03 호출자는 상태를 먼저 영속화한 다음 이벤트를 발행한다. 두 저장소 사이의 원자성/outbox 보장은 이번 범위에 포함하지 않는다.
- W02는 발행 모듈과 SSE 수신 경로를 제공한다. 등록·취소 REST 경로의 이벤트 발행이나 실제 worker 진행 이벤트는 W03 연결 작업에서 담당한다. 따라서 기존 작업이 자동 처리되기 시작하지 않는다.

## SSE 요청과 재접속

1. 작업 ID는 UUID로 검증·정규화하여 Redis 키에 임의 문자열을 넣을 수 없게 한다. 잘못된 ID는 `422`다. 기존 REST 경로의 ID 정책은 이번에 변경하지 않는다.
2. PostgreSQL에서 작업 존재를 확인한다. 없는 작업은 `404`, DB 실패는 기존 방식의 일반화된 `503`이다.
3. `Last-Event-ID`가 없으면 `0-0`부터 현재 남아 있는 모든 이벤트를 읽는다. 있으면 지정 ID를 제외하고 그 이후 이벤트를 읽는다. `$`를 사용하지 않아 재생에서 실시간 구독으로 넘어가는 사이의 이벤트를 건너뛰지 않는다.
4. Header는 ASCII 숫자 두 개의 `<milliseconds>-<sequence>` 형식으로 제한하며 각 값은 unsigned 64-bit 범위여야 한다. 빈 값, 특수 cursor, 음수, 개행, 지나치게 긴 값은 `422`로 거부한다. 검증한 ID를 SSE 프레임에만 사용한다.
5. 수신 cursor가 Redis 최신 생성 ID보다 미래이면 `422`로 거부한다. 아직 이력이 없는 작업에서 `0-0` 이외 cursor도 거부한다. 검증은 비차단 첫 읽기와 함께 응답 시작 전에 수행한다.
6. 보존 범위보다 오래된 cursor는 현재 남아 있는 이벤트만 재생한다. 자동으로 완전한 이력을 복원했다고 주장하지 않는다. 클라이언트는 최초 연결 및 재접속 시 `GET /api/v1/jobs/{job_id}`로 최신 상태를 동기화하고, 이벤트 timestamp를 비교하여 오래된 재생 이벤트로 화면 상태를 되돌리지 않는다. Stream trim/삭제 중 누락은 허용된 사양 제약이다.

진행 이벤트 프레임:

```text
id: 1790900000000-0
event: progress
data: {"job_id":"...","status":"RUNNING","stage":"TRANSCRIBE","stage_progress":40,"overall_progress":55,"message":"전사 중","timestamp":"2026-10-02T00:00:00Z"}

```

`data`는 모델을 JSON으로 직렬화한 한 줄이다. message의 개행은 JSON escape로 표현한다. 각 프레임은 빈 줄로 끝난다. `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`를 설정한다. Browser 코드는 `addEventListener('progress', ...)`를 사용한다.

## 연결 수명과 실패 처리

- 요청마다 cursor를 보유하고 `XREAD COUNT 100 BLOCK 15000`으로 읽는다. 비어 있는 읽기는 `: heartbeat\n\n` comment를 보낸다. 모든 Redis 작업에는 유한 timeout을 적용하며 blocking read의 timeout은 BLOCK보다 길게 둔다.
- 응답 전에 첫 비차단 읽기와 데이터 검증을 완료한다. Redis 연결 실패/잘못된 보존 payload는 일반화된 `503`으로 응답한다. 내부 URL, 인증정보, driver 예외, 원본 payload는 노출하지 않는다.
- 응답 시작 후 Redis 또는 payload 오류는 ID 없는 `event: stream_error`와 고정 JSON `{"detail":"Event stream is unavailable"}`를 한 번 보내고 연결을 닫는다. 클라이언트는 재접속 시 마지막 정상 progress ID를 유지하고 PostgreSQL 상태도 다시 조회한다.
- 마지막으로 전달한 이벤트의 ID를 다음 `XREAD` cursor로 사용한다. 동시에 여러 구독자가 같은 이벤트를 받을 수 있다. 느린 클라이언트에 무제한 큐를 만들지 않고 batch 최대 100개를 순차 전달한다.
- terminal progress 이벤트를 전달한 뒤에도 연결은 유지한다. 클라이언트가 PostgreSQL terminal 상태를 확인하면 EventSource를 닫는다. Worker가 terminal 이벤트를 발행하지 못한 경우에도 REST로 완료 여부를 확인할 수 있다.
- disconnect/cancellation은 정상적으로 전파하고 pending Redis read를 종료한다. SSE 요청은 앱 공용 Redis client를 닫지 않는다. 앱 종료 시 client를 닫는다.
- `create_app`의 Redis client 초기화는 health provider 주입 여부와 분리한다. 테스트용 health provider를 주입해도 이벤트 기능이 꺼지지 않도록 한다. 별도 이벤트 store 의존성은 테스트에서 교체할 수 있게 한다.

## 모듈과 구현 단위

| 단위 | 책임 및 예상 파일 |
| :--- | :--- |
| 1. 이벤트 저장소 | `services/api/src/musicsheet_api/events/store.py`: cursor 검증, JSON 검증, 발행, 비차단/차단 읽기. `events/__init__.py`: 명시적 export. `tests/test_event_store.py`: Redis double 기반 계약 검증. |
| 2. SSE 및 앱 연결 | `events/router.py`: 작업 존재 확인, 응답 시작 전 오류 처리. `events/streaming.py`: 프레임, heartbeat, 읽기 loop, cancellation. `app.py`: 수명주기와 router 연결. `tests/test_job_events.py`, `tests/test_app.py`: ASGI 및 lifespan 검증. |
| 3. 실 Redis 및 운영 증거 | `tests/integration/test_redis_events.py`: 선택형 Redis 통합 검증. API README와 canonical API/Streams 문서, 구현 현황, 결과보고서, 완료 색인을 갱신한다. |

각 단위는 TDD 검증·결과보고서·독립 코드 리뷰 95/100 이상과 blocker/important 해소 후 다음 단위로 진행한다. 실행 계획은 `docs/plans/redis-streams-sse-implementation-plan.md`에 별도로 작성하고, 버전별 독립 점수 95/100 이상을 확인한 뒤 구현한다.

## 검증과 완료 기준

- 발행의 키/JSON/MAXLEN 옵션, 정상 event roundtrip, payload 작업 ID 불일치, 잘못된 enum/진행률/JSON, cursor 형식·수치 경계를 검증한다.
- 최초 접속, Last-Event-ID의 exclusive replay, replay 이후 새 이벤트, 서로 독립된 구독자, 빈 Stream heartbeat, 미래 cursor, trim 이후 남은 이벤트 재생을 검증한다.
- HTTP `404`/`422`/`503`, SSE header와 명명된 프레임, message 개행 escape, 초기 오류와 중간 오류, disconnect 중 read cancellation, lifecycle close를 검증한다.
- 무한 streaming을 `TestClient.get()`로 끝까지 수집하지 않는다. 유한 Redis double과 직접 ASGI send/receive harness를 사용해 프레임을 받은 후 disconnect를 보내고 task 정리를 확인한다.
- API full suite: `uv run --project services/api --python 3.13 pytest services/api/tests -q`.
- Root regression: `uv run --project . --python 3.13 pytest -q`.
- Lock 확인: root/API 각각 `uv lock --check`; 문서/공백 확인: `git diff --check`와 수정한 문서의 상대 링크 존재 검사.
- 실 Redis는 명시적인 `MUSICSHEET_TEST_REDIS_URL`이 설정되었을 때만 사용한다. 운영 키에 손대지 않고 매 실행 생성한 UUID 작업 키만 삭제한다. `FLUSHDB`/`FLUSHALL`은 사용하지 않는다. 기본 테스트에서는 skip한다.
- 통합 검증은 실 `XADD`, exclusive `XREAD`, 읽기 대기 중 새 이벤트, 두 구독자의 같은 이벤트 수신, 명시적 trim 후 잔존 이벤트 재생을 확인한다. 실제로 실행하지 못하면 미검증으로 보고한다.

## 제외 범위와 후속 조건

Celery, 미디어 다운로드, Basic Pitch 제품 연결, 인증, frontend 구현, Consumer Group, outbox, 작업별 Stream TTL 정책은 후속 작업이다. 작업별 MAXLEN은 작업 수 증가에 따른 총 Redis 저장량을 제한하지 않으므로 운영 배포 전에 만료/정리 정책을 정해야 한다.

사용자 설계 검토 후 canonical 문서의 제안 계약을 반영하고 실행 계획을 작성한다. 이번 문서 작성만으로 구현 상태를 완료로 표시하거나 계획/코드 점수를 추정하지 않는다.
