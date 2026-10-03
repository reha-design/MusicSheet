# Backend Spec: Database & PostgreSQL Schema

> **Canonical Owner:** `docs/backend/database.md`  
> **관련 문서:** [docs/domain/job-state.md](../domain/job-state.md), [docs/domain/artifacts.md](../domain/artifacts.md)

---

## 1. DDL Schema

```sql
-- 작업 테이블
CREATE TABLE jobs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64),
    source_type VARCHAR(16) NOT NULL, -- 'YOUTUBE', 'UPLOAD'
    source_url TEXT,
    target_instrument VARCHAR(32) DEFAULT 'piano',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    current_stage VARCHAR(20) NOT NULL DEFAULT 'DOWNLOAD',
    stage_progress INT DEFAULT 0,
    overall_progress INT DEFAULT 0,
    error_code VARCHAR(64),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_jobs_status ON jobs(status);

-- 단계별 실행 이력 테이블
CREATE TABLE stage_attempts (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) REFERENCES jobs(id) ON DELETE CASCADE,
    stage VARCHAR(20) NOT NULL,
    attempt INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL,
    provider VARCHAR(64),
    model_version VARCHAR(32),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INT,
    error_code VARCHAR(64),
    error_detail TEXT
);

CREATE INDEX idx_stage_attempts_job_id ON stage_attempts(job_id);

-- 아티팩트 메타데이터 테이블
CREATE TABLE artifacts (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) REFERENCES jobs(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    uri TEXT NOT NULL,
    mime_type VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    producer VARCHAR(64),
    producer_version VARCHAR(32),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_artifacts_job_id ON artifacts(job_id);
```

## 2. 구현 및 운영 상태

W03 Task1은 [승인 설계](../superpowers/specs/2026-10-03-celery-orchestration-design.md#4-데이터-계약과-마이그레이션)의 outbox·attempt generation/출력 기록·실행 소유권 컬럼을 migration v2로 추가했습니다. 기존 v1 기록을 유지하고 명시적 migration 명령으로 적용하며, 시작 시 자동 적용하지 않습니다. 실제 DB 적용 성공 경로는 URL 미설정으로 아직 미검증입니다.

`services/api`의 명시적 `musicsheet-migrate` 명령이 버전 1과 2 DDL을 적용합니다. `schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)`가 적용 버전을 기록합니다. 각 버전의 DDL과 ledger 기록은 같은 트랜잭션에서 처리하며, PostgreSQL advisory lock으로 동시 실행을 직렬화합니다. API 시작 시 마이그레이션은 실행하지 않습니다.

API 프로젝트 디렉터리에서 `DATABASE_URL`을 설정한 후 `uv run --locked --python 3.13 musicsheet-migrate`를 실행합니다. 성공 시 새로 적용한 버전과 현재 버전을 표시하고, 실패 시 URL·호스트·인증정보·원시 드라이버 예외 없이 일반적인 오류만 표시합니다. 데이터베이스가 없거나 연결이 실패해도 API 기동과 `/health/live`는 유지되고 선택적 `app.state.db_pool`은 `None`입니다. 열린 풀은 종료 시 닫힙니다.

현재 `JobRepository`는 `jobs`의 생성·조회·진행률 갱신·취소 요청을 제공합니다. 취소는 `PENDING`·`RUNNING`·`RETRYING` 행만 조건부로 바꾸며, 기존 `CANCEL_REQUESTED` 또는 terminal 상태는 덮어쓰지 않습니다. `ArtifactRepository`는 job 생성과 같은 트랜잭션 연결을 통한 아티팩트 추가와 job 범위 목록·조회 기능을 제공합니다. 두 저장소는 공용 enum을 사용하고 SQL 값을 바인딩합니다. HTTP 계약은 [FastAPI Gateway](api.md)에 정의되어 있습니다. `stage_attempts` 저장소 연산과 worker dispatch는 이 범위에 포함되지 않습니다.

실DB 계약 검증은 PostgreSQL 16의 별도 `musicsheet_test` 데이터베이스에서만 수행합니다. 각 스키마 초기화 전에 테스트 fixture가 서버에 접속하여 `current_database() = 'musicsheet_test'`와 데이터베이스 comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1`을 확인합니다. 두 조건이 일치할 때에만 해당 DB의 `public` 스키마를 초기화합니다. 생성·마커 설정·실행 명령은 [API README](../../services/api/README.md#opt-in-live-integration-tests)에 있습니다. `MUSICSHEET_TEST_DATABASE_URL`이 없으면 통합 테스트를 건너뜁니다.
