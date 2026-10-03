# W03 Task3 — Celery·dispatcher·API 원자성 보고서

- 날짜2026-10-03 (Asia/Seoul), 기준 `1d9898f`, branch `codex/celery-orchestration`
- 계획R3 독립99점, Task1/Task2 각 독립99점 통과 후 착수.
- 범위: secret-safe 설정, Celery factory/여섯 task/owned runtime, outbox dispatcher·publisher·CLI, API 최초 예약 및 테스트·명령 문서.
- 구현 독립 리뷰 R1: 2026-10-03 `/root/w03_dispatch_review`, 기준1d9898f 이후Task3 전체 **92/100** (22+24+22+14+10), blocker0/important2/minor0. R2 최신Task3 전체 **99/100** (25+25+24+15+10), blocker0/important0/minor0. Task3 완료, Task4 미착수.

## 구현

API는 YouTube job 또는 upload job+artifact와 같은 연결·트랜잭션으로 DOWNLOAD generation1을 등록한다. 공개 응답은201/PENDING이며 broker client를 만들지 않는다. 예약 실패는 DB rollback, 업로드 파일 best-effort 삭제로 연결된다. 업로드 metadata 커밋 후 caller 취소는 파일과 outbox를 보존한다. low-level JobRepository.create_job은 자동 예약하지 않는다.

dispatcher는 available_at 도래 outbox 한 행씩 FOR UPDATE OF o SKIP LOCKED로 소유한다. CPU I/O·AI·render 큐에 outbox ID를 task_id로 보내고 발행 성공 후 published_at을 커밋한다. publish/commit 실패는 고정 예외와 pending 행을 남긴다. terminal3종은 전송 없이 완료 표시하며 CANCEL_REQUESTED는 전달해 worker가 확정한다. thread 발행은 반복 cancellation에도 소유자가 drain한다.

Celery factory는 앱별 독립 task와 runtime을 등록한다. 초기 eager 테스트에서 Celery shared task가 다른 앱의 factory를 덮어쓰는 실패를 관찰하고 closure 진단으로 원인을 확인해 shared=False/lazy=False로 분리했다. task는 asyncio.run으로 자원을 열고 닫으며 DB/busy 장애를 고정 예외5초 무제한 retry로 바꾼다. retry publish 실패는5초 대기 후 Reject(requeue=True). 커밋 후 runtime 정리 실패는 고정 경고이며 계산을 재실행하지 않는다. import는 소켓/API/모델을 열지 않는다.

CLI는 once·연속 poll·유한 recover-pending 모드를 제공한다. 잘못된 flags/URLs와 의존성 오류는 고정 출력·반환코드, credentials repr 은닉을 적용한다. cleanup 및 중단도 소유한 자원을 정리한다. 제품 provider registry는 여전히 비어 있다.

## 검증

신규 설정/dispatcher/CLI 부재 RED3 collection errors, API 최초 예약 부재 RED4, eager runtime 공유 오류 RED1을 실제 관찰했다. API harness의 추가 SQL 지원 및 기존 INSERT 순서 기대값을 갱신했다.

- root full **209 passed/4 skipped/4 deselected** (`t3-review-root`)
- API full **229 passed/21 skipped/기존 Starlette warning1** (`t3-review-api`)
- root/API lock checks 통과, script metadata offline locked sync로 설치.
- eager 여섯 stage, 앱별 runtime/queue 격리, runtime cleanup 실패, retry/requeue 예외와 delay, publish/commit 장애의 동일 task ID 재전달, 동시 row 소유·skip, 반복cancel drain, cancel-before-dispatch, 미래예약, CLI subprocess 설정 오류·의존성 실패·유한 모드·poll cancel, API rollback/committed cancellation 검증.

실DB/Redis 및 실제 Linux worker 실행은 URL unset/Windows 환경으로 미검증이다. eager와 persistence double은 실제 broker ACK/redelivery 성공을 대신하지 않는다. 실제 provider/YouTube 테스트는 후속 범위다.

R1 지적 처리: 실제 Celery send_task가 선택적 backend.on_task_call을 broker 전송 전에 실행함을 RED(backend 호출1)로 관찰했다. publisher에도 ignore_result=True를 적용하고 backend0·JSON payload·전송1을 검증했다. '~/outputs'가 API의 cwd/~와 다른 사용자 home으로 해석되는 RED도 확인해 worker 설정의 expanduser를 제거했다. API·worker relative 경로3종 비교를 추가했다. 최신 full root **211 passed/4 skipped/4 deselected** (`t3-rereview-root`), API **232 passed/21 skipped/기존 warning1** (`t3-rereview-api`).
