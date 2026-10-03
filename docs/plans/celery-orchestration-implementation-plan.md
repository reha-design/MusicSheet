# W03 Celery Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 구현은 주 에이전트가 수행하고 각 단위의 독립 reviewer를 별도로 사용한다. AGENTS.md의 단위별 95점 게이트를 유지한다.

**Goal:** 등록·단계 예약과 PostgreSQL 실행 이력을 원자적으로 연결하고, Celery CPU/AI 큐에서 재시도·멱등 실행·취소를 처리한다.

**Architecture:** `packages/pipeline`의 독립 패키지가 실행 계약과 저장소·dispatcher·Celery task를 제공한다. API는 같은 DB 연결에서 최초 outbox만 등록한다. worker는 job advisory lock과 attempt ID 비교를 통해 결과를 저장하고 다음 단계를 예약한 후 W02 이벤트를 발행한다.

**Tech Stack:** Python 3.13, uv, asyncpg, Redis, Celery 5.6 계열, PostgreSQL 16, pytest, 기존 LocalStorage.

**Spec:** [승인 설계 Revision 1](../superpowers/specs/2026-10-03-celery-orchestration-design.md), [Celery](../backend/celery.md), [DB](../backend/database.md), [상태](../domain/job-state.md), [파이프라인](../architecture/job-pipeline.md).

- Plan Revision: 3 (2026-10-03, Asia/Seoul)
- 기준: `4c86e91`, branch `codex/celery-orchestration`
- 사용자 설계 승인: 2026-10-03 `w03진행`
- 독립 계획 점수: R1 94 → R2 100 → R3 **99/100**, blocker0/important0/minor1(과거 상태 문구, 아래에 해결 기록). 관련 의존성 변경 게이트 통과.
- 작성된 실행 계획의 사용자 실행 승인: 2026-10-03 `다음 task 진행`. Task1·Task2·Task3 완료(각 독립 구현99점), Task4 진행 예정.

## Global Constraints

- backend Python `>=3.13,<3.14`; Basic Pitch Python 3.12 환경은 변경하지 않는다.
- `celery[redis]>=5.6,<6`, asyncpg `>=0.31.0`, Redis **`>=6.4.0,<6.5`**; root/API lock을 resolver로 갱신하고 설치 버전 기록. Kombu 5.6의 redis extra 상한 `<6.5` 때문에 기존 API `>=8.1.0`과 동시 설치 불가임을 resolver로 확인했다. 지원되는 안정 버전 공통 범위로 맞추며 extras 제거·강제 override·pre-release·별도 AI 환경 변경은 사용하지 않는다. lock 수동 편집 금지.
- 세 큐와 여섯 task 이름은 승인 설계 표 그대로; 실제 worker는 Linux/WSL2, Windows는 단위·eager 검증.
- provider 최초 포함 stage별 최대 3 attempts, 대기 5·10초; 중단된 RUNNING도 한도 소모. DB 전용 재전달은 countdown 5초.
- DB 연결 timeout 2초/명령 5초; broker 연결·명령 2초; 이벤트 기존 2초; provider 제한 1800초; broker visibility 3600초; 취소 확인 1초.
- POST 201/PENDING, 조회·취소·SSE 공개 계약 유지. migration v2는 명시적으로만 실행한다.
- 제품 provider registry 기본 empty. 테스트 provider는 테스트 파일에서만 주입한다. 실제 YouTube 접속·AI 추론·렌더링은 W03 범위 밖이다.
- URL·원시 예외·비밀번호를 HTTP/SSE/CLI/DB error detail/Celery retry나 backend 결과에 넣지 않는다. 예외 경계는 고정 메시지와 `from None`, traceback/context 출력도 검증한다.
- 같은 connection을 소유한 짧은 transaction으로 상태·metadata·예약을 함께 처리한다. provider 수행 중 row lock transaction 유지 금지.
- 계획 및 각 단위 독립 리뷰 >=95와 blocker/important 없음; 점수·날짜·버전·범위·지적 처리 기록. 관련 파일만 stage, 보고서와 원자적 commit. push/PR/merge 없음.

## Review Focus

1. 최초 발행 또는 다음 단계 발행 직전 종료: Task 1·3에서 commit/rollback과 재발행 중복을 확인한다.
2. DB lock 연결 상실 후 늦은 provider 결과: Task 2에서 다른 attempt의 metadata·terminal 상태를 덮어쓰지 못함을 확인한다.
3. 취소와 성공·retry의 경쟁: Task 1·2에서 row lock을 먼저 획득한 전이에 따라 terminal 보호를 확인한다.
4. 다운로드 업로드 원본 재사용·손상 출력·서로 다른 job 출력: Task 2에서 integrity와 ownership을 검증하고 연산 skip을 고정한다.
5. broker와 DB 동시 장애 및 worker 종료: Task 3·4에서 성공 ACK를 피하고 소유한 테스트 worker만 종료하며 실제 redelivery 증거를 분리한다.

## 파일 구조와 공용 타입

`packages/pipeline/musicsheet_pipeline/`은 기존 packages/storage 구조를 따른다. `__init__.py`에는 외부 연결·Celery 초기화 없이 공용 타입만 둔다.

- `contracts.py`: frozen `StageMessage(job_id: str, stage: PipelineStage, generation: int)`, `ProviderIdentity(name: str, version: str, configuration: dict[str, JSONValue], input_roles: frozenset[ArtifactRole], output_roles: frozenset[ArtifactRole])`, `StageInput(message, attempt_id, source_type, source_url, target_instrument: str | None, inputs: tuple[ArtifactRef,...])`, `StageContext` (StageInput 정보+storage: ArtifactStorage+cancellation: asyncio.Event). JSONValue는 JSON scalar/list/dict의 recursive type alias다.
- `models.py`: 내부 DB `PipelineJob` (기존 job 정보+active_attempt_id), `StageAttempt` (id/job/stage/attempt/generation/status/provider/version/fingerprint/outputs), `Transition(job: PipelineJob, changed: bool)`.
- `outbox.py`: 등록/복구/dispatcher 저장소. `repository.py`: job 실행 session과 전이. `artifacts.py`: streaming SHA-256 검증·fingerprint.
- `runner.py`·`providers.py`: async 실행과 empty registry. `events.py`: W02 store 공유 구현. `celery_app.py`·`tasks.py`·`config.py`·`dispatcher.py`·`cli.py`: 큐/실행/CLI 경계.
- root tests는 `tests/pipeline/`에 둔다. API 연동은 `services/api/tests/`의 기존 harness를 사용한다. `asyncio.run`으로 loop를 소유하며 pytest-asyncio를 추가하지 않는다.

## Task 1: DB 실행·발행 대기 기록과 패키지 경계

**Files:** Create `packages/pipeline/pyproject.toml`, `musicsheet_pipeline/{__init__,contracts,models,outbox,repository}.py`; `services/api/src/musicsheet_api/migrations/v0002_pipeline.py`; `tests/pipeline/{test_contracts,test_outbox,test_repository}.py`; API `tests/test_pipeline_migration.py`. Modify root `pyproject.toml`, `uv.lock`, API `pyproject.toml`, `uv.lock`, migration runner, 기존 live persistence migration 기대값.

**Interfaces:**

- `StageMessage` validates/canonicalizes UUID, stage enum, exact int generation>0; serialization uses only job_id/stage/generation.
- `enqueue_stage(connection, message: StageMessage, *, delay_seconds: int = 0) -> None`: unique key로 insert-on-conflict-do-nothing. delay는 0/5/10; DB time 기준 available_at. caller transaction을 만들거나 commit하지 않는다.
- `recover_pending(connection, *, limit: int = 100) -> int`: row locks/SKIP LOCKED, PENDING+DOWNLOAD·outbox/attempt 없는 job만 같은 transaction으로 예약.
- `PipelineRepository(connection).stage_session(message) -> AsyncContextManager[StageSession]`: UUID bytes[:8] signed big-endian advisory key; try-lock 실패 `StageBusy`, 소유한 session에서만 unlock. 연결 상실은 영구적인 ownership_lost flag를 설정한다.
- `StageSession.prepare(identity: ProviderIdentity | None) -> PreparedStage`: `PreparedStage(action: RUN|DUPLICATE|SKIP, context: StageInput | None, transition: Transition | None, completed_outputs: tuple[ArtifactRef,...])`. 현재 stage/generation/available_at·terminal·cancel·이전 완료/실행 이력을 같은 row-lock transaction에서 검사한다. runner는 StageInput에 storage/cancellation을 결합해 StageContext를 만든다.
- `StageSession.complete(attempt_id, outputs: tuple[ArtifactRef,...]) -> Transition | None`, `fail(attempt_id, *, code: str, retryable: bool) -> Transition | None`, `cancel_if_requested() -> Transition | None`, `invalidate_completed(*, code: str) -> Transition | None`, `check_ownership(attempt_id) -> bool`. 모든 terminal 쓰기는 job row lock + active_attempt_id/stage/status 조건. lost connection에서 재접속 commit 금지.

- [x] **Step 1 — 실패 테스트 작성:** `test_contract_rejects_boolean_generation`, `test_enqueue_uses_callers_transaction`, `test_finish_rolls_back_artifacts_and_next_message_together`, `test_cancel_wins_before_completion`, `test_terminal_is_immutable`, `test_interrupted_third_attempt_fails_without_next_generation`, `test_early_future_or_unreserved_message_does_not_run`, `test_busy_does_not_create_attempt`, `test_recover_pending_is_idempotent`.
- [x] **Step 2 — RED:** root 신규 테스트를 실행해 패키지/함수 부재로 실패함을 확인. 시작 전 테스트 cache 부모 폴더를 생성한다.
- [x] **Step 3 — 구현:** packages/storage와 같이 hatchling으로 wheel package를 구성한다. root dependency/workspace/sources에 pipeline 추가, API dependency/path source에 `../../packages/pipeline` 추가; common/storage source는 기존 root workspace/API 경로를 사용한다. API/pipeline Redis 제약을 Global Constraints의 공통 안정 범위로 맞춘 후 uv lock/sync를 실행한다. 실제 Celery/Kombu/Redis 설치 버전과 W02 store/SSE 모든 회귀 통과를 보고하고 Redis API 호환 문제는 해결 후 재리뷰한다. v2는 outbox와 active_attempt_id, attempt generation/fingerprint/output IDs 및 unique/check를 추가한다. generation 기존 값=attempt, 새 행 기본값1; 중복·attempt<=0이면 `Pipeline history is invalid`로 중단. 기존 행 삭제 금지. fresh migration `[1,2]`, 이미 v1 `[2]`, 재실행 `[]`; integration 기존 기대값도 갱신한다.
- [x] **Step 4 — 전이 구현:** 첫 실행 PENDING->RUNNING; 다음 stage는 바로 앞 완료 attempt 존재할 때만 시작. stage 완료 후 current_stage는 완료 stage에 남고 후속 task 진입 시 다음 stage로 변경한다. fingerprint는 source/type/target, provider config 정규 JSON, inputs를 `(role,id)` 정렬한 id/sha로 계산한다. retry/interruption은 이전 RUNNING/실패를 닫고 next generation outbox 예약 후 SKIP; 셋째 실패는 FAILED. jobs.active_attempt_id는 완료·실패·취소 시 clear. 오류 저장은 고정 code/message로 제한한다.
- [x] **Step 5 — GREEN + migration 검증:** transaction fake는 rollback snapshot을 실제 복구하여 단순 SQL 문자열 비교에 그치지 않는다. live opt-in `test_v1_upgrade_preserves_jobs_artifacts_attempts`, `test_v2_duplicate_history_rolls_back`, `test_concurrent_migration_applies_once`, `test_two_sessions_only_one_claim`를 API integration에 추가. test DB 마커 확인 없이는 reset 금지. v1 historical row는 outputs/fingerprint 부재로 자동 캐시 재사용하지 않고 기존 PENDING 자동 dispatch도 하지 않는다.
- [x] **Step 6 — 독립 리뷰·보고서·commit:** root/API 회귀와 lock checks, score>=95 기록; `docs/reports/pipeline-persistence-report.md` 및 main_spec 색인, `feat(pipeline): persist stage execution and dispatch intent`.

## Task 2: provider 실행·결과 검증·W02 이벤트 공유

**Files:** Create pipeline `providers.py`, `artifacts.py`, `runner.py`, `events.py`; tests `test_runner.py`, `test_artifact_validation.py`, `test_event_boundary.py`. Modify API `events/store.py` 호환 re-export, 기존 store 테스트의 timeout monkeypatch 대상.

**Interfaces:**

- `StageProvider` protocol: `identity: ProviderIdentity`; `async run(context: StageContext) -> tuple[ArtifactRef,...]`. async cooperative provider를 요구하며 동기 provider는 adapter가 thread/subprocess와 종료 책임을 가진다. 제품 registry `Mapping[PipelineStage, StageProvider]`는 비어 있다.
- `run_stage(message, *, connection, storage, providers, event_store: EventStore | None, provider_timeout: float = 1800, cancellation_interval: float = 1) -> None`: session/prepare 계약을 사용한다. DB 실패/lock 경합은 `InfrastructureUnavailable`/`StageBusy` 고정 예외; provider 원시 예외는 경계 밖으로 나가지 않는다.
- `async validate_artifacts(artifacts, *, job_id, identity, storage, attempt_id, existing_inputs, cancellation: asyncio.Event) -> tuple[ArtifactRef,...]`: mutable Pydantic 재검증(warnings=False), roles·소유 job·UUID·hex sha·size·고유 IDs·provider/version, 64KiB bounded 읽기로 실제 hash 확인. 신규 filename은 `attempt_{attempt_id}_` prefix; 기존 입력 재사용은 DB reference와 전 필드가 일치할 때만 허용. 읽기·파일 예외는 고정 validation 실패로 변환하고 stream 닫는다. 기존 입력 검증은 생산자 identity를 강제하지 않고 DB reference/integrity와 consumer input_roles를 확인하는 별도 모드다.
- 입력·완료 출력·신규 출력의 모든 동기 storage 작업은 함수 내부의 **소유한 asyncio.to_thread task**에서 수행한다. worker thread가 stream을 열고 finally에서 닫으며 매 청크 전에 threading.Event stop을 검사한다. async cancellation/ownership 상실은 stop을 set하고 새 청크를 읽지 않게 한다. wrapper는 shield + 완료 대기로 thread가 닫힐 때까지 drain하며 반복 caller cancellation에서도 thread를 방치하거나 외부에서 동시 close하지 않는다. 진행 중 OS 파일 read 자체를 강제 중단한다고 주장하지 않는다; 검증 종료는 현재 read가 돌아온 뒤 협력적으로 수행되며 monitor는 그동안 계속 동작한다. provider 1800초 제한은 provider에 적용되며 storage의 OS 장애에 대한 hard timeout 보장과 혼동하지 않는다.
- shared events의 공개 symbol/2초 timeout/100 retention/SSE 사용 계약 동일. API import compatibility는 symbol re-export로 제공하며 monkeypatch 내부 모듈 경로는 새로운 공유 모듈로 바꾼다.

- [x] **Step 1 — 실패 테스트 작성:** 여섯 stage 완료 순서와 overall `[16,33,50,66,83,100]`; provider 누락 실패; unknown/retryable/permanent 오류; 3회 초과 없음; deadline 초과 `PROVIDER_TIMEOUT` permanent. 업로드 DOWNLOAD가 SOURCE_ORIGINAL을 재사용할 때 metadata 중복 없음. fingerprint mismatch `INPUT_CHANGED`; 손상/누락/타 job·중복 output·잘못된 producer는 `ARTIFACT_INVALID`.
- [x] **Step 2 — RED:** 신규 engine/integrity 테스트의 실패를 확인하고 구현한다. prepare가 남긴 transition은 커밋 후 발행한다. RUN에서 입력 integrity+identity input roles를 검사한 뒤 provider를 호출한다. DUPLICATE는 completed output 검증 후 연산 생략; 실제 stage 진행이 이미 앞섰으면 SKIP하며 다음 stage 입력 검증이 손상을 잡는다.
- [x] **Step 3 — 취소·소유권 테스트/구현:** asyncio Events로 취소·완료 commit 경쟁 두 순서를 고정한다. monitor는 1초마다 같은 session의 연결로 확인; provider와 monitor DB 조작은 동시에 하지 않도록 session lock으로 serialize한다. monitor는 provider뿐 아니라 입력/출력 검증 전체에서 실행한다. DB monitor 오류는 ownership_lost + cancellation set, provider.cancel 및 gather; 결과 commit 금지. 완료 직전 monitor를 정리하고 최종 transaction에서 취소 재검사. timeout·외부 task cancellation에서도 모든 task/stream/session close를 확인한다. cooperative 종료를 거부하는 provider는 별도 adapter가 필요하며 테스트 provider는 항상 종료에 응답한다.
- [x] **Step 3a — 느린 validation 회귀:** thread read double은 threading.Event로 차단하고 테스트 finally에서 항상 release한다. 각 input/completed-output/new-output 모드에서 read가 막힌 동안 monitor가 실행됨을 관찰한다. input 검사 중 취소 후 provider 호출0, validation 중 lock 연결 상실 후 metadata/성공 commit0, release 이후 stream close1·남은 thread task0을 assert한다. 실제 무한 파일 I/O를 만들어 테스트 runner를 방치하지 않는다. target_instrument가 StageInput/StageContext와 fingerprint에 동일하게 전달되는 테스트도 추가한다.
- [x] **Step 4 — 이벤트 경계 테스트/구현:** commit 이전 발행 0, DB 실패 발행 0, commit 이후 Redis 실패에도 provider 재실행 0 및 상태 보존. cancellation은 잡아먹지 않는다. 원시예외 sentinel이 warnings/stdout/stderr/DB/error context에 없음을 검사한다. W02 store의 UTF8 malformed 응답·100 cap·publish/metadata cancellation probe도 permanent pytest로 고정한다.
- [x] **Step 5 — GREEN·독립 리뷰·보고서·commit:** root/API 회귀, W02 SSE replay/client ownership 모두 통과; `docs/reports/pipeline-stage-runner-report.md`, `feat(pipeline): execute stages with retry and cancellation`.

## Task 3: Celery task·dispatcher·API 등록 원자성

**Files:** Create pipeline `config.py`, `celery_app.py`, `tasks.py`, `dispatcher.py`, `cli.py`; tests `test_celery_tasks.py`, `test_dispatcher.py`, `test_cli.py`, API `test_job_dispatch.py`. Modify pipeline scripts, API jobs router/uploads 및 기존 doubles, README/runtime examples.

**Interfaces:**

- `PipelineSettings.from_env(environ=None, *, working_directory=None)` owns secret-safe fields DATABASE_URL/CELERY_BROKER_URL/CELERY_RESULT_BACKEND/REDIS_URL/LOCAL_STORAGE_DIR. repr hides DSNs. missing required DB/broker fails CLI/consumer start with fixed message; imports never connect. path resolution follows API.
- `create_celery_app(settings, *, runtime_factory=None, queue_prefix="") -> Celery`: six explicitly named bound tasks accepting `(job_id: str, generation: int=1)`, stage fixed by task name. production prefix empty, tests unique. `celery_app` CLI object constructs settings lazily at process entry without opening connections. factory returns task-owned async runtime context (DB connection, Redis/client, storage, providers); registry default empty.
- `dispatch_once(connection, publisher, *, limit: int=100) -> int`: **one row per transaction**, `LIMIT 1 FOR UPDATE SKIP LOCKED`, availability gate; publish with outbox ID task_id + JSON kwargs and known queue, commit published_at only after success. count stops at limit; on publish failure rollback/raise sanitized `DispatchUnavailable` so same row is not busy-looped inside batch. async caller uses thread publishing with bounded library socket timeouts; do not time out and abandon a still-publishing thread that later commits outside owner.
- `CeleryPublisher.publish(message, *, task_id: str) -> None`: broker_connection_timeout=2, Redis socket/connect timeout=2, task_publish_retry=False (no hidden unbounded retries), payload no source_url. dispatcher next poll provides retry. one publisher owns connection/context, closes on shutdown.
- CLI `main(argv=None) -> int`: musicsheet-dispatch `--once`, `--poll-interval` finite positive float default1, `--recover-pending`. recovery mode runs bounded batches then exits; mutually exclusive with normal dispatch. Ctrl-C closes runtime and exits cleanly. steady-state failure logs fixed message, sleeps interval, retries; once failure nonzero. test termination own subprocess only.

- [x] **Step 1 — RED/設定:** assert task names/routes, acks_late/reject_on_worker_lost/JSON-only/prefetch1/visibility3600 (broker/global and configured backend); no result backend required. eager app with task-owned same-loop fake runtime must execute named wrappers and close resources once; production import loads no test provider/no FastAPI/model modules/no network.
- [x] **Step 2 — task adapter implementation:** synchronous task uses asyncio.run to open runtime/run_stage/close. busy or DB failure -> self.retry(countdown=5,max_retries=None,exc=sanitized exception); distinguish Celery Retry control exception from publish failure. if retry publish fails wait5 in consumer then Reject(requeue=True) from None. unit test records delay with injected sleeper, while live test verifies real elapsed/ACK behavior. raw runtime cleanup failures are sanitized and never overturn already committed provider success into provider rerun.
- [x] **Step 3 — dispatcher RED/GREEN:** failures before publish and after publish before DB commit leave row pending; second dispatch may use same task_id and deliver twice, worker deduplicates by DB. two dispatchers cannot concurrently own same row. available_at future excluded, limit range1..100 exact int. **COMPLETED/FAILED/CANCELED** rows are marked published without sending; **CANCEL_REQUESTED는 발행한다**. `register -> cancel -> first dispatch -> worker`에서 provider0/final CANCELED/후속 outbox0을 확인한다. RETRYING의 지연 outbox가 취소된 경우에도 available_at 도래 후 전달되어 같은 결과를 만든다. recovering legacy PENDING at limit and repeated runs leaves one initial intent.
- [x] **Step 4 — API RED/GREEN:** YouTube route acquires connection/transaction, JobRepository.create_job(connection=...), enqueue_stage same connection, returns original PENDING response. Upload metadata transaction adds enqueue. failure rollback deletes upload as existing; cancellation after committed metadata retains upload+outbox; API broker unavailable still 201 and never creates broker client. request_cancel contract unchanged. direct repository.create_job remains low-level persistence only and does not silently enqueue.
- [x] **Step 5 — CLI/subprocess and secret checks:** missing/invalid URLs, malformed flags, publisher RuntimeError(secret), retry-backend tracing, DB close failure do not expose sentinel even with captured formatted tracebacks. imports no side effects; once/recovery finite exit codes; interrupt poll closes resources. producer identity and configuration size limits are documented and tested (name<=64,version<=32; serialized config<=64KiB; no raw secrets in fingerprint material persisted).
- [x] **Step 6 — GREEN·독립 리뷰·보고서·commit:** root/API checks + lock consistency; `docs/reports/celery-dispatch-api-report.md`, `feat(pipeline): dispatch durable stages through Celery queues`.

## Task 4: opt-in live 검증과 운영 문서

**Files:** Create `services/api/tests/integration/test_pipeline_persistence.py`, `tests/pipeline/integration/test_live_worker.py`, `tests/pipeline/integration/support.py`, `packages/pipeline/README.md`; modify pytest markers, canonical status paragraphs, root/API README, main_spec/roadmap/completed-work, aggregate report `docs/reports/celery-orchestration-implementation-report.md`.

- [ ] **Step 1 — 환경 preflight:** root/API Python3.13·uv version, lock checks. Windows에서는 Linux worker suite skip; `MUSICSHEET_TEST_DATABASE_URL`(marked disposable DB), `MUSICSHEET_TEST_REDIS_URL`, explicit `MUSICSHEET_TEST_CELERY=1` opt-in 필요. unset은 skip, configured dependency failure는 sanitized fail. install/start shared Redis/DB/WSL이나 Docker infra는 이 계획 범위에 포함하지 않는다.
- [ ] **Step 2 — DB live tests:** migration v2 fresh/v1/rollback/concurrent, actual SQL transaction cancellation vs success, concurrent advisory sessions, outbox row locking, 3 attempts+generation, completed artifact reference reuse. marker를 접속해 확인 후에만 기존 disposable schema reset; 모든 pipeline live tests는 직렬 실행하고 독립 namespace+temporary storage 사용.
- [ ] **Step 3 — Linux worker harness:** 테스트가 소유한 unique queue prefix·Redis broker global_keyprefix·짧은 visibility(5초)를 factory setting override로 적용한다. startup handshake와 worker process PID/process group을 보관한다. test-only provider module은 harness에서 명시적으로 주입, 제품 CLI에 provider 테스트 옵션 추가 금지. task payload는 운영과 동일. 실제 prefork concurrency2 consumer를 세 test queues에 구독시켜 두 실행의 lock 경합을 관찰한다. eager를 사용하지 않는다.
- [ ] **Step 3a — root/API 환경 경계:** root에 API/FastAPI 의존성을 추가하거나 API 모듈을 직접 import하지 않는다. Linux 사용자는 root와 services/api 두 uv 환경을 sync하고 marked test DB에 API 환경의 명시적 `uv run --project services/api --locked --python 3.13 musicsheet-migrate`를 먼저 실행한다. root live fixture는 접속해 DB name/comment와 schema_migrations version2 존재를 확인하며 불일치 시 generic fail; root fixture는 schema reset/migration하지 않는다. Task4 Step2의 API DB reset suite를 먼저 완료하고 migration 명령을 재실행한 뒤 root worker suite를 직렬 실행한다.
- [ ] **Step 3b — 실제 SSE 관찰:** root harness가 test-owned API process를 `uv run --offline --no-sync --project services/api --python 3.13 python -m uvicorn musicsheet_api.app:app --host 127.0.0.1 --port <allocated>`로 실행한다. 임시 port·PID/group 및 DATABASE_URL/REDIS_URL/LOCAL_STORAGE_DIR을 worker와 공유한다. stdlib HTTP client의 SSE read를 별도 thread에서 timeout2초로 관찰하고 event id/status를 parse한다. COMPLETED 이벤트 또는 observation deadline 도달 시 connection.close를 소유 thread finally에서 호출하고 drain하며 API process도 finally에서 종료/대기한다. startup polling은 /health/live, 모델 health ready를 요구하지 않는다. API 환경/모듈이 없거나 기동 실패하면 configured live suite fail이며 묵시적 dependency 설치는 하지 않는다.
- [ ] **Step 4 — real worker cases:** six stages actual small artifacts+DB history/SSE; one retry then recovery; duplicate delivery provider call once; blocking provider 두 worker lock 경합; 시작 확인 뒤 소유한 worker process group 종료/재시작 및 redelivery; cancel while blocked, outbox publish후 commit 실패. broker failure는 테스트 소유 TCP proxy 연결을 중단/회복해 유도하며 기존 Redis 서버를 중단하지 않는다. wait deadlines<=30초 per observation, full test<=120초, provider blocker timeout<=20초; visibility override와 실제 운영3600 차이를 보고서에 명시한다.
- [ ] **Step 5 — cleanup:** finally에서 소유한 subprocess를 종료/대기하고 고유 prefix에 해당하는 queue/binding/result keys만 SCAN+삭제한다. Redis URL에 CLIENT LIST/SCAN/DELETE ACL 요구를 문서화. FLUSHDB/FLUSHALL·공유 worker 종료 금지. secret URL repr redaction과 fail을 원시 except 밖에서 생성; negative configured URL subprocess로 sentinel 검증. cleanup failure는 fail이며 주 오류를 덮어쓰지 않는다.
- [ ] **Step 6 — docs and full checks:** worker CPU I/O4~8/GPU1/render2~4 Linux 명령, dispatcher, explicit migration v2, blank provider expected failure, manual recover-pending, orphan files/at-least-once/event loss/visibility downtime 설명. 실제 YouTube 테스트가 없음을 명시. opt-in 실행 불가 시 success 증거 미검증으로 분리하고 README 명령을 실제 실행 주장으로 쓰지 않는다.
- [ ] **Step 7 — 독립 단위 및 전체 리뷰:** Task4>=95 및 전체 변경 review>=95/blocker·important0; report에 모든 점수·날짜·범위·지적·해결·미검증 기록. roadmap 완료 및 W04 next로 전환; `test(pipeline): verify worker recovery and document operations`. 브랜치·작업 폴더 유지, push/PR/merge 없음.

## 공통 검증 명령과 합격 기준

PowerShell cwd `D:\develop\MusicSheet`; pytest temp parent를 `New-Item -ItemType Directory -Force outputs/.verification-w03 | Out-Null`로 만든다. 각 실행의 `<fresh>`는 서로 다른 고유 이름이며 기존 디렉터리를 반복 삭제하지 않는다.

```powershell
uv --cache-dir outputs/.uv-cache lock --project . --check
uv --cache-dir outputs/.uv-cache lock --project services/api --check
uv --cache-dir outputs/.uv-cache sync --project . --locked
uv --cache-dir outputs/.uv-cache sync --project services/api --locked
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w03/<fresh-root> --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/api --python 3.13 pytest services/api/tests -q -p no:cacheprovider --basetemp outputs/.verification-w03/<fresh-api> --tb=short
git diff --check
```

처음에는 lock 변경이 필요한 만큼 `uv lock`을 --check 없이 root/API 각각 실행한 뒤 sync한다. 네트워크 제한이 원인이면 authorized lock/sync만 require_escalated로 재시도한다. dependency resolver 충돌을 범위 삭제나 lock 수동 편집으로 숨기지 않는다. root baseline 59passed/4skipped/4deselected, API baseline222passed/17skipped; 신규 tests가 추가되므로 최종 수는 증가한다. failures0, unintended skips0, opt-in unset skips 명시, lock check 성공, diff check 성공이어야 단위 리뷰를 요청한다.

RED는 해당 단위의 신규 tests만 `pytest tests/pipeline/<file>.py -q` 또는 API test path로 실행한다. GREEN은 신규 tests 후 root/API 전체를 실행한다. live marker는 기본값으로도 fixture가 unset skip을 명시하며 real worker configured environment에서는 위 전체 명령과 동일한 runner로 실행한다. 실행한 명령·환경·count·skip 이유를 report에 기록한다.

## 리뷰 기록

| Version | Reviewer/date | 점수 (25/20/20/25/10) | 지적·처리 |
| --- | --- | --- | --- |
| R1 | /root/w03_plan_review · 2026-10-03 | 24+18+20+22+10 = **94** | important2: 취소 발행 enum·동기 무결성 검사 경계. minor2: API live 환경 경계·target 필드. R2에 명시적 처리 및 회귀 검증 추가 |
| R2 | /root/w03_plan_review · 2026-10-03 | 25+20+20+25+10 = **100** | R1 지적4개 해결 확인. blocker0/important0/minor0. 현재 버전에 대한 독립 평가 |
| R3 | /root/w03_plan_review · 2026-10-03 | 25+20+20+25+9 = **99** | Redis 공통 안정 범위 확인. blocker0/important0/minor1: 실행 승인/착수 후에도 과거 대기 상태가 남음 → 현재 상태와 역사 문구로 정리 |

R2 작성 당시 자체 검토는 타입·사양 범위·테스트 준비 순서·취소/정리 책임을 대상으로 했고 제품 코드·설치는 미착수였다. 현재는 사용자 실행 승인 후 Task1을 작성 중이며 R3 의존성 재평가99점을 받은 뒤 lock/sync와 회귀를 진행한다. live DB migration은 실행하지 않았다.
