# W02 Redis Streams 및 SSE 구현 보고서

> 2026-10-03 · 계획 Revision 2 · Task 1–3 완료, 전체 최종 독립 리뷰 98/100 통과 · 실제 Redis 성공 경로 미검증

## 결과와 범위

작업 진행 이벤트를 Redis Streams에 저장하고 `GET /api/v1/jobs/{job_id}/events`로 전달한다. `Last-Event-ID` 이후 보존된 이력과 새 이벤트를 같은 cursor로 이어 읽는다. 최초 구독, heartbeat, 일반화된 초기/중간 실패, disconnect/cancellation 및 앱 공용 client의 종료 책임을 구현했다.

기존 `JobProgressEvent`와 API-local Redis 의존성을 사용했다. 새 runtime dependency, 공용 schema, DB schema, root/API lockfile 변경은 없다. REST 등록·취소와 실제 worker 발행은 W03 연결 범위이며 입력 자동 처리나 Basic Pitch 제품 연결은 아직 없다.

## 점수 게이트

| 날짜 | 대상/범위 | 독립 reviewer | 점수 | 지적 처리 |
| :--- | :--- | :--- | :---: | :--- |
| 2026-10-02 | 계획 Revision 1 | `/root/w02_plan_review` | 94/100 | 모델 warning 원문 누출 important, BLOCK 관측과 asyncio 방식 minor → Revision 2 수정 |
| 2026-10-02 | 계획 Revision 2 | `/root/w02_plan_review` | 100/100 | 모두 해소, 사용자 승인 후 구현 |
| 2026-10-02 | Task 1, BASE `36588ac` | `/root/w02_store_review` | 99/100 | blocker/important 없음, 일부 probe의 영구 회귀 테스트 확장은 minor deferred |
| 2026-10-03 | Task 2, BASE `c1ca195` | `/root/w02_sse_review` | 98/100 | blocker/important 없음, 요청 종료 close0·앱 종료 close1의 연결 검증은 Task 3에서 추가 |
| 2026-10-03 | Task 3 초기 리뷰, BASE `f675ec9` | `/root/w02_integration_review` | 99/100 | blocker/important 없음. CLIENT LIST 호출에도 남은 1초 deadline을 적용하는 minor를 수정 |
| 2026-10-03 | Task 3 수정본 | `/root/w02_integration_review` | 100/100 | minor 해소. 독립 SlowPublisher probe 1.005초 TimeoutError 확인. 미해결 blocker/important/minor 없음 |
| 2026-10-03 | W02 전체, BASE `36588ac`부터 모든 구현/테스트/문서 | `/root/w02_final_review` | 98/100 | 25/25, 25/25, 23/25, 15/15, 10/10. blocker/important 없음. 실제 서버 증거와 일부 영구 회귀 테스트 공백은 각 1점 반영 |

최종 reviewer는 API222/skip17, root59/skip4/deselected4, lock/diff checks 및 추가 손상응답·UTF-8·batch·publish/metadata 취소 probe 8개를 독립 검증했다. pending task 없음. 실제 Redis/PostgreSQL 및 두 서버 조합의 성공 경로는 환경 미설정으로 판정을 보류했다. 계획 점수를 코드 리뷰로 대신하지 않는다.

## 검증 증거와 재현

- Task 1 RED: 이벤트 모듈 부재로 focused collection 실패; GREEN API192/root59.
- Task 2 RED: streaming 모듈 부재로 focused collection 실패; GREEN API221/root59.
- Task 3 현재 API 전체: **222 passed, 17 skipped**, 기존 Starlette httpx deprecation warning 1건. Skip은 PostgreSQL 10개와 실 Redis 7개다.
- Root **59 passed, 4 skipped, 4 deselected**; root/API offline lock checks 및 `git diff --check` 통과. 선택형 Redis 단독 명령도 **7 skipped**로 확인했다.
- 잘못된 test URL을 명시한 negative subprocess probe는 skip 대신 고정 일반 오류로 실패했고 credential sentinel은 출력되지 않았다. 서버 접속 없이 설정 실패 경로를 확인한 증거이며 실제 Redis 성공 경로와 구분한다.
- Task 3 helper deadline 지적은 느린 CLIENT LIST fault probe에서 재현했다: 수정 전 1.317초로 1초 제한 assertion 실패, 수정 후 남은시간 wait_for로 1.010초 종료·assertion 통과. 수정 후 API222/skip17을 재확인했다. 이 probe 역시 실 서버 성공 검증을 대신하지 않는다.
- 실제 store와 앱 lifespan을 연결하는 `test_event_request_does_not_close_client`를 추가했다. Redis I/O boundary double을 사용하되 route/JSON/model/store/streaming/lifespan은 실제 코드다. 요청 종료 close0, 앱 종료 close1을 같은 시나리오에서 확인했다.
- `MUSICSHEET_TEST_REDIS_URL` 미설정: 실제 Redis 서버 실행 증거는 **미검증**이다. 인프라를 임의로 시작하지 않았다. live PostgreSQL/Redis 조합도 실행하지 않았다. 구현 완료와 실 서버 검증을 구분한다.
- 기존 lock 기준 uv sync로 API 환경의 누락된 `python-multipart`를 복구한 뒤 검증했다. 제한된 network에서 처음 실패했고 sandbox escalation 후 기존 lock package 설치가 성공했다.
- 제한 환경 명령은 workspace uv cache, `--offline --no-sync`, pytest `-p no:cacheprovider` 및 매 실행 새 workspace basetemp를 사용한다. 기본 명령과 전제는 [실행 계획](../plans/redis-streams-sse-implementation-plan.md)에 기록했다.

실 Redis 선택 명령:

```powershell
uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_redis_events.py -m redis_integration -q
```

테스트는 UUID 키만 생성·삭제하고 FLUSHDB/FLUSHALL을 호출하지 않는다. CLIENT LIST에서 고유 이름의 blocked XREAD를 관측한 후 발행한다. URL 미설정이면 skip하고 명시 설정 후 실패는 generic failure다. 모든 client가 같은 event loop에서 생성·종료된다.

## 운영 제약과 후속 작업

PostgreSQL이 최신 상태 원본이다. 클라이언트는 접속/재접속 시 REST snapshot을 동기화하고 이전 timestamp의 재생 이벤트로 새 상태를 덮지 않는다. Stream trim/삭제로 누락된 중간 이벤트는 복원할 수 없다. terminal 여부를 REST에서 확인한 클라이언트가 연결을 닫는다.

상태 영속화와 XADD는 원자적이지 않으며 outbox는 없다. 작업별 `MAXLEN ~ 100`만 있고 작업 수에 따른 총 용량 제한/TTL 정리는 후속 운영 작업이다. 다음 제품 연결은 W03 Celery 오케스트레이션이다.

## 실행 판단과 남은 minor

`Ruling: 기존 checkout에서 승인된 문서와 구현을 이어가고 codex/redis-streams-sse 브랜치를 생성했다 — 기존 문서 변경을 보존하고 파일별 stage로 범위를 관리하기 위함 — 격리 판단이 틀리면 같은 checkout에 변경이 섞일 수 있다.`

Deferred minor: Task 1 reviewer가 별도 확인한 UTF-8/응답구조/batch상한/publish 및 metadata cancellation probe 일부를 영구 회귀 테스트로 추가하는 확장. 현재 독립 probe 6개는 통과했다. Task 2의 close 소유권 검증 minor는 Task 3 테스트에서 해소했다.

## 커밋

- Task 1 `c1ca195` — `feat(events): add Redis progress event store`.
- Task 2 `f675ec9` — `feat(api): stream job progress with SSE replay`.
- Task 3/최종 검증·문서 커밋: `test(events): verify Redis replay and document SSE operations`. 자기 commit hash는 본문에 자기참조로 넣지 않으며 `git log`에서 해당 제목으로 확인한다. 위 두 기능 커밋이 주요 코드 변경이다.
- 승인된 계획에 따라 `codex/redis-streams-sse` 로컬 브랜치에 유지한다. push/PR/merge는 수행하지 않았다.
