"""Explicit operator actions reuse worker ownership; PostgreSQL is authoritative."""
from .contracts import InfrastructureUnavailable, StageBusy, StageMessage
from .models import JobObservation, RecoveryResult, StalledJob, validate_stale_seconds
from .repository import PipelineRepository, require_idle_connection
from .runner import _publish


async def scan_stalled(connection, *, stale_seconds=7200, limit=100) -> tuple[StalledJob, ...]:
    validate_stale_seconds(stale_seconds)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Invalid scan limit")
    try:
        rows = await connection.fetch(
            "/* maintenance.scan */ SELECT j.id,j.status,j.current_stage,j.updated_at,j.active_attempt_id,"
            "a.stage AS latest_stage,a.attempt AS latest_attempt,a.generation AS latest_generation,"
            "a.status AS latest_status,a.error_code AS latest_error_code FROM jobs j LEFT JOIN LATERAL "
            "(SELECT stage,attempt,generation,status,error_code FROM stage_attempts WHERE job_id=j.id "
            "ORDER BY started_at DESC NULLS LAST,id DESC LIMIT 1) a ON TRUE "
            "WHERE j.status IN ('PENDING','RUNNING','RETRYING','CANCEL_REQUESTED') "
            "AND j.updated_at <= CURRENT_TIMESTAMP - $1::double precision * INTERVAL '1 second' "
            "ORDER BY j.updated_at,j.id LIMIT $2", stale_seconds, limit)
        return tuple(StalledJob.from_row(row) for row in rows)
    except Exception:
        raise InfrastructureUnavailable() from None


async def fail_stalled(connection, observation: JobObservation, *, stale_seconds=7200, event_store=None) -> RecoveryResult:
    validate_stale_seconds(stale_seconds)
    if not isinstance(observation, JobObservation):
        raise ValueError("Invalid job observation")
    require_idle_connection(connection)
    try:
        # This generation is only a lock carrier; no prepare/reservation is performed.
        message = StageMessage(observation.job_id, observation.current_stage, 1)
        async with PipelineRepository(connection).stage_session(message) as session:
            result = await session.fail_stalled(observation, stale_seconds=stale_seconds)
            await _publish(event_store, result.transition)
            return result
    except StageBusy:
        return RecoveryResult(False, "LOCK_HELD")
