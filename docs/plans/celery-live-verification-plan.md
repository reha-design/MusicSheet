# Celery 실제 Linux worker 검증 계획

- Revision: R4, 2026-10-04.
- 사용자 범위: 현재 Celery 유지 + 실제 worker 장애 복구·취소 검증.
- 기준 소스: `9bca8ce`; Celery 제품 구현과 라이브러리/lock을 변경하지 않는다. 아래 R3 테스트 수정과 R4 WAV MIME 수정 파일만 snapshot에 명시적으로 overlay하고 최종 diff/commit을 기록한다.
- 사양: `docs/backend/celery.md`, `docs/architecture/job-pipeline.md`, `docs/domain/job-state.md`, W03 실행 계획 Task4와 `packages/pipeline/README.md`.

## 범위와 실행 환경

Windows 호스트에 Docker Linux engine29.7.2가 실행 중이다. 기존 `study_postgres` 등 공유 컨테이너는 조회 외에 접근하지 않는다. W03 계획에서 제외했던 공유 인프라 시작 대신 이번 검증만 소유하는 컨테이너·network를 생성한다. 호스트 port, bind mount, 기존 volume, Docker socket mount, privileged mode는 사용하지 않는다. PostgreSQL16-alpine·Redis7-alpine과 Python3.13/uv0.10.11 공식 runner image를 사용하고 실제 image ID/digest·Python 버전을 보고한다.

이 작업은 기존 harness 실행과 결과 문서화다. 제품 코드 변경이 필요해지면 원인·수정 범위·RED/GREEN 검증을 계획 revision에 추가하고 독립95점 리뷰를 다시 받은 뒤 수정한다. 구현 단위별 독립95점 코드 리뷰를 적용한다. 테스트 실패를 skip·timeout 확대·assertion 제거로 숨기지 않는다.

## 단위1 — 격리된 환경과 기존 테스트 실행

1. `tmp/celery-live-<UUID>/`에 상태·log·소유 resource 목록을 기록한다. `git archive 9bca8ce`로 tracked source만 복사해 `.git`, `.env`, 호스트 venv·모델·미커밋 변경을 반입하지 않는다. `.env.example` 외 실제 credential 파일이 tracked 상태가 아닌지 preflight 확인한다.
2. 고유 이름과 `musicsheet.live.run=<UUID>` label로 network·postgres·redis·runner를 생성한다. 외부 공개 port 없이 runner만 이 DB·Redis 주소를 사용한다. 이미지의 declared VOLUME 경로인 `/var/lib/postgresql/data`와 `/data`에 각각 소유 tmpfs(256MiB/64MiB)를 명시하여 anonymous/named volume을 만들지 않는다. 각 container inspect Mounts에서 volume0을 확인하며 예상 밖 volume은 환경 시작 실패로 처리하고 해당 실행에서 생성된 ID만 소유 목록에 기록해 container 제거 후 정리한다. 기존 compose를 시작하지 않는다. 초기화 password는 이 실행만의 임시 값으로 생성하며 shell output·보고서에 기록하지 않는다.
3. PostgreSQL에 새 `musicsheet_test` DB를 생성하고 comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1`를 설정한다. readiness는 `pg_isready`와 `redis-cli ping`으로 각각 최대30초 내 확인한다. 성공하지 않으면 시작 중단하고 소유 resource를 정리한다.
4. runner에 source snapshot을 복사·추출한다. `uv sync --project . --locked --python 3.13` 및 API 동일 명령으로 Linux 환경을 별도로 구성한다. root/API lock check와 Python/uv·Celery/Kombu/redis 버전을 기록한다. 다운로드 실패는 환경 실패로 기록하고 제품 코드에 우회 변경하지 않는다.
5. `MUSICSHEET_TEST_DATABASE_URL`, `MUSICSHEET_TEST_REDIS_URL`, `MUSICSHEET_TEST_CELERY=1`을 runner에만 설정한다. DB URL은 DB 이름/comment guard를 통과해야 한다. API DB suite 실행 → 명시적 migration v2 재적용 → root worker suite 실행 순서이며 serial 실행한다.

실행 명령(각각 exit code와 pytest count 저장):

```sh
uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests/integration/test_pipeline_persistence.py -q -ra
DATABASE_URL="$MUSICSHEET_TEST_DATABASE_URL" uv run --project services/api --offline --no-sync --python 3.13 musicsheet-migrate
uv run --project . --offline --no-sync --python 3.13 pytest tests/pipeline/integration/test_live_worker.py -q -ra --basetemp /work/live-results
```

합격 조건은 API DB suite와 **worker8개 시나리오 모두 pass, skip0, fail0**이다. `normal/retry_once/duplicate/contend/kill/cancel/commit_failure/broker_failure`는 실제 Linux prefork2, PostgreSQL, Redis, API subprocess와 HTTP SSE를 관찰한다. 테스트 provider만 사용하며 실제 YouTube·AI 모델·GPU 취소 검증으로 해석하지 않는다. kill은 테스트 소유 process group만, broker cut은 소유 TCP proxy만 대상으로 한다. 테스트 visibility5초와 운영3600초의 차이를 보고한다. 관찰 deadline30초, scenario80초 및 cleanup40초 예산은 기존 harness를 유지한다. 전체 worker 실행은 외부15분 deadline으로 제한하고 초과 시 실패 처리 및 runner 종료로 소유 process를 정리한다.

## 단위2 — 결과와 정리

단위1 결과·명령·환경·8개 시나리오와 cleanup 상태를 독립 reviewer가 확인한 뒤 전체 회귀로 이동한다. 제품 코드가 바뀌지 않은 실행 증거 리뷰는 구현 코드 점수와 구분해 기록한다. 단위1이 실패하면 이 리뷰는 실패 원인·수정 계획의 독립 검토로 대체하고, 단위2가 단위1을 통과시켰다고 기록하지 않는다.

1. 기존 테스트가 pass이면 동일 Linux 환경의 `/work/repo` cwd에서 전체 회귀를 실행한다. root는 `uv run --project . --offline --no-sync --python 3.13 pytest tests -q -ra -m 'not ml_integration and not celery_integration'`, API는 `uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests -q -ra`이다. ML 및 별도 opt-in 미실행은 사유별로 분리하며 worker8개는 다시 실행하지 않는다. API 전체가 disposable schema를 reset할 수 있으므로 worker suite 이후에 실행한다. 새 실패가 없으면 반복 검증하지 않는다.
2. 실패 시 pytest 결과와 `/work/live-results`의 소유 worker/API logs를 수집해 원인을 조사한다. 공개 문서에는 credential·원시 DSN을 넣지 않는다. 단위1 실패는 단위2 성공으로 대체하지 않는다.
3. `finally`에서 실행 UUID label과 목록의 이름·ID를 재확인하고 **이번에 생성한** runner·Redis·PostgreSQL만 `docker rm -f`로 정리하며 network를 제거한다. 전체 prune·공유 container 종료·공유 volume 삭제·FLUSHDB/FLUSHALL은 금지한다. 예상 밖 anonymous volume이 있었을 때만 소유 목록에 기록한 해당 ID를 정리한다. runner 삭제로 남은 subprocess가 정리되는지도 확인한다. image 다운로드 cache는 유지한다.
4. resource label 조회 결과가 빈 목록임을 확인한다. 테스트 결과·이미지/버전·소스 hash·명령·제약·정리 증거를 `docs/reports/celery-live-verification-report.md`에 기록하고 main_spec 색인을 추가한다. 성공 시 현재 상태 문서의 'Windows 호스트에서 미검증'을 Linux container 검증 사실과 테스트 provider 제약으로 갱신한다. W04는 착수하지 않는다.
5. 문서 diff check 후 관련 문서만 명시적으로 stage하고 Conventional Commit으로 기록한다. 런타임·제품 코드 변경이 없으면 구현 점수를 창작하지 않고 독립 결과 리뷰에서 증거 정확성을 확인한다. 실패하거나 실행 환경이 막히면 미검증으로 기록한다.

## 독립 리뷰 기록

R1 독립 평가: /root/celery_live_plan_review, 2026-10-04, 25+19+18+23+8 =93/100, important2/minor1. R2에서 declared VOLUME 경로의 tmpfs·Mounts 검증·예외 소유 volume 정리, API/root 전체 회귀의 cwd와 test path, 단위1 실행 증거 리뷰 시점을 명시했다.

R2 독립 평가: 같은 reviewer, 2026-10-04, 25+20+20+25+9 =99/100, blocker0/important0, R1 지적 모두 처리. runner image reference는 실행 결과의 digest/버전으로 보완한다. R2 환경 생성·실행 gate 통과.

## R3 — 실제 실패에 근거한 테스트 수정 단위

R2 실행 결과: API pipeline DB8pass. worker7pass/kill1fail, 83.90초. 취소·broker failure는 통과했다. 재시작 worker는 ready이나 DOWNLOAD를 수신하지 못했다. 설치된 Kombu5.6.2 소스에서 `on_poll_init()`이 처음 `restore_visible()`을 호출하고, event loop는10초마다 호출하지만 QoS는 기본 interval10으로 호출10번 중1번만 실제 스캔한다. 즉 visibility5초 전에 초기 스캔 후 다음 실제 스캔이 약100초 뒤여서 기존30초 관찰과 맞지 않는다. 제품 메시지 유실로 판정할 증거는 없으며, 실제 복구 시간의 visibility+scan 지연도 문서화한다.

추가 실제 RED: API `test_migration_is_repeatable`과 `test_concurrent_migration_runners_apply_once`가 v2 fixture에서 ledger2/table5를 받으나 v1의1/4 기대값으로 실패했다(2fail/8deselected). v1 메타데이터 검증 fixture는 그대로 보존한다.

단일 구현 단위는 다음 네 파일이다.

- 새 `tests/pipeline/integration/redis_transport.py`: Redis transport/Channel/QoS를 subclass하여 **테스트 worker만** `restore_visible`의 default interval을1로 설정한다. 기존 실제 Redis ACK·timestamp·visibility·restore 알고리즘은 그대로 호출한다. monkeypatch·수동 restore·추가 task 발행은 사용하지 않는다.
- `tests/pipeline/integration/worker_app.py`: 위 test-only transport를 `broker_transport`로 지정한다. 제품 factory/consumer는 변경하지 않는다. 기존5초 visibility와10초 실제 스캔으로30초 관찰 안에 실제 재전달을 검증한다.
- `tests/pipeline/test_live_harness.py`: 모듈 import에 제품/network side effect가 없는지 확인하고, clock+fake Redis boundary로 초기 t0 미만료 스캔 후 t10에서 만료 전달이 실제 restore되는 의미 있는 회귀를 먼저 작성·RED 실행한다. 실 kill RED 결과도 보존한다. 원본 Redis QoS는 default interval10을 유지함을 assert하여 제품 설정 오염을 막는다.
- `services/api/tests/integration/test_postgres_persistence.py`: 두 v2 migration 테스트에서 ledger를 `[1,2]`, canonical table 집합을 jobs/stage_attempts/artifacts/schema_migrations/pipeline_outbox로 정확하게 검증한다. v1 메타데이터 테스트는 변경하지 않는다.

실행 순서: R3 독립 계획95점 승인 → 신규 회귀 RED → 테스트 수정 → 네 파일만 기존 runner snapshot에 overlay → 신규 회귀와 migration 두 사례 GREEN → migration v2 확인 → worker8개 전체 pass/skip0/fail0 → 독립 구현95점 리뷰(blocker/important0) → root/API 전체 회귀 및 단위2 문서·정리. 소스 hash는 baseline+명시적 diff hash 및 최종 commit으로 기록한다. 다른 실제 실패가 나타나면 원인과 수정 범위를 계획에 반영해 다시 리뷰한다.

```sh
uv run --project . --offline --no-sync --python 3.13 pytest tests/pipeline/test_live_harness.py -q -ra
uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests/integration/test_postgres_persistence.py -q -ra -k 'migration_is_repeatable or concurrent_migration_runners_apply_once'
```

테스트를 위해 poll cadence를 바꿨으므로 운영3600초 설정의 recovery latency를 검증했다고 주장하지 않는다. 실패1의 원인 추정은 수정 후 실제 kill 재전달 성공으로 추가 확인해야 한다.

R3 독립 평가: /root/celery_live_plan_review, 2026-10-04, 25+20+20+24+10 =99/100, blocker0/important0. 실제 inherited restore 실행·custom transport 선택·재발행 없는 kill 재전달은 구현 증거 리뷰에서 확인한다. 테스트 수정 단위 gate 통과.

R3 단일 구현 단위 독립 리뷰: /root/celery_live_implementation_review, 2026-10-04, 25+25+23+15+10 =98/100, blocker0/important0. 신규 모듈 부재 RED와 실제 cadence RED를 구분하라는 minor는 보고서에 명시한다. 실제 worker8pass(68.02초), 동일 task ID 복구, inherited 알고리즘, 제품 transport 비침범을 확인해 단위2 gate 통과.

## R4 — Linux 전체 회귀에서 발견한 WAV metadata 수정 단위

실제 전체 회귀: API257pass/skip0(기존 warning1), root222pass/1fail/1skip/12deselected. 실패는 `test_local_storage_put_from_path_copies_bytes_and_returns_metadata`: Linux의 `mimetypes.guess_type('canonical.wav')`가 `audio/x-wav`를 반환하여 기존 `audio/wav` 계약과 다르다. root skip1은 runner에 Docker CLI가 없기 때문이며, 같은 Compose 설정 검증을 호스트 Docker CLI에서 별도로 실행한다. 실패 또는 skip을 숨기지 않는다.

수정 단위는 LocalStorage WAV metadata의 OS 독립성만 다룬다. 사양 owner `docs/domain/artifacts.md`에 `.wav` 확장자(case insensitive)는 저장 metadata `audio/wav`를 반환하며 내용 검증·sniffing은 아니라는 규칙을 먼저 명시한다. 나머지 확장자는 기존 `mimetypes.guess_type` 및 unknown `application/octet-stream` 동작을 유지한다. 등록된 artifact의 과거 metadata/DB를 변경하지 않는다.

1. R4 독립 계획95점/blocker·important0 후 `tests/unit/test_storage.py`에 OS mapping을 `audio/x-wav`로 주는 회귀를 작성해 `.wav`/`.WAV` 각각 RED를 확인한다. 실제 storage.put 결과·저장 bytes·SHA256을 검사하며 mock의 호출 자체를 검증하지 않는다. 기존 unknown `.bin`과 JSON/PDF 경로는 전체 storage suite로 검증한다.
2. `packages/storage/musicsheet_storage/local.py`의 MIME 선택에서 `.wav` 확장자만 canonical 값을 적용한다. 두 파일과 사양 변경만 명시적으로 overlay한다. 바이트 복사·자원 수명·경로 검증·멱등성은 변경하지 않는다.
3. storage 전체 GREEN → Linux root/API 전체 회귀 재실행 → Windows host root/API 전체 회귀. API는 공유 DB를 사용하지 않고 Linux의 owned DB·Redis에서만 opt-in live를 실행한다. Windows는 기존 opt-in unset skip을 기록한다. uv lock/root/API checks와 diff check도 실행한다.
4. 단위2 변경·전체 증거·문서·소유 리소스 정리의 독립 구현 리뷰95점/blocker·important0을 받은 뒤 완료 문서 커밋을 기록한다. worker8개 증거는 `.bin` 아티팩트를 쓰는 R3 실행에서 확보했으며 MIME 수정은 WAV에 한정되어 불필요하게 다시 실행하지 않는다. 제품 Celery/Kombu/redis 버전 변경은 없다.

```sh
uv run --project . --offline --no-sync --python 3.13 pytest tests/unit/test_storage.py -q -ra
```

R4 독립 계획 평가: /root/celery_live_plan_review, 2026-10-04, 25+20+20+24+10 =99/100, blocker0/important0. minor1(기존 suite의 JSON/PDF/unknown MIME 보존 직접 증거 없음)은 해당 세 metadata 반환 회귀를 추가해 보완한다. R4 수정 단위 gate 통과.

R4 단위 독립 구현 리뷰: /root/celery_live_final_review, 2026-10-04, 25+25+24+15+10 =99/100, blocker0/important0. 전체 최종 리뷰는25+25+24+15+9 =98/100, blocker0/important0. minor(`/proc` 체크 원본은 parent tool stdout, 파일은 전사본)은 보고서에 구분해 처리했다. Linux root228/API257, Windows root225/API232 pass와 소유 container/network0을 확인했다. 결과·skip·warning·명령·SHA256은 보고서에 기록한다.
