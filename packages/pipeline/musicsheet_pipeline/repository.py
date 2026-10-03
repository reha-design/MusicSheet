"""Job-scoped execution ownership and atomic PostgreSQL stage transitions."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from musicsheet_common import ArtifactRef, JobStatus, PipelineStage
from .contracts import STAGES, InfrastructureUnavailable, StageBusy, StageInput, StageMessage, InvalidArtifact
from .models import PipelineJob, PreparedStage, Transition, TERMINAL
from .outbox import enqueue_stage

_logger = logging.getLogger(__name__)
_ACTIVE_CONNECTIONS = set()
_ERRORS = {
    "PROVIDER_FAILED": "Stage processing failed",
    "PROVIDER_RETRYABLE": "Stage processing will be retried",
    "PROVIDER_NOT_CONFIGURED": "Stage provider is not configured",
    "PROVIDER_TIMEOUT": "Stage processing timed out",
    "ARTIFACT_INVALID": "Stage artifact is unavailable or invalid",
    "INPUT_CHANGED": "Stage input configuration changed",
    "WORKER_INTERRUPTED": "Stage execution was interrupted",
    "CANCELED": "Job was canceled",
}


def _ids(attempt):
    value = attempt["output_artifact_ids"]
    return json.loads(value) if isinstance(value, str) else value


class PipelineRepository:
    def __init__(self, connection):
        self.connection = connection

    def stage_session(self, message: StageMessage):
        return StageSession(self.connection, message)


class StageSession:
    """Caller owns the connection; this session owns only its advisory lock."""

    def __init__(self, connection, message):
        self.connection = connection
        self.message = message
        self.lock_key = int.from_bytes(UUID(message.job_id).bytes[:8], "big", signed=True)
        self.ownership_lost = False
        self._locked = False
        self._used = False
        self._acquire_task = None
        self._cleanup_cancelled = False
        self._mutex = asyncio.Lock()
        self._listener = lambda _: self._lose_ownership()

    def _lose_ownership(self):
        self.ownership_lost = True

    def _alive(self):
        if self.ownership_lost or self.connection.is_closed():
            self.ownership_lost = True
            raise InfrastructureUnavailable()

    @asynccontextmanager
    async def _operation(self, *, acquiring=False):
        async with self._mutex:
            self._alive()
            if not acquiring and not self._locked:
                raise InfrastructureUnavailable()
            try:
                yield
            except (InfrastructureUnavailable, InvalidArtifact):
                raise
            except Exception:
                self._lose_ownership()
                raise InfrastructureUnavailable() from None

    async def __aenter__(self):
        if self._used or self.connection in _ACTIVE_CONNECTIONS:
            raise StageBusy()
        self._used = True
        _ACTIVE_CONNECTIONS.add(self.connection)
        listening = False
        try:
            self.connection.add_termination_listener(self._listener)
            listening = True
            async with self._operation(acquiring=True):
                self._acquire_task = asyncio.create_task(self.connection.fetchval(
                    "/* pipeline.lock */ SELECT pg_try_advisory_lock($1)", self.lock_key))
                self._locked = await asyncio.shield(self._acquire_task)
            if not self._locked:
                raise StageBusy()
            return self
        except BaseException:
            try:
                await self._drain_cleanup()
            except InfrastructureUnavailable:
                pass
            finally:
                if listening:
                    self.connection.remove_termination_listener(self._listener)
                _ACTIVE_CONNECTIONS.discard(self.connection)
            if self._cleanup_cancelled:
                raise asyncio.CancelledError from None
            raise

    async def _release(self):
        """Resolve acquisition before releasing; close an uncertain session."""
        try:
            if self._acquire_task is not None:
                self._locked = bool(await self._acquire_task)
            if self._locked and not self.connection.is_closed():
                async with self._mutex:
                    await self.connection.fetchval("/* pipeline.unlock */ SELECT pg_advisory_unlock($1)", self.lock_key)
        except Exception:
            self._lose_ownership()
            if not self.connection.is_closed():
                self.connection.terminate()
            raise InfrastructureUnavailable() from None
        finally:
            self._locked = False

    async def _drain_cleanup(self):
        task = asyncio.create_task(self._release())
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                self._cleanup_cancelled = True
            except Exception:
                break
        task.result()

    async def __aexit__(self, typ, value, tb):
        failure = None
        try:
            await self._drain_cleanup()
        except InfrastructureUnavailable as error:
            failure = error
        finally:
            self.connection.remove_termination_listener(self._listener)
            _ACTIVE_CONNECTIONS.discard(self.connection)
        if self._cleanup_cancelled:
            raise asyncio.CancelledError
        if failure is not None and typ is None:
            raise failure from None

    async def _job(self):
        row = await self.connection.fetchrow(
            "/* pipeline.job */ SELECT * FROM jobs WHERE id=$1 FOR UPDATE", self.message.job_id)
        return PipelineJob.from_row(row) if row else None

    async def _attempts(self, stage=None):
        return await self.connection.fetch(
            "/* pipeline.attempts */ SELECT * FROM stage_attempts "
            "WHERE job_id=$1 AND stage=$2 ORDER BY attempt DESC",
            self.message.job_id, (stage or self.message.stage).value)

    async def _artifacts(self, ids):
        if not ids:
            return ()
        rows = await self.connection.fetch(
            "/* pipeline.artifacts */ SELECT * FROM artifacts WHERE job_id=$1 AND id=ANY($2::varchar[])",
            self.message.job_id, list(ids))
        refs = {row["id"]: ArtifactRef.model_validate(dict(row)) for row in rows}
        return tuple(refs[i] for i in ids if i in refs)

    async def _update(self, job, *, status, stage=None, progress=None, overall=None, active=None, code=None):
        row = await self.connection.fetchrow(
            "/* pipeline.job.update */ UPDATE jobs SET status=$2,current_stage=$3,stage_progress=$4,"
            "overall_progress=$5,active_attempt_id=$6,error_code=$7,error_message=$8,updated_at=CURRENT_TIMESTAMP,"
            "completed_at=CASE WHEN $2::varchar IN ('COMPLETED','FAILED','CANCELED') THEN CURRENT_TIMESTAMP ELSE NULL END "
            "WHERE id=$1 RETURNING *", job.id, status.value, (stage or job.current_stage).value,
            job.stage_progress if progress is None else progress,
            job.overall_progress if overall is None else overall, active, code, _ERRORS.get(code))
        return Transition(PipelineJob.from_row(row))

    async def _finish_attempt(self, id, *, status, code=None, outputs=()):
        await self.connection.execute(
            "/* pipeline.attempt.finish */ UPDATE stage_attempts SET status=$2,error_code=$3,error_detail=NULL,"
            "output_artifact_ids=$4::jsonb,completed_at=CURRENT_TIMESTAMP,"
            "duration_ms=LEAST(2147483647,GREATEST(0,EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-started_at))*1000))::int "
            "WHERE id=$1", id, status, code, json.dumps(list(outputs)))

    async def _cancel(self, job):
        if job.active_attempt_id:
            await self._finish_attempt(job.active_attempt_id, status="FAILED", code="CANCELED")
        return await self._update(job, status=JobStatus.CANCELED, code="CANCELED")

    async def _fail(self, job, attempt, code, retryable):
        if job.status == JobStatus.CANCEL_REQUESTED:
            return await self._cancel(job)
        await self._finish_attempt(attempt["id"], status="FAILED", code=code)
        if retryable and attempt["attempt"] < 3:
            await enqueue_stage(self.connection, StageMessage(job.id, self.message.stage, attempt["generation"]+1),
                                delay_seconds=5 if attempt["attempt"] == 1 else 10)
            return await self._update(job, status=JobStatus.RETRYING, code=code)
        return await self._update(job, status=JobStatus.FAILED, code=code)

    async def prepare(self, identity):
        async with self._operation(), self.connection.transaction():
            job = await self._job()
            if job is None or job.status in TERMINAL:
                return PreparedStage("SKIP")
            reservation = await self.connection.fetchrow(
                "/* pipeline.reservation */ SELECT (SELECT MAX(generation) FROM pipeline_outbox "
                "WHERE job_id=$1 AND stage=$2) AS current_generation,available_at<=CURRENT_TIMESTAMP AS ready "
                "FROM pipeline_outbox WHERE job_id=$1 AND stage=$2 AND generation=$3",
                job.id, self.message.stage.value, self.message.generation)
            if not reservation or reservation["current_generation"] != self.message.generation or not reservation["ready"]:
                return PreparedStage("SKIP")
            if job.status == JobStatus.CANCEL_REQUESTED:
                return PreparedStage("SKIP", transition=await self._cancel(job))
            index = STAGES.index(self.message.stage)
            current_index = STAGES.index(job.current_stage)
            if index < current_index:
                return PreparedStage("SKIP")
            previous = await self._attempts(STAGES[index-1]) if index else []
            if index > current_index and (index != current_index+1 or not previous or previous[0]["status"] != "COMPLETED"):
                _logger.warning("Unexpected pipeline stage message")
                return PreparedStage("SKIP")
            if index and (not previous or previous[0]["status"] != "COMPLETED" or not previous[0]["input_fingerprint"] or not _ids(previous[0])):
                return PreparedStage("SKIP", transition=await self._update(job, status=JobStatus.FAILED, code="INPUT_CHANGED"))
            attempts = await self._attempts()
            if attempts and attempts[0]["status"] == "RUNNING":
                return PreparedStage("SKIP", transition=await self._fail(job, attempts[0], "WORKER_INTERRUPTED", True))
            if attempts and attempts[0]["status"] == "FAILED" and attempts[0]["generation"] == self.message.generation:
                return PreparedStage("SKIP")
            if index:
                inputs = await self._artifacts(_ids(previous[0]))
                inputs_missing = len(inputs) != len(_ids(previous[0]))
            elif job.source_type == "UPLOAD":
                rows = await self.connection.fetch(
                    "/* pipeline.inputs */ SELECT * FROM artifacts WHERE job_id=$1 AND role=$2 ORDER BY id",
                    job.id, "SOURCE_ORIGINAL")
                inputs = tuple(ArtifactRef.model_validate(dict(row)) for row in rows)
                inputs_missing = False
            else:
                # DOWNLOAD creates a YouTube source; it is never its own input.
                inputs = ()
                inputs_missing = False
            identity_data = None if identity is None else (identity.name, identity.version, identity.configuration_json)
            fingerprint = hashlib.sha256(json.dumps(
                [job.source_type, job.source_url, job.target_instrument, identity_data,
                 sorted((a.role.value,a.id,a.sha256) for a in inputs)],
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            if attempts and attempts[0]["status"] == "COMPLETED":
                attempt = attempts[0]
                if attempt["input_fingerprint"] != fingerprint:
                    return PreparedStage("SKIP", transition=await self._update(job, status=JobStatus.FAILED, code="INPUT_CHANGED"))
                outputs = await self._artifacts(_ids(attempt))
                if not outputs or len(outputs) != len(_ids(attempt)):
                    return PreparedStage("SKIP", transition=await self._update(job, status=JobStatus.FAILED, code="ARTIFACT_INVALID"))
                return PreparedStage("DUPLICATE", completed_outputs=outputs)
            number = attempts[0]["attempt"]+1 if attempts else 1
            if number > 3:
                return PreparedStage("SKIP", transition=await self._update(job,status=JobStatus.FAILED,code="WORKER_INTERRUPTED"))
            id = str(uuid4())
            await self.connection.execute(
                "/* pipeline.attempt.insert */ INSERT INTO stage_attempts "
                "(id,job_id,stage,attempt,generation,provider,model_version,input_fingerprint,status) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'RUNNING')",
                id, job.id, self.message.stage.value, number, self.message.generation,
                identity.name if identity else None, identity.version if identity else None, fingerprint)
            t = await self._update(job, status=JobStatus.RUNNING, stage=self.message.stage, progress=0, active=id)
            if identity is None or inputs_missing:
                attempt = (await self._attempts())[0]
                code = "ARTIFACT_INVALID" if inputs_missing else "PROVIDER_NOT_CONFIGURED"
                return PreparedStage("SKIP",transition=await self._fail(t.job,attempt,code,False))
            context = StageInput(self.message,id,job.source_type,job.source_url,job.target_instrument,inputs)
            return PreparedStage("RUN", context=context, transition=t)

    def _owned(self, job, attempt_id):
        return job is not None and job.status not in TERMINAL and job.active_attempt_id==attempt_id and job.current_stage==self.message.stage

    async def complete(self, attempt_id, outputs):
        async with self._operation(), self.connection.transaction():
            job = await self._job()
            if not self._owned(job,attempt_id):
                return None
            if job.status==JobStatus.CANCEL_REQUESTED:
                return await self._cancel(job)
            if not outputs:
                raise InvalidArtifact()
            ids = []
            for original in outputs:
                try:
                    artifact = ArtifactRef.model_validate(original.model_dump(warnings=False))
                    if artifact.job_id != job.id or artifact.id in ids:
                        raise ValueError
                except Exception:
                    raise InvalidArtifact() from None
                values = artifact.model_dump()
                values["role"] = artifact.role.value
                columns = ("id","job_id","role","filename","uri","mime_type","size_bytes","sha256","producer","producer_version")
                same = " AND ".join(f"artifacts.{c} IS NOT DISTINCT FROM EXCLUDED.{c}" for c in columns[1:])
                result = await self.connection.fetchval(
                    "/* pipeline.artifact.insert */ INSERT INTO artifacts ("+",".join(columns)+") VALUES ("+
                    ",".join(f"${i}" for i in range(1,11))+
                    ") ON CONFLICT (id) DO UPDATE SET id=EXCLUDED.id WHERE "+same+" RETURNING id",
                    *(values[c] for c in columns))
                if result is None:
                    raise InvalidArtifact()
                ids.append(artifact.id)
            await self._finish_attempt(attempt_id,status="COMPLETED",outputs=ids)
            index = STAGES.index(self.message.stage)
            if index < len(STAGES)-1:
                await enqueue_stage(self.connection,StageMessage(job.id,STAGES[index+1],1))
            return await self._update(job,status=JobStatus.COMPLETED if index==5 else JobStatus.RUNNING,
                                      progress=100,overall=(index+1)*100//6)

    async def fail(self, attempt_id, *, code, retryable):
        if code not in _ERRORS or type(retryable) is not bool:
            raise ValueError("Invalid stage failure")
        async with self._operation(), self.connection.transaction():
            job = await self._job()
            if not self._owned(job,attempt_id):
                return None
            attempt = next(a for a in await self._attempts() if a["id"]==attempt_id)
            return await self._fail(job,attempt,code,retryable)

    async def cancel_if_requested(self):
        async with self._operation(), self.connection.transaction():
            job = await self._job()
            return await self._cancel(job) if job and job.status==JobStatus.CANCEL_REQUESTED else None

    async def check_ownership(self, attempt_id):
        async with self._operation(), self.connection.transaction():
            return self._owned(await self._job(),attempt_id)

    async def invalidate_completed(self, *, code):
        if code not in {"ARTIFACT_INVALID","INPUT_CHANGED"}:
            raise ValueError("Invalid stage failure")
        async with self._operation(), self.connection.transaction():
            job = await self._job()
            if job is None or job.status in TERMINAL or job.current_stage != self.message.stage or job.active_attempt_id:
                return None
            if job.status==JobStatus.CANCEL_REQUESTED:
                return await self._cancel(job)
            return await self._update(job,status=JobStatus.FAILED,code=code)
