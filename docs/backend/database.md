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

`services/api`의 명시적 `musicsheet-migrate` 명령이 버전 1 DDL을 적용합니다. `schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)`가 적용 버전을 기록합니다. 각 버전의 DDL과 ledger 기록은 같은 트랜잭션에서 처리하며, PostgreSQL advisory lock으로 동시 실행을 직렬화합니다. API 시작 시 마이그레이션은 실행하지 않습니다.

API 프로젝트 디렉터리에서 `DATABASE_URL`을 설정한 후 `uv run --locked --python 3.13 musicsheet-migrate`를 실행합니다. 성공 시 새로 적용한 버전과 현재 버전을 표시하고, 실패 시 URL·호스트·인증정보·원시 드라이버 예외 없이 일반적인 오류만 표시합니다. 데이터베이스가 없거나 연결이 실패해도 API 기동과 `/health/live`는 유지되고 선택적 `app.state.db_pool`은 `None`입니다. 열린 풀은 종료 시 닫힙니다.

현재 `JobRepository`는 `jobs`의 생성·조회·진행률 갱신만 제공합니다. 공용 `JobStatus`·`PipelineStage` enum을 사용하고 SQL 값은 바인딩합니다. 이 작업에는 job REST endpoint, `stage_attempts`/`artifacts` 저장소 연산, worker dispatch가 포함되지 않습니다.

실DB 계약 검증은 PostgreSQL 16의 별도 `musicsheet_test` 데이터베이스에서만 수행합니다. 각 스키마 초기화 전에 테스트 fixture가 서버에 접속하여 `current_database() = 'musicsheet_test'`와 데이터베이스 comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1`을 확인합니다. 두 조건이 일치할 때에만 해당 DB의 `public` 스키마를 초기화합니다. 생성·마커 설정·실행 명령은 [API README](../../services/api/README.md#opt-in-live-integration-tests)에 있습니다. `MUSICSHEET_TEST_DATABASE_URL`이 없으면 통합 테스트를 건너뜁니다.
