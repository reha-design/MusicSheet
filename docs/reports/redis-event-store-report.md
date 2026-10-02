# W02 Task 1 — Redis 이벤트 저장소

> 2026-10-02 · 계획 Revision 2 (독립 리뷰 100/100, 사용자 승인) · 구현 독립 리뷰 99/100 통과

`musicsheet_api.events.RedisEventStore`가 검증된 `JobProgressEvent`를 JSON payload로 작업별 Stream에 저장한다. 발행 반환값은 Redis ID이며 `MAXLEN ~ 100`을 사용한다. 첫 읽기는 cursor 미래 여부를 `XINFO STREAM last-generated-id`로 확인한 뒤 비차단 exclusive XREAD를 수행한다. 후속 읽기는 최대 100개씩 BLOCK 읽기한다.

UUID 정규화, u64 ASCII cursor 경계, bytes/text 응답, payload job 일치와 이벤트 순서를 검증한다. 모든 Redis 작업의 timeout은 유한하다. 잘못된 mutable Pydantic 모델도 warning 원문 없이 재검증하며 외부 오류는 일반 메시지로 표현한다. cancellation은 전파하고 공용 client를 닫지 않는다. PostgreSQL 변경이나 REST 이벤트 발행, SSE router는 이 단위에 포함하지 않는다.

## 검증 증거

- RED: `test_event_store.py` 실행 → 아직 없는 `musicsheet_api.events` import로 collection 실패.
- GREEN: API full suite **192 passed, 10 skipped**, 기존 Starlette httpx deprecation warning 1건. 새 이벤트 저장소 테스트는 41개다.
- Root regression **59 passed, 4 skipped, 4 deselected**; `git diff --check` 통과.
- 명령 공통: `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project <services/api 또는 .> --python 3.13 pytest ... -q -p no:cacheprovider --basetemp outputs/.verification-w02/<api-task1 또는 root-task1> --tb=short`.
- 기존 lockfile 기준 API sync를 실행해 누락된 `python-multipart==0.0.32`를 설치했다. 제한된 network 실행은 socket 권한 오류로 실패했고 승인된 sandbox escalation 실행으로 동기화를 마쳤다. 의존성 선언/lockfile 변경은 없다.
- 실제 Redis 통합은 Task 3에서 검증한다. 현재 `MUSICSHEET_TEST_REDIS_URL`은 미설정이다.

## 실행 기록과 판단

Task 1 BASE: `36588ac`. 승인된 미커밋 W02 설계/계획/색인 변경을 동일 작업 폴더에서 이어간다. `Ruling: 기존 작업 폴더 유지 — 승인된 W02 문서와 구현을 같은 범위로 이어가기 위함 — 격리 경계를 잘못 판단하면 같은 checkout 변경이 섞일 수 있으므로 W02 파일만 명시적으로 stage한다.`

Plan preflight: Task 1 EventStore protocol을 Task 2가 그대로 사용하며 Task 3은 실제 Redis를 같은 loop에서 생성·종료한다. public signature와 단계 의존성 충돌 없음. 단위별 독립 리뷰와 점수 기록은 AGENTS.md를 따라 수행한다.

## 독립 리뷰

2026-10-02 `/root/w02_store_review`: **99/100** (외부 동작 25/25, 오류·보안 25/25, 검증 24/25, 구조 15/15, 문서 10/10). Blocker/important 없음. 독립 focused suite 41 passed, 추가 UTF-8/부분 손상 batch/다른 key/101개 batch/publish 및 metadata cancellation probe 6개 통과.

Minor deferred: 독립 probe 일부를 영구 pytest로 남기는 회귀 보호 확장. 현재 동작 검증은 통과했으며 후속 기능을 막는 결함으로 평가하지 않았다.
