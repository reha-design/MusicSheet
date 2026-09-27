# PostgreSQL 마이그레이션 러너 구현 보고서

> **작성 일자:** 2026-09-27
> **범위:** PostgreSQL 작업 영속성 계획 Task 1
> **리뷰 상태:** 독립 코드 리뷰 대기

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
| API 전체 테스트 | `uv run --project services/api --python 3.13 pytest -q` | 54 passed, 3 skipped, 4 deselected |
| 변경 검증 | `git diff --check` | 통과 |

가짜 연결 테스트는 버전 정렬과 건너뛰기, 잠금 획득 순서, 단일 연결 사용, 트랜잭션 rollback, 실패 후 잠금 해제와 종료, CLI 오류 메시지의 비밀값 비노출을 검증합니다. 실DB 스키마 catalog와 재실행·동시성 검증은 계획의 Task 3 통합 테스트에서 수행합니다.

## 리뷰 기록

구현 전 계획 revision 8은 2026-09-27 독립 평가 99/100으로 통과했고 blocker/important 지적은 없었습니다. Task 1 코드 독립 리뷰 점수와 지적 사항은 현재 대기 중이며, 리뷰 완료 후 기록합니다.
