"""Initial tables from the canonical database specification."""

UPGRADE_SQL = """
CREATE TABLE jobs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64),
    source_type VARCHAR(16) NOT NULL,
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
"""
