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

Workflow bookkeeping is introduced by migration v2; it is not part of immutable migration v1:

```sql
ALTER TABLE jobs
    ADD COLUMN start_job_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN workflow_dispatched_at TIMESTAMP WITH TIME ZONE;
```

## 2. 구현 및 운영 상태

`services/api`의 명시적 `musicsheet-migrate` 명령이 migration v1과 v2를 순서대로 적용합니다. `schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)`가 적용 버전을 기록합니다. 각 버전의 DDL과 ledger 기록은 같은 트랜잭션에서 처리하며, PostgreSQL advisory lock으로 동시 실행을 직렬화합니다. API 시작 시 마이그레이션은 실행하지 않습니다. Worker와 maintenance CLI를 시작하기 전에 v2가 적용되어 있어야 합니다. v2는 `jobs.start_job_attempts`와 `jobs.workflow_dispatched_at`만 추가하며, start-task worker-loss 복구용 내부 bookkeeping입니다.

API 프로젝트 디렉터리에서 `DATABASE_URL`을 설정한 후 `uv run --locked --python 3.13 musicsheet-migrate`를 실행합니다. 성공 시 새로 적용한 버전과 현재 버전을 표시하고, 실패 시 URL·호스트·인증정보·원시 드라이버 예외 없이 일반적인 오류만 표시합니다. 데이터베이스가 없거나 연결이 실패해도 API 기동과 `/health/live`는 유지되고 선택적 `app.state.db_pool`은 `None`입니다. 열린 풀은 종료 시 닫힙니다. v1에는 workflow bookkeeping column이 없으므로 worker claim query가 실패하고 handler 또는 chain 실행 전에 중단됩니다. Worker와 maintenance CLI를 시작하기 전에 v2를 적용합니다.

`JobRepository`는 `jobs`의 생성·조회·취소와 orchestration compare-and-set을 제공합니다. `StageAttemptRepository`는 job row lock 아래 attempt claim을 만들고, attempt 종료와 guarded job 상태 전이를 같은 PostgreSQL transaction에서 처리합니다. `ArtifactRepository`는 job 생성과 같은 트랜잭션 연결을 통한 아티팩트 추가와 job 범위 목록·조회 기능을 제공합니다. 두 저장소는 공용 enum을 사용하고 SQL 값을 바인딩합니다. HTTP 계약은 [FastAPI Gateway](api.md)에 정의되어 있습니다. W03 worker claim과 operator recovery는 PostgreSQL이 상태 기준이며 Celery result backend는 상태 권한이 없습니다.

`musicsheet-orchestration-maintenance scan`은 `updated_at`이 `2 × CELERY_VISIBILITY_TIMEOUT`보다 오래된 nonterminal job을 안전한 summary로 보여줍니다. Guarded recovery는 관찰한 timestamp/status를 비교하고 시작 task 및 현재 stage advisory session locks를 nonblocking으로 얻은 뒤, job row transaction에서 staleness와 eligibility를 재확인합니다. Open attempt 종료와 `FAILED/WORKER_PRECLAIM_STALLED` 또는 선행한 취소의 `CANCELED` 전이는 하나의 transaction으로 저장합니다. Terminal event는 commit 후 Redis DB `/2`에 best-effort 발행합니다.

실DB 계약 검증은 PostgreSQL 16의 별도 `musicsheet_test` 데이터베이스에서만 수행합니다. 각 스키마 초기화 전에 테스트 fixture가 서버에 접속하여 `current_database() = 'musicsheet_test'`와 데이터베이스 comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1`을 확인합니다. 두 조건이 일치할 때에만 해당 DB의 `public` 스키마를 초기화합니다. 생성·마커 설정·실행 명령은 [API README](../../services/api/README.md#opt-in-live-integration-tests)에 있습니다. `MUSICSHEET_TEST_DATABASE_URL`이 없으면 통합 테스트를 건너뜁니다.
