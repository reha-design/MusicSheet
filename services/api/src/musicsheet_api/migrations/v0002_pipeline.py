"""Add durable dispatch and stage ownership without rewriting historical rows."""
UPGRADE_SQL = """
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM stage_attempts WHERE attempt <= 0)
       OR EXISTS (SELECT 1 FROM stage_attempts GROUP BY job_id,stage,attempt HAVING count(*) > 1)
    THEN RAISE EXCEPTION 'Pipeline history is invalid'; END IF;
END $$;

ALTER TABLE jobs ADD COLUMN active_attempt_id VARCHAR(36);
ALTER TABLE stage_attempts ADD COLUMN generation INT;
UPDATE stage_attempts SET generation=attempt;
ALTER TABLE stage_attempts ALTER COLUMN generation SET DEFAULT 1;
ALTER TABLE stage_attempts ALTER COLUMN generation SET NOT NULL;
ALTER TABLE stage_attempts ADD CONSTRAINT stage_attempts_generation_positive CHECK (generation > 0);
ALTER TABLE stage_attempts ADD CONSTRAINT stage_attempts_attempt_positive CHECK (attempt > 0);
ALTER TABLE stage_attempts ADD CONSTRAINT stage_attempts_unique_attempt UNIQUE(job_id,stage,attempt);
ALTER TABLE stage_attempts ADD COLUMN input_fingerprint VARCHAR(64);
ALTER TABLE stage_attempts ADD COLUMN output_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE stage_attempts ADD CONSTRAINT stage_attempts_output_array CHECK (jsonb_typeof(output_artifact_ids)='array');

CREATE TABLE pipeline_outbox (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage VARCHAR(20) NOT NULL CHECK (stage IN ('DOWNLOAD','PREPROCESS','SEPARATE','TRANSCRIBE','POSTPROCESS','RENDER')),
    generation INT NOT NULL CHECK (generation > 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id,stage,generation)
);
CREATE INDEX idx_pipeline_outbox_pending ON pipeline_outbox(available_at,id) WHERE published_at IS NULL;
"""
