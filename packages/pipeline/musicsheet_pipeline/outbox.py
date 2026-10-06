"""Caller-owned transaction helpers; never connect to a message broker."""
from uuid import uuid4
from .contracts import StageMessage


async def enqueue_stage(connection, message: StageMessage, *, delay_seconds: int = 0) -> None:
    if type(delay_seconds) is not int or delay_seconds not in (0, 5, 10):
        raise ValueError("Invalid dispatch delay")
    await connection.execute(
        "/* pipeline.enqueue */ INSERT INTO pipeline_outbox (id,job_id,stage,generation,available_at) "
        "VALUES ($1,$2,$3,$4,CURRENT_TIMESTAMP + $5 * INTERVAL '1 second') "
        "ON CONFLICT (job_id,stage,generation) DO NOTHING",
        str(uuid4()), message.job_id, message.stage.value, message.generation, delay_seconds,
    )


async def recover_pending(connection, *, limit: int = 100) -> int:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid dispatch limit")
    rows = await connection.fetch(
        "/* pipeline.recover */ SELECT j.id FROM jobs j "
        "WHERE j.status='PENDING' AND j.current_stage='DOWNLOAD' "
        "AND NOT EXISTS (SELECT 1 FROM pipeline_outbox o WHERE o.job_id=j.id) "
        "AND NOT EXISTS (SELECT 1 FROM stage_attempts a WHERE a.job_id=j.id) "
        "ORDER BY j.created_at,j.id LIMIT $1 FOR UPDATE OF j SKIP LOCKED", limit,
    )
    for row in rows:
        await enqueue_stage(connection, StageMessage(row["id"], "DOWNLOAD", 1))
    return len(rows)
