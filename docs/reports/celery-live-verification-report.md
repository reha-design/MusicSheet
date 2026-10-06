# Celery 실제 Linux worker 장애 복구·취소 검증

- 날짜: 2026-10-04, Asia/Seoul.
- 사용자 선택: 현재 Celery 유지 + 실제 worker 장애 복구·취소 검증.
- 계획: [R4 검증 계획](../plans/celery-live-verification-plan.md). R1 93점 → R2/R3/R4 각각 독립99점, blocker/important0.
- 기준 소스: `9bca8ce78003ae2148fa1712d6b90344dac888bf`의 git archive + 계획에 명시한 R3 테스트4파일 및 R4 storage/test2파일 overlay. Celery 제품 코드·라이브러리·root/API lock 변경 없음. WAV metadata의 OS 차이는 수정했다.
- 상태: 실제 worker8개, Linux/Windows 전체 회귀 및 검증 환경 정리 완료. 독립 구현 점수 R3 98/R4 99, 전체 최종98점으로 통과했다.

## 실행 환경

Windows의 Docker Desktop Linux engine29.7.2에서 실행했다. Linux kernel6.6.87.2-microsoft-standard-WSL2, x86_64, Python3.13.16, uv0.10.11, Celery5.6.3, Kombu5.6.2, redis-py6.4.0, asyncpg0.31.0, pytest9.1.1이다. root/API `uv sync --locked` 및 각각 `uv lock --check --offline` 성공.

| 이미지 | 실행 digest |
| --- | --- |
| python:3.13-slim-bookworm | `sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed` |
| postgres:16-alpine | `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` |
| redis:7-alpine | `sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99` |

지정한 `ghcr.io/astral-sh/uv:0.10.11-python3.13-bookworm-slim` 태그는 레지스트리에 없었다. 공식 Python 이미지에 `python -m pip install uv==0.10.11`을 실행해 동일 uv 버전을 준비했다. 초기 PowerShell tmpfs 옵션의 쉼표 해석 오류는 문자열 quoting으로 수정했으며, 그 시도에서 생성한 network는 제거한 뒤 재실행했다.

실행 UUID `2c0830c85fb...`의 고유 DB·Redis·runner와 network만 생성했다. 호스트 port/bind mount/기존 volume/socket mount/privileged mode는 사용하지 않았다. PGDATA와 Redis `/data`는 각각256MiB/64MiB tmpfs이며 inspect volume mount0을 확인했다. 별도 DB `musicsheet_test`와 comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1` guard를 적용했다. 공유 `study_postgres`는 변경하지 않았다. 원시 DSN과 임시 credential은 이 문서에 기록하지 않는다.

## 실제 실패와 수정

최초 API pipeline DB suite는 **8pass**, worker suite는 **7pass/kill1fail, 83.90초**였다. 재시작 worker는 ready지만30초 관찰 안에 DOWNLOAD를 수신하지 못했다. Kombu의 초기 scan은5초 visibility 전에 수행되고, event loop10초 호출과 QoS interval10이 결합해 실제 복구 scan은 약100초 간격이다. 기본 설정에서 메시지가 유실됐다고 단정할 증거는 없으며 기존 bounded test와 주기가 맞지 않았다.

테스트 전용 Redis transport를 subclass하여 **scan 호출 횟수 제한만1로 변경**했다. 실제 Redis ACK·만료 timestamp·restore 알고리즘은 Kombu 원본을 호출한다. 제품 transport/default scan 주기/visibility3600은 변경하지 않았다. 신규 회귀는 fake clock의 초기 미만료 scan과10초 뒤 만료 메시지 복구를 실제 inherited restore 경로로 확인하며 원본 QoS가 그대로임도 확인한다. 신규 모듈 부재 RED1fail은 restore assertion까지 도달하지 않았으므로 cadence 실패 증거는 최초 실제 kill 실패·원본 QoS 대조·최종 실제 재전달 성공으로 구분한다. 최종 harness **9pass, 0.56초**. 최초 GREEN의 incomplete boundary double 때문에 종료 finalizer가 AttributeError를 출력했고, double의 `do_restore=False`로 소유하지 않은 shutdown 복구를 막은 뒤 오류 없는 GREEN을 확인했다.

기존 API migration 테스트 두 곳은 v2 fixture에서 ledger2/table5를 받지만 v1의1/4를 기대해 **2fail**했다. 이를 정확한 ledger `[1,2]`와 다섯 canonical table 집합으로 수정해 **2pass/8deselected, 0.46초**를 확인했다. v1 메타데이터 검증 fixture는 보존했다.

변경 코드 범위는 `tests/pipeline/integration/redis_transport.py`, `worker_app.py`, `tests/pipeline/test_live_harness.py`, `services/api/tests/integration/test_postgres_persistence.py` 네 파일이다.

## 최종 worker 실행 증거

```sh
uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests/integration/test_pipeline_persistence.py -q -ra
DATABASE_URL="$MUSICSHEET_TEST_DATABASE_URL" uv run --project services/api --offline --no-sync --python 3.13 musicsheet-migrate
uv run --project . --offline --no-sync --python 3.13 pytest tests/pipeline/integration/test_live_worker.py -v -ra --basetemp /work/live-results-green
```

각 suite는 serial 실행했다. worker 명령에는 외부900초 timeout을 적용했으며 초과하지 않았다. API DB8pass/skip0/fail0, migration current2, 최종 worker **8pass/skip0/fail0, 68.02초**다.

| 시나리오 | 확인 결과 |
| --- | --- |
| normal | 실제6단계·아티팩트6개·DB 완료 및 HTTP SSE terminal 이벤트 |
| retry_once | provider 첫 실패 후 durable 예약으로 성공, attempt/generation 기록 |
| duplicate | 중복 delivery의 DOWNLOAD provider 호출1회 |
| contend | prefork2의 advisory lock 경합과 재시도 후 완료 |
| kill | 처리 시작 증거 후 소유 worker group SIGKILL, 재시작 뒤 원래 delivery 재전달 및 완료 |
| cancel | 실행 중 DB 취소 요청 후 CANCELED와 HTTP SSE 확인 |
| commit_failure | publish후 outbox commit 실패의 중복 delivery가 안전하게 완료 |
| broker_failure | 소유 TCP proxy cut 중 retry 발행 실패, 실제5초 지연 후 requeue와 완료 |

kill 로그에서 task `34dd943f-3b18-49b2-a246-09ae83ecf97a`는01:34:30.157 UTC에 최초 수신됐다. 재시작 worker는01:34:30.535 ready였고01:34:40.533에 **같은 task ID**를 다시 수신했다. 종료한 메시지를 수동 발행하지 않았다. 실제 로그와 별도 worker-app transport 로딩 확인 모두 `VerificationRedisTransport`/`VerificationRedisQoS` 선택을 확인했다.

## 전체 회귀·리뷰·정리

최초 Linux 전체 회귀는 API257pass와 root222pass/1fail/1skip였다. root 실패는 WAV MIME의 OS 차이(`audio/x-wav` vs 기존 `audio/wav` 계약)였다. R4 독립 계획99점 후 canonical owner에 규칙을 명시하고 `.wav`/`.WAV` 회귀2개 RED를 확인했다. non-WAV unknown/JSON/PDF metadata 보존3개는 기존 코드에서도 pass했다. 확장자에 한정해 `LocalStorage.put`의 반환 metadata를 수정한 뒤 storage **41pass**를 확인했다. 기존 bytes·SHA256·자원 수명·경로 검사와 과거 DB metadata는 변경하지 않았다.

| 최종 검증 | 결과 |
| --- | --- |
| Linux root 전체 (`-m 'not ml_integration and not celery_integration'`) | **228pass/1skip/12deselected**, 2.04초 |
| Linux API 전체 (실제 owned DB·Redis opt-in 설정) | **257pass/skip0**, 3.76초, 기존 경고1 |
| Windows root 전체 (기본 ML 제외) | **225pass/12skip/4deselected**, 6.56초 |
| Windows API 전체 (live opt-in unset) | **232pass/25skip**, 2.30초, 경고2 |
| 호스트 Compose 설정 검사 | **3pass**, 0.36초 |
| root/API lock checks (Linux 및 Windows) | 모두 성공, lock 변경0 |
| `git diff --check` | 성공 |

Linux skip1은 runner의 Docker CLI 부재이며 동일 Compose 검증을 호스트에서 별도로 통과했다. Linux deselect12는 앞서 실행한 worker8개와 이번 범위 밖 ML4개다. Windows skip12는 Linux worker8개와 symlink 권한4개, API skip25는 DB18/Redis7 opt-in unset이다. 같은 live DB18/Redis7 사례는 Linux API 전체에서 pass했다.

최종 명령(cwd: repo root):

```sh
uv run --project . --offline --no-sync --python 3.13 pytest tests -q -ra -m 'not ml_integration and not celery_integration'
uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests -q -ra
# Windows root uses its default ML exclusion; live worker cases report Linux-only skip.
uv run --project . --offline --no-sync --python 3.13 pytest -q -ra
uv run --project . --offline --no-sync --python 3.13 pytest tests/infra/test_docker_compose.py -q -ra
uv lock --check --offline
uv lock --project services/api --check --offline
```

R3 독립 구현: `/root/celery_live_implementation_review`, 2026-10-04, 25+25+23+15+10 =**98/100**, blocker0/important0. minor1(RED 표현)은 위처럼 모듈 부재 RED와 cadence 증거를 구분해 처리했다.

R4 단위 및 전체 최종 독립 리뷰: `/root/celery_live_final_review`, 2026-10-04. R4 단위는25+25+24+15+10 =**99/100**, 전체는25+25+24+15+9 =**98/100**, 모두 blocker0/important0. minor1(`/proc` 체크 증거 출처)은 다음 문단에 parent tool stdout과 후속 전사본임을 명시해 처리했다. 6개 code SHA256, 회귀 count, 비WAV fallback, 제품 Celery/lock 비침범을 확인했다.

runner의 `/proc` 확인에서 소유 worker/API process 잔여0을 확인했다. 이 체크의 원본은 실행 시 parent tool stdout이며 파일로 redirect하지 않았다. `pre-cleanup-process-observation.md`는 해당 실제 출력과 exit0의 후속 전사본이다. 삭제 후 결과의 원본 파일로그 `cleanup.log`와 구분한다. cleanup은 setup 로그의 생성 ID·고유 이름·UUID label 세 조건을 재확인하고 소유 container3개와 network1개만 제거했다. **소유 container0/network0/volume mount0**, 임시 credential 파일2개 제거를 확인했고 공유 `study_postgres`는 계속 실행 중이었다. 기존 공유 서비스·volume은 변경하지 않았으며 전체 prune/FLUSHDB/FLUSHALL은 사용하지 않았다. 진단 log와 source archive만 ignored tmp 폴더에 보존했다.

검증한 overlay의 SHA256(원본 파일 bytes; Windows Git의 줄바꿈 정규화와 구분):

| 파일 | SHA256 |
| --- | --- |
| `tests/pipeline/integration/redis_transport.py` | `4a8f86b212726f0dfd074bb85f27d5dd21f87e35c60f40f3017c5f445eee5ff1` |
| `tests/pipeline/integration/worker_app.py` | `c3e73ff61bbe3607f2d2154bed45564d42d5883c2d94a11e4e943c18a8c3a664` |
| `tests/pipeline/test_live_harness.py` | `8fa1c331d4b2998b5b40a0fe855c88c7d918964a01ec3dc6a21410fca415318e` |
| `services/api/tests/integration/test_postgres_persistence.py` | `ab0825fd8045191af36c16f2f86f38cf72f1c0f85e8c742bcff964666312f0f6` |
| `packages/storage/musicsheet_storage/local.py` | `32c5a4f60ddfbf207616ca024a6a2c1b39f681b6ca8c3a199cc40ceeff89d94f` |
| `tests/unit/test_storage.py` | `c82417da6753a4404534bdc6a6715abe4d08abe99d797a2882a61b34e0666e24` |

## 검증 범위와 운영 제약

실제 Linux prefork·PostgreSQL·Redis·HTTP API/SSE를 사용했지만 **provider는 테스트 전용**이다. 실제 YouTube 다운로드, Basic Pitch/다른 모델, GPU 자원 정리, 악보 렌더링은 이번 검증에 포함하지 않았다.

visibility5초·scan 호출 interval1은 테스트 조건이다. 운영 visibility3600초와 Kombu 기본 scan 주기에서 실제 복구 지연을 측정하지 않았다. '10초 안에 운영 복구'나 'Celery 교체/업그레이드가 영구 불필요'를 결론으로 삼지 않는다. 현재6.4 클라이언트 조합에서 위 orchestration 시나리오가 실행 가능하다는 증거다.

API 테스트의 Starlette/httpx deprecation warning은 기존 의존성 경고이며 이 범위에서 교체하지 않는다. Windows API에는 pytest cache 쓰기 권한 경고1개가 추가됐지만 테스트 exit0이며 코드·캐시 권한을 변경하지 않았다. 로그는 `tmp/celery-live-20261004/`의 ignored 진단 자료로 보존하고 보고서의 count/명령/제약을 Git으로 남긴다. 제품 Celery 설정·라이브러리 교체·push/PR/merge는 수행하지 않는다.
