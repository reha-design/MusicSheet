# Pipeline 운영 복구와 단계 진행률 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 구현은 주 에이전트가 수행하고 AGENTS.md에 따라 각 단위를 독립 reviewer가 평가한다.

**Revision:** R1 · 2026-10-06. **상태:** 독립 계획97점·Task1/Task2/전체 구현 각각99점 통과, PR 통합·정리 단계. 리뷰 후 상태/ledger만 갱신하며 리뷰한 실행 내용은 아래 기록의 hash로 식별한다.

**Goal:** PR #11의 운영 복구 및 진행률 기능을 현재 main 구조에 맞춰 통합하고 기존 PR/브랜치를 정리한다.

**Architecture:** 현재 StageSession의 job advisory lock과 mutex/transaction을 재사용한다. 진행률은 active attempt/generation으로 갱신을 제한하고, 운영 종료는 scan 관측값을 잠금 안에서 재검사한 뒤 job/attempt/outbox를 원자적으로 변경한다. 이벤트는 기존 공용 Redis store로 DB commit 후 발행한다.

**Tech Stack:** 기존 Python 3.13, asyncpg, Redis, Celery, pytest, Basic Pitch 독립 Python 3.12 worker 계약.

**Spec:** [R1 설계](../superpowers/specs/2026-10-06-pipeline-operator-tools-design.md). Canonical owner: [Celery](../backend/celery.md), [Job 상태](../domain/job-state.md), [파이프라인](../architecture/job-pipeline.md), [Redis 이벤트](../backend/redis-streams.md).

## Global Constraints

- migration v1/v2, root/API/model 의존성 버전, HTTP API/task/queue/event 저장 계약을 유지한다. 스키마 변경 없음.
- callback 값은 bool 제외 정수 0~99; 최종 100은 runner 완료 transaction이 기록한다.
- scan stale_seconds 기본7200/범위1~2147483647, limit 기본100/범위1~1000. 서버 시간 사용, NULL updated_at 제외.
- 운영 종료는 기존 job lock을 사용하고 관측 timestamp/status/stage/active_attempt_id가 모두 일치해야 한다. 취소는 CANCELED 우선.
- CLI exit0 성공/1인프라/2입력·설정/3무변경. connect2초/command5초, owned cleanup, 상세 예외 비노출.
- 계획과 단위 및 최종 독립 리뷰 각각 >=95이며 미해결 blocker/important 0. 점수는 서로 대체하지 않는다.
- 테스트/보고서/관련 spec 변경은 단위별 atomic commit. 새 PR 병합 후 PR #11과 브랜치 정리. 평가 W05나 옵션 후보를 제품 변경으로 확장하지 않는다.

## Review Focus

1. bool/float/음수/100 진행률과 오래된 callback은 DB 결과를 성공으로 오인하게 만들지 않아야 한다 → Task1 boundary/late callback 테스트.
2. worker 소유권이나 generation이 바뀐 경우 늦은 진행률을 기록하지 않아야 한다 → Task1 stale attempt/generation, 취소 테스트.
3. scan 후 API 취소가 바뀌거나 worker가 활동을 재개한 경우 운영 종료는 관측값 불일치/LOCK_HELD로 거부해야 한다 → Task2 fake + 실제 두 세션 검증.
4. 종료 transaction의 마지막 쓰기나 commit이 실패하면 attempt/job/outbox가 함께 되돌아가야 한다 → Task2 rollback fault injection + 실제 DB transaction 검증.
5. Redis 장애/반복 취소/CLI 오류는 커밋 결과나 자원 회수를 깨뜨리지 않아야 한다 → Task1 event error와 Task2 CLI cleanup/sanitization 테스트.

## 파일 구조

- 수정: `packages/pipeline/musicsheet_pipeline/contracts.py`, `repository.py`, `runner.py`, `basic_pitch/provider.py` — 실행 소유권 안의 진행률 및 기존 session의 운영 종료 전이. Basic Pitch는 callback의 InfrastructureUnavailable을 영구 provider 오류로 변환하지 않는다.
- 수정: `packages/pipeline/musicsheet_pipeline/models.py` — JobObservation/StalledJob/RecoveryResult와 최신 attempt 요약의 독립 데이터 계약. repository와 maintenance가 이 모듈을 공유해 순환 import를 만들지 않는다.
- 생성: `packages/pipeline/musicsheet_pipeline/maintenance.py` — bounded scan, 기존 StageSession을 사용하는 복구 orchestration.
- 생성: `packages/pipeline/musicsheet_pipeline/maintenance_cli.py` — 인자/환경/연결/출력의 CLI 경계. `packages/pipeline/pyproject.toml`에 script 등록.
- 테스트: `tests/pipeline/test_progress.py`, `test_maintenance.py`, `test_maintenance_cli.py`, `support.py`; `services/api/tests/integration/test_operator_tools.py` — guarded live DB/Redis 검증.
- 문서: canonical Celery/Job 상태, pipeline README, main_spec/roadmap/completed-work/backlog, `docs/reports/pipeline-operator-tools-{progress,maintenance,integration}-report.md`.

## Task 1: 현재 attempt의 진행률

**Interfaces:** `StageContext.report_progress: Callable[[int], Awaitable[bool]] | None = None`; `StageSession.report_progress(attempt_id: str, progress: int) -> Transition | None`. 기존 StageContext 생성자의 인자 순서는 보존한다.

- [x] Step1 — `test_progress.py`에 0~99 검증, 반복/역행 무변경, stale id/generation, 취소/최종 상태, 동시 callback, provider 종료 후 호출, DB rollback 및 Redis 실패 테스트를 작성한다. fake는 실제 rollback snapshot을 유지한다.
- [x] Step2 — `uv run --project . --offline --no-sync --python 3.13 pytest tests/pipeline/test_progress.py -q` RED를 확인한다. 없거나 미연결 callback 때문에 실패해야 한다.
- [x] Step3 — canonical owner에 callback 계약을 반영하고 session의 progress 전이, runner callback 연결 및 수명/직렬화, Basic Pitch 처리 이정표 20/70/85/95를 구현한다. callback은 provider가 await한다. 갱신은 RUNNING job/attempt 및 active id/stage/generation을 검증하고 전체 진행률을 감소시키지 않는다.
- [x] Step4 — 집중 progress/runner/repository/Basic Pitch 회귀를 GREEN으로 확인한다. 실제 DB/Redis 테스트에 진행률 commit와 payload 읽기, stale generation 무변경을 추가한다.
- [x] Step5 — 독립 구현 reviewer가 rubric25/25/25/15/10로 >=95 및 지적0을 확인한다. 정확한 리뷰 범위/hash/검증 결과를 progress report와 이 계획에 기록하고 관련 파일만 commit한다.

## Task 2: 운영자 scan 및 안전한 종료 CLI

**Interfaces:** `StalledJob`은 job_id/status/current_stage/updated_at/active_attempt_id 및 최신 attempt 요약을 제공한다. `JobObservation(job_id, status, current_stage, updated_at, active_attempt_id)`는 UUID/enum/aware timestamp를 검증한다. `scan_stalled(connection, *, stale_seconds=7200, limit=100) -> tuple[StalledJob, ...]`; `fail_stalled(connection, observation, *, stale_seconds=7200, event_store=None) -> RecoveryResult`는 changed/reason/transition을 반환한다. `StageSession.fail_stalled(observation, *, stale_seconds) -> RecoveryResult`가 잠금·transaction 경계 안의 전이를 소유한다. 공개 maintenance 모듈은 private session method를 직접 호출하지 않는다.

- [x] Step1 — bounded scan, NULL timestamp, 민감 필드 제외, worker lock, timestamp/status/stage/active id 변경, NOT_FOUND/NOT_STALE/NOT_ELIGIBLE, 취소 승리, 모든 RUNNING attempt 종료 및 미발행 outbox 소비, 완료 이력/아티팩트 보존, commit/마지막 쓰기 rollback, Redis 실패 테스트를 작성한다.
- [x] Step2 — `uv run --project . --offline --no-sync --python 3.13 pytest tests/pipeline/test_maintenance.py tests/pipeline/test_maintenance_cli.py -q` RED를 확인한다.
- [x] Step3 — scan/observation/result와 StageSession 종료 전이를 구현한다. 기존 stage_session lock의 cancellation/cleanup을 재사용하며 generation1 placeholder는 단계 실행을 시작하지 않는다. 새 WORKER_STALLED 고정 오류 메시지로 실패를 기록한다.
- [x] Step4 — `musicsheet-maintenance scan` 및 `fail-stalled` script를 등록한다. 관측 인자5개를 요구하고 null active id는 문자열 none으로 입력한다. `PipelineSettings`는 database만 필요, broker 필수 검사를 호출하지 않는다. Redis 미설정이면 생략한다. help/no-connect, 잘못된 UUID/time/enum/age/limit, secret exception, CLI exit/cleanup을 확인한다.
- [x] Step5 — 집중 테스트와 실제 PostgreSQL 두 세션 lock/CAS/취소/rollback, 기존 메시지의 최종 상태 SKIP 및 실제 Redis terminal payload를 검증한다. root/API 전체 회귀와 `uv lock --check --offline`를 실행한다.
- [x] Step6 — 독립 단위 리뷰 >=95/지적0 후 maintenance report와 계획에 정확한 범위/hash/증거를 기록하고 atomic commit한다.

## 전체 검증·통합

- [x] 전용 Docker PostgreSQL16/Redis7 container를 작업 고유 이름으로 생성하고 DB를 `musicsheet_test` 및 `MUSICSHEET_DISPOSABLE_TEST_DB_V1` marker로 한정한다. 기존 API migration runner로 v1/v2를 명시적으로 적용한다. 다른 DB/container는 변경하지 않는다.
- [x] live: `uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests/integration/test_operator_tools.py -q -ra`를 전용 URL 설정으로 실행하며 skip0을 요구한다. Redis key는 생성 job UUID만 삭제한다. DB marker가 없으면 쓰기를 거부한다.
- [x] root: `uv run --project . --offline --no-sync --python 3.13 pytest tests -q -ra -m 'not ml_integration and not celery_integration'`; API: `uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests -q -ra`. 환경 부재 skip과 실제 검증을 구분한다.
- [x] Linux에서도 변경된 순수 async/DB 코드의 회귀를 실행하고, 실제 Celery 실행은 기존 검증과 이번 검증을 혼동하지 않는다. 추가 라이브러리/모델 설치를 하지 않는다.
- [x] 전체 독립 리뷰 >=95/지적0과 report/main_spec 색인을 확인한다. PR #11 head `2bc50a12ea704dd6580fcd7827b03602b2d71337`의 후보 중 두 기능을 통합했고 timeout 설정 노출/손상 event 건너뛰기는 계약 대안으로 후속 후보라는 처리를 보고서에 기록한다.
- [ ] commit/push/새 PR 생성 후 attach_artifact, 최신 diff/check 확인 및 병합. main을 fast-forward로 동기화하고, 새 구현 보존을 확인한 뒤 PR #11 close와 원격 redis branch 삭제. main clean 및 열린 PR/남은 branch를 확인한다.
- [ ] 이 작업의 container·임시 환경은 소유한 이름/절대 경로를 확인하고 정리한다. 최종 보고에 실제 검증 결과와 제한을 명시한다.

## Gate / Ledger

아래는 리뷰한 R1 실행 내용의 fingerprint와 이후 상태 기록이다. 자체 추정 점수는 없다.

- R1 독립 계획 reviewer `/root/operator_tools_plan_review`, 2026-10-06: **97/100** (25+19+20+24+9), blocker0/important0.
- 리뷰한 실행 계획 SHA256(이 상태/ledger 추가 전): `CB7BB58B669125126468241A6445ABF5D785FF3800C125DA537DB67E6BF277FC`; 설계 R1: `4A74C4DCCE868C19E91D60D71DBC319F36CB039143EF1E376B6C8B68A9715D18`.
- minor3 처리: 최신 attempt는 started_at DESC NULLS LAST/id DESC로 결정하고 실제 DB 필터·정렬·limit 검증에 eligible/terminal/NULL을 함께 넣는다. Linux 경로/명령/runtime fingerprint는 통합 보고서에 남긴다. 기존 요구와 인터페이스를 바꾸는 사항은 아니다.
- 실행 방식: 사용자 `이후작업 진행`에 따라 현재 session에서 주 에이전트가 실행하며, 단위별 독립 review는 사용자 AGENTS.md 요구를 적용한다.
- Task1 완료: RED23fail → 집중89pass(Windows/Linux), 실DB/Redis1pass·skip0, root334pass/11skip/14deselected, API232pass/26skip. `/root/operator_progress_review` 독립 **99/100** (25+25+24+15+10), 2026-10-06, 미해결 지적0. 범위/hash/minor처리는 [progress report](../reports/pipeline-operator-tools-progress-report.md) 참조.
- Task2 최초 독립94점 (23+24+23+15+9), important1: outer transaction의 savepoint 해제 후 terminal event를 발행하는 문제를 실제 DB에서 재현. R1 commit 후 발행 요구를 지키기 위해 idle connection 조건을 공개 maintenance/session 경계에서 강제했고 RED2fail/GREEN2pass 및 실DB1건을 추가했다. signature/schema/범위 변경은 없다. 수정 후 집중121pass(Windows/Linux), 실DB8pass/skip0, root394pass/11skip/14deselected, API232pass/33skip. 독립 재리뷰 **99/100** (25+25+24+15+10),2026-10-06, 미해결 지적0; [maintenance report](../reports/pipeline-operator-tools-maintenance-report.md)에 범위/hash/처리 기록.
- 전체 `/root/operator_final_integration_review`,2026-10-06: 독립 **99/100** (25+25+24+15+10), 미해결 blocker/important/minor0. base1b3a1e3 → HEAD26d5028 + staged문서5개,24파일/+1596/-9, binary diff SHA256 `88c179f9f92b5ebd249b6b0c41458c99f211da8123fed6be178a2b3da06ad07d`. 독립 집중149pass 및 실DB8pass/skip0, progress→운영거부→취소→최종상태 연속 probe 통과. 정확한 범위/fingerprint는 [통합 보고서](../reports/pipeline-operator-tools-integration-report.md) 참조. 이후 변경은 상태/ledger 및 완료 색인이다.

Baseline: Windows root **308pass/11skip/14deselected**, API **232pass/25skip** (2026-10-06). root DB opt-in2 skip, Linux 경계4 및 symlink5 skip; API DB/Redis opt-in25 skip. API는 기존 deprecation/cache 경고2개. Docker29.7.2 사용 가능.
