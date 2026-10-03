# W03 Celery 오케스트레이션 설계

- Revision: 1
- 작성일: 2026-10-03 (Asia/Seoul)
- 상태: 사용자 설계 승인 (2026-10-03 `w03진행`); 실행 계획 작성 단계, 미구현
- 기준: W02 완료 `2d39ed9`
- 사양: [Celery](../../backend/celery.md), [파이프라인](../../architecture/job-pipeline.md), [상태 머신](../../domain/job-state.md), [DB](../../backend/database.md)

## 1. 목적과 완료 범위

등록된 YouTube·업로드 작업을 CPU·AI 큐에 전달하고, 단계 실행·재시도·중복 전달·취소를 PostgreSQL에 기록한다. DB가 상태의 기준이며 Redis Streams는 커밋된 진행 상태를 사용자에게 전달한다. 실제 다운로드·전처리·분리·전사·퀀타이즈·렌더 provider 구현은 후속 작업이다.

성공 기준은 실제 Celery task 경계를 거친 여섯 단계의 순서와 큐 라우팅, stage_attempts 기록, 장애 후 재전달, 중복 실행 방지, 취소 경쟁 처리를 검증하는 것이다. 테스트 provider로 완료한 job은 테스트에서만 생성한다. 제품 설정에서 없는 provider를 성공으로 간주하거나 가짜 아티팩트를 만들지 않는다.

추정한 사용자 의도는 W01 등록 API와 W02 진행 이벤트를 실제 worker 실행 구조로 연결하고 이후 W04–W08 구현을 꽂을 수 있게 하는 것이다. W03만으로 음악 변환 전체가 완성되지는 않는다.

## 2. 접근 방식과 선택

| 접근 | 장점 | 제한 |
| --- | --- | --- |
| **DB 발행 대기 기록 + 단계별 전달 (추천)** | 등록·다음 단계 예약을 상태 변경과 함께 커밋; 큐 장애 후 다시 전달 가능 | outbox 테이블과 dispatcher가 필요 |
| 등록 후 직접 Celery canvas chain 발행 | 코드가 짧고 표준 canvas 사용 | DB 커밋·최초 발행 및 단계 완료·후속 발행 사이의 장애를 별도로 복구해야 함 |
| 운영자가 CLI로 job_id 전달 | API 변경이 작음 | 등록 후 자동 실행이라는 목표에 부족 |

추천안은 단계 순서를 DB와 발행 대기 기록으로 연결한다. Canonical Celery 사양의 `chain 또는 chord` 문구는 이 방식을 허용하도록 **설계 승인 후 계획 단계에서 먼저 갱신**한다. 실행 순서와 큐 분리는 유지한다. 병렬 분기와 chord는 필요하지 않다.

## 3. 패키지와 실행 환경

- `packages/pipeline`에 `musicsheet-pipeline` Python 3.13 workspace 패키지를 추가한다. 공용 스키마·스토리지, asyncpg, Redis, Celery에 의존한다. FastAPI와 AI 모델 패키지는 의존하지 않는다.
- API는 pipeline의 outbox 등록 함수를 호출한다. 이 함수의 import는 Celery 앱 생성, Redis/DB 연결, worker 시작을 일으키지 않는다.
- W02 `events/store.py`를 pipeline의 공유 이벤트 모듈로 옮기고 API 경로에는 기존 import 호환 re-export를 남긴다. 기존 SSE 오류·재생 계약과 테스트를 유지한다.
- Celery 의존성은 `celery[redis]>=5.6,<6`로 시작해 실제 Python 3.13 resolver 결과를 lockfile에 고정한다. API 별도 lock과 root workspace lock을 함께 갱신한다. Python 3.12 Basic Pitch 환경은 변경하지 않는다.
- 실제 worker의 지원 실행 환경은 Linux/WSL2다. Windows에서는 단위 테스트와 eager 실행만 검증한다. GPU 큐의 consumer는 이후 격리된 모델 worker를 호출할 수 있다.

## 4. 데이터 계약과 마이그레이션

명시적 migration v2를 추가한다. API/worker 시작 시 자동 적용하지 않는다. 기존 v1 데이터를 유지한다.

1. `pipeline_outbox`: `id` UUID 문자열 PK, `job_id` FK, `stage`, `generation` 양의 정수, `available_at` timestamptz, `published_at` nullable, `created_at`. `(job_id, stage, generation)` unique와 미발행·예약 시각 인덱스를 둔다. payload에는 ID·stage·generation만 사용하며 URL·파일·인증정보는 넣지 않는다.
2. `stage_attempts`: 기존 컬럼에 `generation` 양의 정수, `input_fingerprint` nullable SHA-256 문자열, `output_artifact_ids` JSONB 배열 기본 `[]`를 추가한다. generation은 메시지와 attempt를 연결하며 기존 행은 attempt 값으로 채운다. `(job_id, stage, attempt)` unique를 추가하기 전 기존 중복 또는 비양수 attempt가 있으면 명시적이고 비밀 없는 migration 오류로 중단한다. 역사 데이터를 임의 삭제하지 않는다.
3. `jobs`: 내부 실행 소유권을 비교할 `active_attempt_id` nullable 문자열을 추가한다. REST response와 공용 JobStatus/PipelineStage/JobProgressEvent 필드는 변경하지 않는다.

Task 입력은 canonical UUID `job_id`, 명시적 stage, 양의 정수 generation이다. bool을 generation으로 허용하지 않는다. 형식 오류·없는 job·예약 기록 없는 메시지는 provider와 DB 상태 변경 없이 거부하며 고정 오류만 기록한다. 현재 generation은 해당 job/stage의 예약된 outbox 최대 generation으로 판단한다. 최초·다음 stage는 generation 1, 같은 stage 재시도는 이전 값 +1이다. provider에는 DB에서 읽은 source 정보와 같은 job에 속하는 검증된 아티팩트만 전달한다. output은 `ArtifactRef` 목록이며, 같은 job_id·지원 role·실제 저장 파일·size·SHA-256·provider/version을 검증한다. 성공한 attempt의 출력 ID 목록이 다음 단계 입력의 기준이다.

## 5. 등록과 전달

YouTube job 생성과 DOWNLOAD generation 1 outbox 삽입을 하나의 DB 트랜잭션으로 처리한다. 업로드도 기존 job+SOURCE_ORIGINAL metadata 트랜잭션에 같은 outbox 삽입을 추가한다. outbox 실패 시 등록을 롤백하고 기존 업로드 파일 정리 정책을 적용한다.

기존 POST의 201·PENDING 응답과 조회·취소 HTTP 계약을 유지한다. broker가 내려가도 DB 등록은 성공하며 outbox는 남는다. migration 미적용 등 DB 오류는 기존의 일반적인 503을 반환한다. API 요청은 broker에 직접 연결하지 않는다.

별도 `musicsheet-dispatch` CLI가 미발행·available_at 도래 행을 배치 100개 이하로 읽는다. 각 행은 짧은 DB 트랜잭션의 `FOR UPDATE SKIP LOCKED`로 소유한다. broker 발행에 연결/명령 timeout 2초와 bounded publish retry를 적용한다. 성공 후 published_at을 저장한다. 실패 또는 프로세스 종료 시 행은 다음 주기에 다시 처리할 수 있다. 발행 성공 후 DB 기록 전에 종료하면 중복 메시지가 생길 수 있으며 worker가 처리한다.

실행 모드는 `--once`와 `--poll-interval 1` 기본 지속 실행을 제공한다. 테스트는 --once 또는 명시적으로 종료 가능한 프로세스만 사용한다. 시작 오류·실행 오류·경고에 URL, 비밀번호, 원시 provider 예외를 출력하지 않는다.

기존 PENDING job은 새 등록 트랜잭션을 거치지 않았으므로 별도 `--recover-pending` 명령으로 DOWNLOAD outbox를 보충한다. 이미 outbox/attempt가 있거나 terminal·CANCEL_REQUESTED job은 제외한다. 자동 migration에서 과거 job을 실행시키지 않는다.

## 6. 단계 실행과 멱등성

| Task 이름 | Stage | Queue |
| --- | --- | --- |
| `pipeline.tasks.download` | DOWNLOAD | cpu_io_queue |
| `pipeline.tasks.preprocess` | PREPROCESS | cpu_io_queue |
| `pipeline.tasks.separate` | SEPARATE | gpu_ai_queue |
| `pipeline.tasks.transcribe` | TRANSCRIBE | gpu_ai_queue |
| `pipeline.tasks.postprocess` | POSTPROCESS | cpu_render_queue |
| `pipeline.tasks.render` | RENDER | cpu_render_queue |

모든 task는 acks_late, reject_on_worker_lost, JSON-only serializer/accept_content, worker_prefetch_multiplier=1을 사용한다. broker URL은 CELERY_BROKER_URL, 선택적 backend는 CELERY_RESULT_BACKEND, 이벤트는 REDIS_URL로 분리한다. 결과 backend가 없어도 단계 연결이 동작하며 애플리케이션 상태는 DB에서 읽는다. broker visibility_timeout은 3600초, provider 실행 제한은 최대 1800초로 시작한다.

Worker는 task마다 하나의 asyncio loop에서 DB/Redis 연결을 열고 닫는다. prefork 전에 pool/client를 만들거나 다른 loop의 연결을 재사용하지 않는다. provider의 동기 I/O는 별도 실행 경계로 보내 loop가 취소 확인을 계속할 수 있게 한다.

1. UUID에서 결정적으로 계산한 signed bigint의 PostgreSQL session advisory lock을 **job 단위**로 try-acquire한다. 다른 실행이 소유하면 연산 없이 5초 뒤 재전달하도록 처리한다. 이 경합은 provider attempt 횟수를 늘리지 않는다.
2. 짧은 row-lock 트랜잭션으로 job과 attempt를 검사한다. terminal job과 과거 generation 메시지는 상태를 바꾸지 않고 종료한다. 현재 stage보다 앞선 메시지는 실행하지 않는다. 미래 stage 메시지는 일반적인 protocol 오류로 기록하되 job의 정상 진행을 훼손하지 않는다.
3. 같은 generation의 완료 attempt가 있으면 provider를 다시 실행하지 않는다. output의 존재·size·SHA-256을 확인한다. 유효하면 이미 기록된 후속 outbox를 그대로 사용한다. 손실·손상 출력은 `ARTIFACT_INVALID` 실패로 기록하며 다음 단계로 진행하지 않는다.
4. 이전 실행이 종료되어 advisory lock을 새 worker가 취득했지만 attempt가 RUNNING이면 `WORKER_INTERRUPTED`로 닫고 재시도 규칙에 따라 다음 generation을 예약한다. 해당 메시지에서는 provider를 실행하지 않는다. 새 generation 실행 시작 때 jobs.active_attempt_id를 새 attempt ID로 지정하고 provider를 트랜잭션 밖에서 호출한다. 긴 DB 트랜잭션을 유지하지 않는다.
5. provider 종료 후 다시 row lock을 잡고 active_attempt_id·stage·status를 비교한다. 소유권을 잃은 결과는 등록하지 않는다. 출력 metadata, attempt 완료, 진행 상태와 **다음 stage outbox**를 같은 트랜잭션으로 커밋한다. RENDER 성공 시에만 job을 COMPLETED로 전환한다.

advisory lock 연결이 끊겼을 때 기존 provider가 계속 살아 있을 수 있다. 해당 실행은 소유권 상실을 영구 기록하고 새 연결에서 결과를 커밋하지 않는다. attempt ID 비교가 늦게 도착한 DB 쓰기도 거부하고, provider는 attempt별 고유 파일명으로 출력하여 새 실행의 파일을 덮어쓰지 않는다. 외부 모델 연산 자체의 exactly-once는 보장하지 않는다. 실패한 미등록 파일의 자동 GC는 후속 운영 범위이며, 경로·attempt ID를 운영 기록으로 찾을 수 있게 한다.

입력 fingerprint는 source 및 순서가 고정된 input artifact SHA-256·provider/version·설정에서 계산한다. 기존 완료 결과의 fingerprint가 다르면 캐시로 사용하지 않고 `INPUT_CHANGED`로 실패한다. 실제 provider별 필수 role과 bypass는 후속 provider 구현이 계약에 선언한다. orchestration이 임의의 stem이나 score를 합성하지 않는다.

## 7. 재시도·오류·취소

- provider의 명시적 `RetryableStageError`와 `WORKER_INTERRUPTED`만 재시도한다. stage별 총 attempt는 최초 포함 3회, 대기는 5초·10초다. worker 중단도 무한 크래시 반복 방지를 위해 한도를 소모한다. RETRYING 상태, 실패 attempt, 같은 stage의 다음 generation outbox를 함께 커밋한다. 셋째 attempt 실패·중단은 FAILED로 끝내고 다음 generation을 만들지 않는다. Celery countdown에 provider 재시도를 맡기지 않아 예약을 DB에서 추적한다.
- `PermanentStageError`, provider 누락(`PROVIDER_NOT_CONFIGURED`), 잘못된 출력, 알 수 없는 provider 예외는 FAILED로 종료한다. 사용자 error_message와 SSE message는 고정 안내문이며 원시 예외를 저장하거나 발행하지 않는다. provider/version과 error_code로 분석한다.
- DB 연결·커밋 장애는 성공으로 ACK하지 않는다. DB 명령 timeout 5초, 연결 timeout 2초 후 비밀 없는 Celery retry를 5초 countdown으로 예약한다. 인프라 retry는 max_retries=None으로 한다. retry 자체의 broker 발행도 실패하면 consumer 실행에서 5초 지연 후 `Reject(requeue=True)`를 사용한다. 일반 예외 종료로 메시지가 ACK되는 경로를 허용하지 않는다. 이 재전달은 provider attempt 생성 전에는 stage 한도를 소모하지 않지만, 이미 시작된 RUNNING attempt를 복구할 때는 위 한도를 적용한다. 실제 broker 단절·복구에서 이 동작을 검증한다.
- 시작 전 CANCEL_REQUESTED는 CANCELED로 바꾸고 provider·후속 발행을 생략한다. provider 실행 중에는 1초 주기 DB 확인과 provider의 협력적 취소 callback으로 중단한다. 완료 트랜잭션에서 취소 상태를 다시 확인하여 취소가 먼저 커밋됐다면 성공 결과를 등록하지 않는다.
- terminal 상태는 worker의 늦은 성공·실패·재시도로 덮어쓰지 않는다. stage_attempts의 상태는 RUNNING/COMPLETED/FAILED만 사용하고 취소된 attempt는 FAILED + `CANCELED` error_code로 닫는다.
- stage_progress는 시작 0·완료 100; overall_progress는 여섯 단계를 동일 가중으로 `floor(completed_stages * 100 / 6)` 계산하고 전체 완료는 100이다. 재시도에서 완료 단계 수를 줄이지 않는다. provider의 상세 진행률은 후속 확장이다.

## 8. W02 진행 이벤트 연결

상태 트랜잭션 성공 **후** 공유 RedisEventStore.publish를 호출한다. DB 실패 시 이벤트를 발행하지 않는다. 이벤트 발행 실패 때문에 성공한 provider를 재실행하거나 DB 상태를 되돌리지 않는다. 이 경우 비밀 없는 경고를 남기며 REST 조회가 최종 상태를 제공한다. 이벤트 exactly-once·모든 이벤트 보존은 보장하지 않는다. W02의 제한된 retention과 재접속 계약을 유지한다.

## 9. 검증과 구현 단위 후보

실행 계획 작성 전 사용자 설계 검토가 필요하다. 아래는 순서 후보이며 계획 점수가 아니다.

1. **DB 실행 기록과 발행 대기 계약:** v2 migration·outbox·attempt/상태 저장소, 등록 원자성, migration 재실행/기존 데이터/rollback 테스트.
2. **단계 실행 엔진:** provider 계약, 중복·오래된 generation·완료 출력 검증·DB 연결 상실 fencing·재시도 한도·취소 경쟁·후속 예약 원자성, DB 커밋 후 SSE 발행 테스트.
3. **Celery·dispatcher·API 연결:** 실제 task 등록과 큐 설정, 발행 전/후 장애·동시 dispatcher, API broker 장애·업로드 rollback·과거 PENDING 복구, eager 및 subprocess CLI 검증.
4. **실서비스 통합·운영 문서:** opt-in PostgreSQL/Redis+Linux worker 검증과 전체 회귀, 실행/중단/장애 복구 절차, 보고서·완료 색인.

각 단위는 TDD, 별도 독립 리뷰 95점 이상 및 blocker/important 없음, 결과보고서, 관련 파일의 원자적 커밋 후 다음 단위로 이동한다. 구현 전에 docs/plans 실행 계획의 별도 독립 평가도 95점 이상이어야 한다.

테스트 provider는 여섯 단계의 실제 아티팩트를 임시 storage에 만들며 제품 registry에 등록하지 않는다. Python 3.13 root/API 테스트를 모두 실행한다. 실DB 테스트는 기존 `musicsheet_test` 이름과 `MUSICSHEET_DISPOSABLE_TEST_DB_V1` comment 확인을 유지한다. Redis는 테스트 고유 queue/key만 정리하며 FLUSHDB/FLUSHALL을 사용하지 않는다. live 테스트 URL이 없으면 skip, 설정됐지만 실패하면 fail이다. eager 통과를 실제 Linux worker 성공으로 보고하지 않는다.

실서비스 통합은 별도 test queue namespace로 운영 worker와 격리한다. 정상 여섯 단계, broker 중단 후 회복, 중복 메시지, 두 worker 동시 전달, 실행 중 worker 종료와 redelivery, 취소 경쟁을 검증한다. 환경이 없으면 해당 증거는 미검증으로 기록한다.

## 10. 설계 검토 기록

작성자 자체 검토: 범위와 W04–W08 경계, 기존 HTTP 계약, 저장소/loop 소유권, DB·broker 장애 구간, 이벤트 실패 정책, 취소 경쟁과 stale 결과 차단, 테스트 환경 제한을 확인했다. 구현 계획의 독립 점수와 구현 리뷰 점수는 아직 없다. 이 문서를 구현 승인이나 점수 통과로 간주하지 않는다.

참고: [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html), [Redis broker의 visibility timeout](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html), [Windows 지원 FAQ](https://docs.celeryq.dev/en/stable/faq.html#does-celery-support-windows) (2026-10-03 확인).
