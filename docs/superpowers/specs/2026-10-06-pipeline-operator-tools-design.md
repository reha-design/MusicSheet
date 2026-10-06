# Pipeline 운영 복구와 단계 진행률 설계

**Revision:** R1 · 2026-10-06 · 기준 main `1b3a1e3fab426f8456ef9de630547b8fae315e4d`.

사용자는 PR #11 검토 후 `이후작업 진행`으로 필요한 기능의 통합과 브랜치 정리를 요청했다. 목적은 현재 실행 구조에서 멈춘 작업을 운영자가 안전하게 종료하고, 실제 provider의 단계 내부 진행 상황을 보여주는 것이다. 이번 범위는 이 두 기능이다. 기존 API 내부 chain 구현을 채택하는 대신 현재 `packages/pipeline`의 outbox, generation, active attempt, job 잠금, 공용 이벤트 저장소를 사용한다. API와 worker를 두 실행 구조로 병행하는 방식은 작업 이름·큐·DB 계약의 충돌을 남기므로 채택하지 않는다.

## 실행 구조와 경계

- Python 3.13 backend, 기존 Python 3.12 Basic Pitch worker와 의존성 버전을 유지한다. 모델이나 새 라이브러리를 설치하지 않는다.
- 현재 migration v1/v2, HTTP API, `pipeline.tasks.*`, 세 큐, `payload` Redis 필드와 SSE `progress`/`stream_error` 계약을 유지한다. 추가 컬럼이 필요하지 않으므로 migration은 추가하지 않는다.
- 구현은 현재 checkout의 `codex/pipeline-operator-tools` 브랜치에서 주 에이전트가 수행한다. 사용자 AGENTS.md에 따라 계획 및 각 구현 단위를 독립 reviewer가 평가한다.

## 1. 단계 내부 진행률

`StageContext`에 선택적 async callback `report_progress(int) -> bool`을 추가한다. 기존 직접 생성자는 callback 없이도 동작한다. runner가 실제 실행 중인 attempt에 callback을 연결하며 provider는 callback을 await하고 실행 종료 후 보관해 호출하지 않는다.

- 값은 bool을 제외한 정수 0~99다. 100은 결과 검증·DB 완료 후 runner만 기록한다.
- job이 RUNNING이고 현재 stage/active_attempt_id가 일치하며 attempt가 RUNNING이고 message generation과 현재 예약 generation이 일치해야 갱신한다.
- 동일하거나 낮은 진행률, 이전 attempt/generation, 취소 요청·최종 상태, provider 종료 후 callback은 false를 반환하고 DB/SSE를 변경하지 않는다.
- 같은 실행의 동시 callback은 직렬화한다. 진행률은 단계 내에서 증가하고 전체 진행률은 `max(기존 값, (stage_index * 100 + progress) // 6)`로 감소하지 않는다.
- 기존 job advisory lock과 session mutex, DB transaction으로 저장한 뒤 공용 event store에 발행한다. Redis 실패는 커밋된 DB 상태를 취소하거나 provider를 재실행하지 않는다. DB 연결·소유권 장애는 기존 InfrastructureUnavailable 경계를 사용한다.
- Basic Pitch는 입력 준비 완료 20, 모델 실행 완료 70, 결과 검증 완료 85, 파일 저장 완료 95의 처리 이정표를 보고한다. 이는 시간 비율이나 전사 정확도가 아니다. DB 결과 공개·다음 단계 예약 전에는 100이 되지 않는다.

## 2. 운영자 복구

새 root workspace 명령 `musicsheet-maintenance`에 `scan`과 `fail-stalled`를 제공한다. 모델·Celery worker 실행이나 broker 발행은 하지 않는다.

### 조회

`scan --stale-seconds 7200 --limit 100`은 PostgreSQL 서버 시각 기준으로 오래된 PENDING/RUNNING/RETRYING/CANCEL_REQUESTED를 조회한다. stale-seconds는 정수 1~2147483647, limit은 정수 1~1000이며 기본값은 각각 7200/100이다. 최대 limit만큼 updated_at/id 순서로 반환한다. updated_at이 NULL인 행은 제외한다.

출력은 job_id, status, current_stage, updated_at, active_attempt_id와 최신 attempt의 stage/number/generation/status/error_code다. source URL, artifact URI, DB 접속값 또는 예외 원문을 출력하지 않는다. scan 자체는 DB 상태를 쓰지 않는다.

### 종료

`fail-stalled`는 scan의 `--job-id`, `--observed-updated-at`, `--observed-status`, `--observed-stage`, `--observed-attempt-id`를 필수로 받는다. 마지막 값은 UUID 또는 active attempt가 없음을 뜻하는 `none`이다. `--stale-seconds` 기본값은 7200이며 scan과 같은 값을 사용해야 한다.

- 기존 StageSession의 job advisory lock을 비차단 획득한다. worker가 잠금을 가지고 있으면 LOCK_HELD로 무변경 종료한다.
- 같은 DB transaction에서 row lock을 얻고 관측한 timestamp/status/stage/active_attempt_id가 정확히 같은지, 여전히 오래됐는지 확인한다. NOT_FOUND / OBSERVATION_CHANGED / NOT_STALE / NOT_ELIGIBLE이면 무변경이다.
- 관측 상태가 CANCEL_REQUESTED면 CANCELED, 나머지 비종료 상태면 FAILED/WORKER_STALLED로 종료한다. 활성 RUNNING attempt들을 같은 transaction에서 FAILED로 닫고 active_attempt_id를 지운다.
- 미발행 outbox는 같은 transaction에서 published_at을 채워 더 이상 발행 대상으로 두지 않되 이력은 삭제하지 않는다. 이미 broker에 있는 메시지는 최종 job 상태에 의해 실행을 건너뛴다. 관측 후 취소가 바뀌면 먼저 재조회해야 하며 취소 요청을 FAILED로 덮어쓰지 않는다.
- job/attempt/outbox 중 쓰기나 commit이 실패하면 전체를 rollback한다. artifact와 완료된 attempt는 삭제하지 않는다.
- DB commit 후 기존 Redis event store로 최종 이벤트를 best effort 발행한다. 이벤트 실패는 DB 종료 결과를 뒤집지 않는다.

CLI는 연결 timeout 2초, DB command timeout 5초 및 기존 owned cleanup을 사용한다. CLI 성공 exit 0, 인프라 실패 1, 잘못된 입력/설정 2, 무변경 종료 3이다. 도움말은 서비스 연결 없이 제공한다. 유효하지 않은 인자와 driver 오류는 고정된 진단만 출력한다. DB만 설정해도 명령을 사용할 수 있고 REDIS_URL이 없으면 이벤트 발행을 생략한다.

## 검증과 정리

단위 테스트는 실제 상태 snapshot/rollback을 가진 기존 fake를 확장하고, 동일 job에 대한 실제 PostgreSQL 두 세션의 잠금·관측값 재검사와 Redis 이벤트 읽기를 별도로 검증한다. 실제 서비스 검증은 이 작업에서 만든 전용 DB/Redis container에서만 실행하며 PostgreSQL disposable marker 확인이 필수다. 기존 root/API 회귀를 실행하고 소유 container와 임시 결과만 정리한다.

새 구현의 계획·단위·최종 리뷰가 95점 이상이고 미해결 blocker/important가 없을 때 PR을 생성·병합한다. PR #11의 소스 commit과 보존/대체한 기능을 추적 가능한 보고서에 남긴 뒤 기존 PR을 닫고 원격 브랜치를 정리한다. `CELERY_VISIBILITY_TIMEOUT` 노출과 손상 Redis entry 건너뛰기는 현재 계약을 유지하며 선택적 후속 후보로 기록한다. W05 평가 작업은 이번 범위에 추가하지 않는다.
