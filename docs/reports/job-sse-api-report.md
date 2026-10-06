# W02 Task 2 — 진행 이벤트 SSE API

> 2026-10-03 · 계획 Revision 2 (100/100, 사용자 승인) · 구현 독립 리뷰 98/100 통과

`GET /api/v1/jobs/{job_id}/events`를 연결했다. UUID와 단일 `Last-Event-ID`를 검증한 뒤 PostgreSQL 작업 존재와 Redis 첫 batch를 확인하고 SSE 응답을 시작한다. 최초 접속은 `0-0`, 재접속은 지정 ID 이후의 보존 이벤트를 전달한다. `progress` 프레임은 JSON 개행 escape를 사용하며 heartbeat와 시작 후 일반화된 `stream_error`를 지원한다.

별도 `SSEStreamingResponse`는 ASGI 버전과 무관하게 disconnect를 감시하여 BLOCK read 중에도 pending task를 취소·정리한다. stream은 terminal event 후에도 유지되며 클라이언트가 REST terminal 상태를 확인한 뒤 닫는다. 요청은 공유 Redis client를 닫지 않는다.

앱 lifespan은 health provider 주입과 Redis 초기화를 분리하고 event store를 연결한다. 유한 socket timeout과 decode 설정을 적용했으며 종료 시 DB close 오류가 있어도 Redis를 한 번 닫고 state 참조를 해제한다. 기존 readiness test double의 from_url signature는 새 kwargs를 받을 수 있게 맞췄다.

## 검증

- RED: 새 streaming 모듈 미구현으로 `test_job_events.py` collection 실패.
- GREEN API full suite: **221 passed, 10 skipped**, 기존 Starlette httpx deprecation warning 1건.
- Root: **59 passed, 4 skipped, 4 deselected**. `git diff --check` 통과.
- workspace uv cache와 `--offline --no-sync`, pytest `-p no:cacheprovider`, 전용 basetemp `api-task2`/`root-task2`를 사용했다. Task 1에서 기존 lock 의존성 sync를 마쳤다.
- 직접 ASGI 테스트가 exclusive replay, replay 중 후속 이벤트, 두 독립 구독자, heartbeat, terminal 유지, 404/422/503, 프레임·header, 초기/중간 오류 원문 비노출을 검증한다.
- ASGI 2.3/2.4 BLOCK read 중 disconnect, response task cancellation, body send 실패 후 listener/async generator 정리와 앱 종료 close를 확인했다.
- 실제 Redis와 PostgreSQL을 연결한 end-to-end 검증은 이 단위 증거에 포함하지 않는다.

## 리뷰와 실행 기록

Task 2 BASE `c1ca195`. EventStore protocol과 Step별 산출물은 승인 계획 그대로 사용했다. 2026-10-03 `/root/w02_sse_review`: **98/100** (25/25, 25/25, 23/25, 15/15, 10/10). 미해결 blocker/important 없음. 독립 API221/root59 검증 및 receive 실패/await 중 send disconnect/heartbeat cursor/initial_read 취소 probe 4개 통과, pending task 없음.

Minor: 실제 store/client가 연결된 lifespan에서 요청 종료 close0·앱 종료 close1을 한 시나리오로 검증하는 회귀 보호를 Task 3에서 보강한다.
