"""Internal durable bookkeeping for bounded workflow publication."""

UPGRADE_SQL = """
ALTER TABLE jobs
    ADD COLUMN start_job_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN workflow_dispatched_at TIMESTAMPTZ;
"""
