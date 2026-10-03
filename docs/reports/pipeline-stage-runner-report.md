# W03 Task2 — provider 실행·무결성·취소·이벤트 보고서

- 날짜: 2026-10-03 (Asia/Seoul), 기준 `83915c7`, branch `codex/celery-orchestration`
- 계획 R3 독립99점, Task1 최신 독립99점 통과 후 착수.
- 범위: provider protocol/빈 registry, stage runner, thread 기반 streaming 무결성 검사, W02 이벤트 저장소 공유·API 호환 exports, 회귀 테스트.
- 구현 독립 리뷰 R1: 2026-10-03 `/root/w03_runner_review`, 기준83915c7 이후 Task2 전체, **94/100** (23+22+24+15+10), blocker0/important1/minor1. R2 최신 Task2 전체 **99/100** (25+25+24+15+10), blocker0/important0/minor0. Task2 완료, Task3 미착수.

## 동작과 경계

RUN 입력은 소비자 input_roles와 DB reference·실제 SHA/size를 검증한다. provider는 target_instrument·source·저장소·취소 Event를 받으며, DB reference snapshot과 별도 복사한 입력을 전달한다. 출력은 job/UUID/role/producer/version/고유 ID/attempt filename을 검사한다. 업로드 입력의 정확한 재사용은 원본 생산자를 유지하고 metadata를 중복 등록하지 않는다. provider retryable만 durable5·10초 예약하고 최초 포함3회로 끝낸다. deadline1800초는 provider에 적용하며 일반 실패·손상·timeout은 terminal FAILED다.

검증은 소유한 to_thread task에서 최대64KiB씩 읽고 stream을 finally 닫는다. stop Event는 새 read를 막으며 shield/drain은 반복 caller cancellation에도 thread를 끝까지 수거한다. 진행 중 OS read의 강제 중단을 보장하지 않는다. 취소/소유권 감시는 입력·완료 출력·신규 출력 검증과 provider 전체에서 동작한다. DB 연결 상실 뒤 provider를 취소·수거하고 commit을 금지한다. 취소와 완료의 최종 판단은 DB transaction에서 한다.

W02 Redis store 구현은 pipeline.events로 이동하고 API 공개 경로는 호환 re-export한다. timeout monkeypatch만 공유 모듈로 갱신했다. DB commit 뒤 이벤트를 발행하며 Redis 실패는 계산 재실행이나 DB rollback을 유발하지 않는다. 이벤트 전파 중 caller 취소는 그대로 전파한다.

## 검증 증거

신규 runner/artifacts 모듈 부재3 collection errors와 공유 events 모듈 부재를 RED로 관찰했다. 추가 RED는 DB artifact ID 충돌이 runner 밖으로 탈출하는 문제와 provider 입력 변이가 DB 원본 재사용 판정을 바꾸는 문제를 실제 재현하고 각각 실패 전이·독립 snapshot으로 수정했다.

full root **171 passed/4 skipped/4 deselected** (`t2-review-root`), API **224 passed/21 skipped/기존 Starlette warning1** (`t2-review-api`), root/API offline lock check 및 diff check 통과. 느린 read 회귀12개는 input/completed/new-output 각각 취소·연결 상실·외부 단일/반복 취소를 고정한다. finally에서 test-owned read를 release하고 close1·남은 asyncio task0·성공 metadata/후속 예약0을 확인했다. real LocalStorage+DB persistence double을 사용하며 실SQL 또는 실제 YouTube/AI/렌더 실행 증거를 대신하지 않는다.

실DB/Redis URL 미설정에 따른 skip 제한을 유지한다. Celery task adapter·dispatcher·API 자동 등록 연결은 Task3에서 진행한다.

R1 지적 처리: storage의 실제 InterruptedError까지 내부 취소로 오인해 RUNNING이 남는 문제를 open/read/close3개 RED로 재현했다. 내부 전용 `_ValidationStopped`로 분리해 실제 파일 오류는 ARTIFACT_INVALID 실패로 기록한다. minor의 이벤트 실패 경고도 고정 메시지만 기록하고 sentinel 비노출 회귀 RED→GREEN을 확인했다. 최신 full root **174 passed/4 skipped/4 deselected** (`t2-rereview-root`), API **224 passed/21 skipped/기존 warning1** (`t2-rereview-api`).
