# PostgreSQL 마이그레이션 러너 구현 보고서

> **작성 일자:** 2026-09-27
> **범위:** PostgreSQL 작업 영속성 계획 Task 1
> **독립 코드 리뷰:** 98/100 통과 (2026-09-27; blocker/important 없음)

## 구현 내용

- `musicsheet-migrate` 명령을 추가했습니다. `DATABASE_URL`을 프로세스 환경에서 직접 읽고, 성공 시 적용한 버전과 현재 패키지 버전을 출력합니다. 오류 시 연결 문자열과 드라이버 예외를 노출하지 않는 일반 메시지와 종료 코드 1을 반환합니다.
- 마이그레이션 러너는 하나의 PostgreSQL 연결에서 세션 advisory lock을 획득한 뒤 `schema_migrations` 이력을 만들고 조회합니다. 버전별 DDL과 이력 INSERT를 같은 트랜잭션에서 실행하며, 종료 시 잠금을 해제하고 연결을 닫습니다.
- v1 마이그레이션은 [데이터베이스 사양](../backend/database.md)의 `jobs`, `stage_attempts`, `artifacts` 테이블과 인덱스, 외래 키의 cascade 동작을 구현합니다.
- API pool, repository, endpoint, PostgreSQL 실DB 통합 테스트는 이후 작업 범위입니다.

## 변경 파일

- `services/api/src/musicsheet_api/migrations/__init__.py`
- `services/api/src/musicsheet_api/migrations/runner.py`
- `services/api/src/musicsheet_api/migrations/v0001_initial.py`
- `services/api/src/musicsheet_api/migrations/cli.py`
- `services/api/pyproject.toml`
- `services/api/tests/test_migrations.py`
- `docs/reports/postgresql-migration-runner-implementation-report.md`
- `docs/main_spec.md`의 Reports 색인 1줄

## 검증 결과

| 단계 | 명령 | 결과 |
| :--- | :--- | :--- |
| TDD RED | `uv run --project services/api --python 3.13 pytest services/api/tests/test_migrations.py -q` | 테스트 수집 중 `ModuleNotFoundError: No module named 'musicsheet_api.migrations'`로 종료 코드 1. 구현 전 패키지 부재를 확인했습니다. |
| TDD GREEN | 같은 명령 | 8 passed |
| 저장소 루트 테스트 | `uv run --project services/api --python 3.13 pytest -q` (저장소 루트에서 실행) | 54 passed, 3 skipped, 4 deselected. 루트 `pyproject.toml`의 `testpaths = ["tests"]` 설정에 따라 API 테스트는 수집하지 않습니다. |
| API 전체 테스트 | `uv run --project services/api --python 3.13 pytest services/api/tests -q` | 38 passed, StarletteDeprecationWarning 1건 |
| 변경 검증 | `git diff --check` | 통과 |

가짜 연결 테스트는 버전 정렬과 건너뛰기, 잠금 획득 순서, 단일 연결 사용, 트랜잭션 rollback, 실패 후 잠금 해제와 종료, CLI 오류 메시지의 비밀값 비노출을 검증합니다. 실DB 스키마 catalog와 재실행·동시성 검증은 계획의 Task 3 통합 테스트에서 수행합니다.

## 리뷰 기록

계획 revision 8은 구현 전 독립 평가에서 99/100을 받았습니다. Task 1 코드는 2026-09-27 독립 평가 **98/100**으로 통과했습니다.

| 평가 기준 | 점수 |
| :--- | ---: |
| 외부 동작 정확성 | 25/25 |
| 오류 처리, 경계 및 보안 | 24/25 |
| 테스트와 검증 증거 | 24/25 |
| 구조와 유지보수성 | 15/15 |
| 문서와 재현성 | 10/10 |
| **합계** | **98/100** |

blocker 또는 important 지적이 없어 Task 2 진행 게이트를 통과했습니다. 아래 경미한 제안은 최종 리뷰에서 재검토하도록 보류했습니다.

- CLI가 DB ledger의 실제 버전 대신 패키지에 포함된 가장 높은 버전을 `current version`이라고 표시합니다. 실제 DB 버전으로 오인될 수 있습니다.
- advisory lock 해제 중 오류가 발생하면 원래 migration 오류를 가릴 수 있습니다. 연결 종료는 계속 수행됩니다.

실 PostgreSQL catalog, 재실행 및 동시성 동작은 계획된 Task 3 통합 테스트 대상이므로 이번 변경 diff에서는 판정하지 않았습니다.
