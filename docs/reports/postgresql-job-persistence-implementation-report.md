# PostgreSQL 작업 영속성 통합 검증 보고서

> **작성 일자:** 2026-09-27
> **범위:** 승인된 PostgreSQL 작업 영속성 계획 Task 3
> **독립 코드 리뷰:** 2026-09-27, 98/100. blocker/important 없음. Task 3 게이트 통과.

## 구현 내용과 버전

- PostgreSQL 16.14 (`postgres:16-alpine`), Python 3.13.7, uv 0.10.11, asyncpg 0.31.0, pytest 9.1.1에서 검증했습니다. API에 새 런타임 의존성을 추가하지 않았고 루트 `pyproject.toml`과 `uv.lock`은 변경하지 않았습니다.
- `musicsheet-migrate`의 migration version 1이 `jobs`, `stage_attempts`, `artifacts`를 생성하고 `schema_migrations`에 기록합니다. 실제 PostgreSQL 카탈로그에서 네 테이블 전체 목록, 애플리케이션 세 테이블의 모든 컬럼 타입·varchar 길이·NULL 허용·기본값, 기본키/보조 인덱스, 두 FK의 `ON DELETE CASCADE`를 확인했습니다. 삽입 결과로 `jobs`/`stage_attempts`의 기본값과 세 테이블의 timezone 있는 타임스탬프도 확인했습니다.
- 통합 테스트는 `MUSICSHEET_TEST_DATABASE_URL`이 있어야 실행됩니다. 각 동작 테스트의 스키마 초기화 직전 서버의 현재 DB 이름 `musicsheet_test`와 DB comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1`을 검증합니다. guard 테스트는 스키마를 초기화하지 않습니다. 실패 출력의 fixture URL 표현과 통합 DB 예외는 일반 메시지로 가립니다.
- 실제 DB RED에서 기존 `JobRepository.update_progress`의 `$2` 파라미터가 상태 컬럼과 `CASE`에서 서로 다르게 추론되어 `asyncpg.exceptions.AmbiguousParameterError`가 발생했습니다. `$2::VARCHAR(20)`을 명시하여 GREEN으로 만들었습니다. 이는 Task 2 코드의 단일 SQL 교정입니다.
- API README와 데이터베이스 사양에 명시적 migration 명령, ledger·동시 실행·롤백 방식, 선택적 pool의 장애 동작, 저장소 범위, 안전한 테스트 DB 준비/호출을 기록했습니다. 이 작업은 job REST endpoint를 추가하지 않습니다.

## 검증 결과

| 명령 / 단계 | 결과 |
| :--- | :--- |
| PostgreSQL 일회용 DB `CREATE DATABASE musicsheet_test`와 `COMMENT ON DATABASE ... IS 'MUSICSHEET_DISPOSABLE_TEST_DB_V1'` | 성공. 기존 `musicsheet` DB/volume/container는 초기화하지 않음 |
| 통합 테스트 첫 RED: `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_postgres_persistence.py -q` (저장소 루트) | 6 passed, 3 failed. FK 삭제동작 코드값의 bytes 비교와 테스트 시계 기준을 고쳤으며, 진행률 갱신의 실DB 타입 충돌은 생산 코드에서 고침. 출력에 URL fixture 표현이 나타나 이후 가림 |
| 통합 테스트 최종 GREEN: 구현자 실행, 동일 명령, `MUSICSHEET_TEST_DATABASE_URL` 설정 | 9 passed in 2.19s. guard 2, schema 1, idempotence 1, concurrent runner 1, rollback 1, repository 왕복 1, 경계값 1, cascade 1 |
| 통합 테스트 재실행: 컨트롤러의 독립 확인, 동일 명령과 DB 설정 | 9 passed in 2.34s. 위 실행과 별도의 재실행이며, 검토자 보고서 및 최종 증거에는 이 재실행 결과를 사용 |
| `uv run --project . --python 3.13 musicsheet-migrate` (`services/api`, `DATABASE_URL`을 disposable DB로 설정) | `Applied versions: []; current version: 1` |
| `uv run --project services/api --python 3.13 pytest services/api/tests -q` (저장소 루트, 통합 URL 미설정) | 68 passed, 9 skipped, StarletteDeprecationWarning 1건 |
| `uv run --project . --python 3.13 pytest -q` (`services/api`, 통합 URL 미설정) | 68 passed, 9 skipped, StarletteDeprecationWarning 1건 |
| `uv run --project . pytest -q` (저장소 루트) | 54 passed, 3 skipped, 4 deselected |
| `uv lock --check` (`services/api`) | 성공, 27 packages resolved |
| `uv lock --check` (저장소 루트) | 성공, 14 packages resolved |
| `git diff --check` | 성공 |

통합 URL 없이 실행한 API 전체 테스트에서 통합 테스트 9개가 의도대로 건너뛰어졌습니다. 기존 `starlette.testclient` 경로의 StarletteDeprecationWarning 1건은 남아 있습니다. DB 연결 실패 시 API 기동/health 동작은 Task 2의 기존 unit 테스트에서 검증했으며, 이 Task 3에서는 별도 실DB 장애 주입을 하지 않았습니다.

## 리뷰 게이트와 제한

- 계획 revision 8의 독립 점수는 **99/100**, blocker/important 없음입니다.
- Task 1 코드 리뷰는 **98/100**, Task 2는 **97/100**, Task 3는 **98/100**으로 각각 독립 리뷰 게이트를 통과했습니다. 전체 코드 리뷰는 Task 1: `d0597b5..3d0caf0`, Task 2: `20602dd..74ee298`, Task 3: Task 3 구현 커밋 `f3342e1`의 변경분을 검토했습니다. 각 Task 리뷰에서 blocker/important는 없었습니다.
- Task 1 리뷰의 경미한 지적 두 건은 후속 동작 변경 범위를 키우지 않는 개선 제안으로 기록했습니다. `musicsheet-migrate`의 “current version” 표시는 패키지 migration의 최고 버전을 뜻하며, DB ledger와의 차이를 표시하지 않을 수 있습니다. advisory unlock 실패가 기존 migration 오류를 가릴 수도 있습니다. 둘 다 현재 완료 기준의 실패나 보안 문제는 아니어서 후속 개선 항목으로 남겼습니다.
- Task 2 리뷰의 실제 PostgreSQL 기본값·timestamp 확인 제안은 Task 3 통합 테스트에서 검증했습니다. Task 3 리뷰는 **98/100** (외부 동작 25/25, 오류·경계·보안 25/25, 테스트·증거 24/25, 구조·의존성 15/15, 문서·재현성 9/10)으로 통과했습니다. blocker/important는 없으며, 보고서 실행시간은 구현자 실행 2.19초와 컨트롤러 재실행 2.34초를 별도 기록했습니다.
- Task 3를 포함해 모든 세 구현 단위가 계획의 순서대로 독립 코드 리뷰 95점 이상을 받았습니다. 최종 roadmap 상태는 Done입니다.
- 실제 DB 테스트는 지정된 PostgreSQL 16.14 인스턴스에서 실행했습니다. 다른 PostgreSQL 버전이나 원격 배포 환경은 검증하지 않았습니다.
