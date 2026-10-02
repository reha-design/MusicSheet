# W02 Redis Streams 및 SSE 구현 계획

> **For agentic workers:** `superpowers:executing-plans`로 주 세션에서 구현한다. AGENTS.md의 단위별 독립 리뷰 요구사항이 스킬의 최종 리뷰만 수행하는 기본 방식보다 우선한다.
> 작성일: 2026-10-02 · Revision 2 · 상태: 사용자 계획 승인, Task 1–2 완료·Task 3 진행; 독립 계획 리뷰 100/100 통과

**Goal:** 작업 진행 이벤트의 Redis 저장·독립 구독·Last-Event-ID 재생을 제공한다.

**Architecture:** 기존 API-local `redis.asyncio.Redis`를 사용한다. 저장소가 JSON 검증과 cursor 기반 읽기를 담당하고, 별도 router/streaming 모듈이 HTTP 사전 검증 및 SSE 연결 수명을 담당한다. PostgreSQL은 최신 상태 원본으로 유지한다.

**Tech Stack:** Python 3.13, FastAPI/Starlette, redis-py, 공용 Pydantic `JobProgressEvent`, pytest 및 asyncio. 새 runtime dependency와 root lockfile 변경 없음.

비동기 테스트는 기존 저장소 방식대로 동기 `test_*`에서 `asyncio.run()`을 호출한다. pytest-asyncio를 추가하지 않는다. Redis client 생성·사용·종료는 같은 event loop에서 수행한다.

**Spec:** [승인된 W02 설계 Revision 1](../superpowers/specs/2026-10-02-redis-streams-sse-design.md), [Redis Streams](../backend/redis-streams.md), [API](../backend/api.md), [작업 상태](../domain/job-state.md).

## Global Constraints

- Stream key `job:{job_id}:events`, JSON `payload`, `XADD MAXLEN ~ 100`; consumer groups/PubSub 금지.
- 이벤트는 기존 `JobProgressEvent`를 사용하고 공용 필드/enum을 변경하지 않는다. UUID 문자열은 저장/조회 모두 정규화한다.
- header가 없으면 `0-0`; 지정 cursor는 exclusive. 읽기에 `$`를 사용하지 않는다.
- 첫 비차단 batch 검증 후 HTTP 응답 시작. 매 batch 최대 100개; 이후 `XREAD COUNT 100 BLOCK 15000`.
- heartbeat `: heartbeat\n\n`; progress는 `id`/`event: progress`/한 줄 JSON `data`/빈 줄이다.
- 초기 장애는 일반 `503`. 시작 후 장애는 ID 없는 `stream_error`, `{"detail":"Event stream is unavailable"}`를 한 번 보내고 종료한다.
- terminal event 이후에도 연결 유지. 요청 취소는 전파하며 Redis client를 닫지 않는다. 앱 lifespan이 생성/종료를 소유한다.
- 초기/재접속 시 REST snapshot을 동기화한다. trim된 중간 이벤트와 DB/Redis 이중 쓰기 원자성을 보장하지 않는다.
- W03 연결 전 REST 등록·취소 동작을 바꾸거나 실제 작업을 실행하지 않는다.
- 계획/코드 리뷰는 각각 95/100 이상, unresolved blocker/important 없음이어야 다음 게이트를 통과한다. 점수는 reviewer만 부여한다.

## Review Focus

- 유효하지만 미래인 cursor: stream의 `last-generated-id`와 수치로 비교해 422; 삭제된 최신 entry가 있어도 XREVRANGE만으로 미래를 판정하지 않는다 (Task 1).
- bytes/text Redis 응답과 잘못된 payload: 정상 decoding/모델 검증 및 요청 job ID 대조; 비밀 원문 미노출 (Task 1/2).
- replay → live 전환 중 발행: 동일 cursor로 이어 읽어 보존된 이벤트 누락 없음 (Task 2/3).
- disconnect 중 pending BLOCK read: 요청 task와 Redis read가 취소되고 앱 공용 client는 열려 있음 (Task 2).
- health provider 주입 또는 Redis 초기화 오류: event 의존성과 health mock 분리, 종료 시 정확히 한 번 close, DB close 오류에도 Redis close (Task 2).

## Task 1 — 이벤트 저장소와 cursor 계약

**Files:** Create `services/api/src/musicsheet_api/events/__init__.py`, `events/store.py`, `services/api/tests/test_event_store.py`, `docs/reports/redis-event-store-report.md`; Modify `docs/backend/redis-streams.md`, `docs/main_spec.md`, 본 계획.

**Interfaces:**

- `normalize_job_id(value: str | UUID) -> str`: UUID 검증·canonical 문자열. `ValueError`는 고정 일반 메시지.
- `parse_event_id(value: str) -> tuple[int, int]`: 전체 길이 41 이하, ASCII `[0-9]+-[0-9]+`, 각 요소 `0..18446744073709551615`. 잘못된 입력은 `InvalidEventCursor(ValueError)`.
- `StreamEvent` frozen dataclass: `id: str`, `event: JobProgressEvent`.
- `EventStore(Protocol)`: 아래 `publish`, `initial_read`, `read`를 가진다. Task 2에서 이 protocol에 의존한다.
- `RedisEventStore(client: Redis)`: client 소유권 없음. `async publish(event: JobProgressEvent) -> str`; `async initial_read(job_id: str, cursor: str) -> list[StreamEvent]`; `async read(job_id: str, cursor: str, *, block_ms: int = 15000) -> list[StreamEvent]`.
- `EventStoreUnavailable(Exception)`: Redis timeout/연결/응답/payload 오류를 원문 없이 표현. cancellation은 이 예외로 감싸지 않는다.

- [x] 실패 테스트를 작성한다: `test_publish_serializes_validated_event_and_scopes_key`는 canonical UUID, JSON envelope, `maxlen=100, approximate=True`와 반환 ID를 검증한다. `test_publish_revalidates_mutated_model`은 이미 생성한 모델을 잘못된 enum/범위/job ID로 변경했을 때 Redis write가 없는지 확인한다. sentinel `secret-token-example`을 넣고 warnings capture, caplog, 외부 예외 `str`/`repr`에 원문이 없음을 검증한다.
- [x] `test_cursor_bounds_and_ascii_format`은 `0-0`, 최대 u64 두 요소의 수치 결과 및 `''`, `$`, `+`, `-1-0`, 공백, Unicode 숫자, 개행, overflow, 42글자 입력 거부를 확인한다. 숫자 leading zero는 길이 제한 내에서 허용하고 반환 tuple은 수치 비교한다.
- [x] `test_initial_read_is_exclusive_and_nonblocking`, `test_future_cursor_uses_last_generated_id`, `test_nonzero_cursor_without_stream_is_rejected`, `test_deleted_last_entry_does_not_make_valid_cursor_future`를 작성한다. stream metadata가 missing key인 경우에만 최신 ID `0-0`으로 취급하고 WRONGTYPE/기타 ResponseError는 unavailable이다.
- [x] `test_read_handles_bytes_and_text`, `test_read_rejects_wrong_job_and_invalid_payload`, `test_read_rejects_invalid_or_nonincreasing_ids`, `test_trimmed_cursor_reads_remaining_entries`, `test_empty_read_is_empty_list`, `test_redis_errors_are_sanitized`, `test_timeout_is_bounded`, `test_cancellation_propagates`를 작성한다. 반환 entry ID는 cursor보다 커야 하고 batch 안에서 엄격히 증가해야 한다.
- [x] RED: `uv run --project services/api --python 3.13 pytest services/api/tests/test_event_store.py -q`; 아직 없는 모듈/동작으로 실패했음을 기록한다.
- [x] 저장소를 구현한다. `initial_read`는 cursor `0-0`이 아니면 XINFO STREAM의 `last-generated-id`를 확인 후 비차단 `XREAD`를 한다. 미래 cursor는 InvalidEventCursor이고 stream 삭제 시점의 복원 제한은 설계대로다. XREAD의 `block=None`은 비차단이며 `block=0`을 사용하지 않는다.
- [x] 모든 Redis 명령을 `asyncio.wait_for`로 제한한다: 비차단/발행/metadata 2초, 차단 read `block_ms / 1000 + 5`초. 내부 exception message를 로그/응답에 붙이지 않는다. batch 전체를 검증한 후 반환하며 부분적으로 잘못된 batch를 전달하지 않는다.
- [x] 공용 모델은 `model_dump(warnings=False)`한 값을 다시 `model_validate`하여 mutable 모델도 재검증한다. 검증/직렬화 예외를 고정 일반 메시지로 감싸고 `raise ... from None`으로 연결된 원문 예외가 외부 traceback에 출력되지 않게 한다. job ID를 canonical 문자열로 저장하고 JSON 직렬화한다. Redis 응답이 bytes인 경우 UTF-8 strict decode하고 IDs도 검증한다.
- [x] canonical Streams 문서에 승인 설계의 payload·보존·cursor 계약을 옮기고 상태는 “저장소 구현, SSE 미연결”로 구분한다. 결과보고서와 색인을 작성한다.
- [x] GREEN: focused tests 및 API full suite `uv run --project services/api --python 3.13 pytest services/api/tests -q`, `git diff --check`. 독립 코드 리뷰 95/100 이상과 important 해소 후 Task 1 관련 파일만 명시적으로 stage/commit한다: `feat(events): add Redis progress event store`.

## Task 2 — SSE route, 연결 loop 및 앱 수명주기

**Files:** Create `services/api/src/musicsheet_api/events/router.py`, `events/streaming.py`, `services/api/tests/test_job_events.py`, `docs/reports/job-sse-api-report.md`; Modify `services/api/src/musicsheet_api/app.py`, `services/api/tests/test_app.py`, `docs/backend/api.md`, `docs/backend/redis-streams.md`, `docs/main_spec.md`, 본 계획.

**Consumes:** Task 1 `EventStore`, `StreamEvent`, `parse_event_id`, 두 public 예외; 기존 `JobRepository(pool).get_job(job_id)`와 `Settings.redis_url`.

**Produces:**

- `encode_progress(item: StreamEvent) -> str`: 검증한 ID와 JSON으로 SSE frame 생성.
- `async stream_events(store: EventStore, job_id: str, cursor: str, initial: list[StreamEvent]) -> AsyncIterator[str]`: 첫 batch 전달 이후 같은 cursor로 read 반복.
- `SSEStreamingResponse(StreamingResponse)`: HTTP ASGI spec 버전과 무관하게 disconnect 수신과 body 송신을 함께 감시하고 종료·취소 시 양쪽 task를 cancel/await하여 pending read를 정리한다.
- `router = APIRouter(prefix="/api/v1/jobs", tags=["events"])`; `GET /{job_id}/events`.
- lifespan에서 `app.state.event_store: EventStore | None` 설정. router는 이를 조회하고 tests는 state를 교체한다. `create_app` public 인자는 유지한다.

- [x] `test_initial_subscription_replays_retained_events`, `test_last_event_id_replays_only_later_ids`, `test_event_written_during_replay_is_delivered_next`, `test_two_subscribers_receive_same_history`, `test_empty_read_emits_heartbeat`, `test_terminal_event_keeps_subscription_open`을 작성한다. 첫 batch 전달 전 Redis fake가 후속 이벤트를 추가해 전환 시 cursor 사용을 검증한다.
- [x] `test_sse_frames_escape_message_newlines_and_have_headers`, `test_uuid_is_normalized`, `test_invalid_id_or_header_returns_422`, `test_future_cursor_returns_422`, `test_unknown_job_returns_404`, `test_db_unavailable_returns_503`, `test_missing_event_store_returns_503`, `test_initial_read_failure_returns_503_without_secrets`, `test_later_failure_emits_one_sanitized_error_without_id`를 작성한다.
- [x] 직접 ASGI send/receive harness를 작성한다. `http.request` 이후 프레임 관측에 따라 `http.disconnect`를 보낸다. ASGI HTTP spec 2.3/2.4 양쪽에서 blocking read 중 disconnect를 발생시키고, spec 2.4의 send 실패와 호스트 task cancellation도 검증한다. 각 실행 전체를 2초 이내 wait_for로 제한하고 task/fake pending read 정리를 finally에서 수행한다.
- [x] `test_disconnect_cancels_pending_read_without_closing_shared_client`와 `test_response_cancellation_propagates`를 작성한다. stream_error로 취소를 바꾸지 않는다. 프레임 생성/loop 단위 검증은 async generator를 직접 읽고 `aclose()`한다. 무한 응답을 동기 TestClient로 수집하지 않는다.
- [x] 앱 테스트 `test_health_override_does_not_disable_event_store`, `test_missing_redis_url_disables_only_events`, `test_redis_initialization_failure_keeps_liveness`, `test_redis_closes_once_on_shutdown_even_if_db_close_fails`, `test_event_request_does_not_close_client`를 작성한다. RED: focused `test_job_events.py test_app.py` 실행.
- [x] router는 UUID path param과 단일 optional Header를 검증하고 header 기본값은 `None`에서만 `0-0`으로 바꾼다. DB 존재 확인 → event store 확인 → initial_read의 순서를 지킨다. 헤더 중복은 422로 거부한다. DB/Redis 실패는 고정 generic HTTPException으로 mapping한다.
- [x] 응답은 `SSEStreamingResponse(stream_events(...), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})`. Starlette의 spec 2.4 경로는 send 오류에 의존하므로 BLOCK read 중에도 즉시 disconnect를 처리하기 위해 별도 disconnect listener를 유지한다. 초기 batch 전달 후 각 read 결과를 순차 emit하고 마지막 전송 ID를 cursor로 유지한다. 빈 batch는 heartbeat; 오류는 고정 stream_error 프레임 1회 후 return; cancellation은 re-raise한다.
- [x] lifespan은 health override와 무관하게 `Redis.from_url(..., decode_responses=True, socket_connect_timeout=2, socket_timeout=20)`을 만들고 `RedisEventStore`를 연결한다. 없거나 생성 실패하면 event_store=None. health override는 readiness provider에만 영향을 준다. 종료 시 기존 DB/Redis 중첩 finally 정리를 유지하고 state가 닫힌 client를 참조하지 않게 정리한다.
- [x] API/Streams canonical 문서에 구현 계약을 반영하고 결과보고서/색인을 작성한다. GREEN: focused + API full suite 및 root `uv run --project . --python 3.13 pytest -q`, `git diff --check`. 독립 코드 리뷰 95/100 이상과 important 해소 후 관련 파일만 commit: `feat(api): stream job progress with SSE replay`.

## Task 3 — 실 Redis 통합 증거와 완료 문서

**Files:** Create `services/api/tests/integration/test_redis_events.py`, `docs/reports/redis-streams-sse-implementation-report.md`; Modify `services/api/pyproject.toml` (marker 설명만), `services/api/README.md`, `README.md`, `docs/main_spec.md`, `docs/roadmap.md`, `docs/completed-work.md`, `docs/reports/current-implementation-briefing.md`, 본 계획. `docs/backlog.md`에서는 W02가 이미 이동되어 W03 이후 항목을 유지한다.

**Consumes:** Task 1/2 public 계약. **Produces:** 선택형 실제 Redis 검증, 정확한 구현 상태/실행 명령/통합 증거 및 W02 완료 기록.

- [ ] marker `redis_integration` 등록; `MUSICSHEET_TEST_REDIS_URL` 없으면 테스트 skip한다. 설정이 있는데 연결이 실패하면 skip하지 않고 고정 일반 실패로 표시한다. 테스트 URL은 repr에 `<redacted Redis test URL>`로 나타내고 예외/pytest locals에 비밀을 노출하지 않는다.
- [ ] 각 실행에서 UUID job 키를 생성한다. 다른 키와 공유 DB 설정은 변경하지 않는다. client cleanup/finally에서 자신의 정확한 키만 `DELETE`; FLUSHDB/FLUSHALL 금지. key cleanup 실패도 고정 문구로 기록하고 원래 실패를 숨기지 않는다.
- [ ] `test_real_redis_publish_and_exclusive_replay`, `test_real_redis_waiting_read_receives_new_event`, `test_real_redis_two_readers_receive_same_event`, `test_real_redis_trim_replays_retained_entries`, `test_real_redis_deleted_last_id_is_valid_cursor`, `test_real_redis_empty_blocking_read_times_out`를 구현한다. 각 read client에는 UUID 기반 고유 `client_name`을 설정한다. publisher client의 `CLIENT LIST`에서 해당 이름의 `cmd=xread`, flag `b`를 관측하고 read task가 pending임을 확인한 다음 발행한다. 두 reader는 둘 다 서버에서 blocked임을 확인한다. polling은 10ms 간격·1초 deadline, read는 2초 BLOCK·4초 전체 timeout으로 제한한다. 빈 read 테스트는 새 빈 stream 키를 100ms BLOCK으로 읽고 결과가 비어 있고 즉시 반환하지 않았음을 확인한다. trim 테스트만 자기 stream에 exact XTRIM을 적용한다. 통합 테스트용 ACL은 CLIENT LIST를 허용해야 하며 응답 원문은 출력하지 않는다.
- [ ] 실제 SSE route와 store를 연결하는 `test_sse_replays_events_from_real_redis`를 추가한다. DB 존재 확인은 기존 repository boundary double로 대체하고 Redis/JSON/route/ASGI는 실제 코드를 실행한다. 프레임 수신 후 disconnect하고 앱/read 종료를 확인한다. 실제 PostgreSQL을 함께 사용한 end-to-end로 표현하지 않는다.
- [ ] 실 Redis 사용 전 해당 URL의 명시 설정 여부만 확인한다. 무설정이면 인프라를 임의로 설치/시작하지 않고 미검증으로 보고한다. 설정이 있으면 `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_redis_events.py -m redis_integration -q` 실행. 새 통합 테스트가 RED를 재현할 때만 원인을 수정하며 Task 1/2 제품 변경이 필요하면 해당 단위 재리뷰한다.
- [ ] 일반 검증: `uv run --project services/api --python 3.13 pytest services/api/tests -q`; `uv run --project . --python 3.13 pytest -q`; `uv lock --check`; `uv lock --project services/api --check`; `git diff --check`. pytest skipped/unverified와 warning은 보고서에 명시한다.
- [ ] README/현황에 SSE 구현과 W03 worker 미연결 경계를 반영한다. curl `-N` 요청, Last-Event-ID, browser `progress` listener, REST 동기화, terminal close, stream_error 재접속, TTL/outbox 한계를 설명한다. 완료 문서에는 날짜·보고서·별도 계획/코드 리뷰 점수·commit을 기록한다.
- [ ] 변경한 문서의 상대 링크 존재와 미완료 placeholder를 확인한다. 독립 코드 리뷰 95/100 이상과 important 해소 후 관련 파일만 commit: `test(events): verify Redis replay and document SSE operations`. 완료 후 전체 W02 범위를 독립 최종 리뷰하고 발견된 중요한 결함은 검증·재리뷰한다. push/PR/merge는 이번 작업 범위에 포함하지 않는다.

## 리뷰 및 진행 기록

| 날짜 | 대상 | reviewer | 점수 | 지적과 처리 |
| :--- | :--- | :--- | :--- | :--- |
| 2026-10-02 | 계획 Revision 1 | 독립 reviewer `/root/w02_plan_review` | **94/100** (23/25, 20/20, 20/20, 22/25, 9/10) | important: model_dump 경고 원문 누출; minor: BLOCK 동기화, async 테스트 실행 방식. Revision 2에 경고 억제·누출 검증, 서버 blocked 관측, asyncio.run 방식을 반영. 재평가 전 구현 금지. |
| 2026-10-02 | 계획 Revision 2 | 독립 reviewer `/root/w02_plan_review` | **100/100** (25/25, 20/20, 20/20, 25/25, 10/10) | Revision 1 지적 모두 해소. SSE 2.4의 pending read 중 disconnect 감시와 환경 사전 확인도 검토. unresolved blocker/important/minor 없음. 계획 사용자 검토와 구현 리뷰는 별도이며 제품 코드 변경 없음. |

설계 승인: 사용자의 2026-10-02 “다음작업진행” 응답. 계획 및 실행 방식 승인: 이어진 “진행” 응답. 주 세션에서 구현하고 각 단위는 독립 reviewer로 검증한다. 기존 작업 폴더의 승인된 설계/계획 변경을 이어서 작업하며 별도 worktree는 생성하지 않는다.

Task 1 독립 코드 리뷰: 2026-10-02, `/root/w02_store_review`, BASE `36588ac`, **99/100** (25/25, 25/25, 24/25, 15/15, 10/10). Blocker/important 없음. Reviewer focused suite 41 passed 및 추가 probe 6개 통과. Minor deferred: UTF-8/응답구조/batch상한/publish·metadata cancellation probe의 영구 회귀 테스트 추가. Task 3 실 Redis 범위와 구분한다.

Task 2 독립 코드 리뷰: 2026-10-03 `/root/w02_sse_review`, BASE `c1ca195`, **98/100** (25/25, 25/25, 23/25, 15/15, 10/10). Blocker/important 없음. 독립 API221/root59 및 추가 4 cleanup/cursor/cancellation probes 통과. Minor: 실제 store/client와 lifespan을 연결한 요청 종료 close0·앱 종료 close1 검증을 Task 3에서 보강한다.

## 실행 환경 사전 확인과 현재 baseline

2026-10-02 확인 결과, 기본 uv cache 및 pytest 임시 폴더에서 sandbox 권한 오류가 발생했다. 제품 코드 수정 없이 workspace 내부 cache/basetemp와 pytest cache plugin 비활성화로 해결했다. 기존 API 가상환경에는 lockfile에 선언된 `python-multipart`가 설치되지 않았으며, 직접 `Request.form()` 실행에서도 라이브러리 미설치 AssertionError를 재현했다.

- Root baseline: **59 passed, 4 skipped, 4 deselected**.
- API baseline: **138 passed, 10 skipped, 13 failed**. 실패는 `test_job_uploads.py`의 등록·파일명·MIME·지원 확장자 5종·용량 초과·DB 실패 보상·cleanup 실패·storage 실패·URI 미노출 테스트에서 multipart 파싱이 422를 반환한 것이다. 제품 코드 결함으로 단정하지 않는다. 기존 Starlette의 httpx deprecation warning 1건도 기록한다.
- 실제 Redis URL은 미설정이므로 실 Redis 통합은 미검증이다.

구현 시작 시 기존 lockfile 기준으로 `uv --cache-dir outputs/.uv-cache sync --project services/api --locked`와 root `uv --cache-dir outputs/.uv-cache sync --project . --locked`를 먼저 수행한다. 네트워크/캐시 제한으로 sync하지 못하면 환경 불완전 상태를 보고하고 API full suite를 통과로 표시하지 않는다. 기존 가상환경의 완료된 sync를 확인한 경우에만 다음 제한 환경 대체 명령을 사용한다:

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/api --python 3.13 pytest services/api/tests -q -p no:cacheprovider --basetemp outputs/.verification-w02/api-baseline --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w02/root-baseline --tb=short
```

위 baseline 실제 실행에는 `api-temp`/`root-temp` suffix를 사용했다. 이후 검증은 새 suffix를 사용해 기존 디렉터리를 자동 재귀 삭제하지 않게 한다. `outputs/` cache·검증 산출물은 gitignore 대상이고 제품 산출물과 함께 커밋하지 않는다. 환경 문제로 실패했던 첫 기본 실행(root 35 setup errors, API 61 setup errors)은 대체 경로 실행에서 해소되었다.
