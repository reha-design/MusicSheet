# PostgreSQL API 풀 및 작업 저장소 구현 보고서

> **작성 일자:** 2026-09-27
> **범위:** PostgreSQL 작업 영속성 계획 Task 2
> **독립 코드 리뷰:** 대기 중 (계획 revision 8은 별도 99/100 승인)

## 구현 내용

- API lifespan에 선택적 `asyncpg` 풀을 추가했습니다. `DATABASE_URL`이 없거나 풀이 열리지 않으면 `app.state.db_pool`은 `None`이며, 실패 로그는 연결 세부 정보를 포함하지 않습니다. 연결 제한 시간은 1초이고, 열린 풀은 종료 시 닫습니다. API 시작 시 migration을 실행하지 않습니다.
- 불변 `JobRecord`에 `jobs` 테이블의 전체 필드와 정확한 nullable 타입을 정의했습니다. 상태와 단계는 공용 `JobStatus`/`PipelineStage`를 사용합니다.
- `JobRepository`에 생성, 단건 조회, 진행률 갱신만 추가했습니다. 생성 ID는 UUID v4, 입력값은 SQL 바인딩 파라미터이며, `YOUTUBE`/`UPLOAD`와 0..100 정수 진행률을 검사합니다. 명시적인 `target_instrument=None`을 보존하고, 알 수 없는 DB enum 값이나 DB 오류는 호출자에게 전달합니다.
- 기존 health endpoint의 응답 형태와 readiness probe는 그대로 유지했습니다.

## 검증 결과

| 단계 | 저장소 루트 실행 명령 | 결과 |
| :--- | :--- | :--- |
| 저장소 TDD RED | `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_repository.py -q` | 구현 전 `musicsheet_api.jobs` 부재로 수집 실패, 종료 코드 1 |
| 수명주기 TDD RED | `uv run --project services/api --python 3.13 pytest services/api/tests/test_database.py services/api/tests/test_app.py -q` | 구현 전 `musicsheet_api.database` 부재로 수집 실패, 종료 코드 1 |
| 수명주기 TDD RED 확인 | `uv run --project services/api --python 3.13 pytest services/api/tests/test_app.py -q` | 신규 수명주기 테스트 2개 실패, 기존 health 테스트 2개 통과 |
| 집중 테스트 GREEN | `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_repository.py services/api/tests/test_database.py services/api/tests/test_app.py -q` | 32 passed, StarletteDeprecationWarning 1건 |
| API 전체 테스트 | `uv run --project services/api --python 3.13 pytest services/api/tests -q` | 68 passed, StarletteDeprecationWarning 1건 |
| 변경 검증 | `git diff --check` | 통과 |

이 테스트는 제어 가능한 연결/풀 대역을 사용합니다. 실제 PostgreSQL 스키마와 데이터 왕복 검증은 계획된 Task 3의 disposable database 통합 테스트 대상입니다. 독립 코드 리뷰 점수와 지적 처리 결과는 reviewer 확인 후 기록할 예정입니다.
