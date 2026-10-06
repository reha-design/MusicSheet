"""Execute one durable stage with cooperative cancellation and commit fencing."""
from __future__ import annotations

import asyncio
import math
import logging

from musicsheet_common import JobProgressEvent
from .artifacts import validate_artifacts
from .contracts import StageContext,InfrastructureUnavailable,InvalidArtifact
from .providers import RetryableProviderError
from .repository import PipelineRepository

_logger=logging.getLogger(__name__)


async def _publish(store,transition):
    if store is None or transition is None or not transition.changed:
        return
    job=transition.job
    event=JobProgressEvent(job_id=job.id,status=job.status,stage=job.current_stage,
        stage_progress=job.stage_progress,overall_progress=job.overall_progress,
        message=job.error_message or "Stage state updated")
    try:
        await store.publish(event)
    except Exception:
        # PostgreSQL is already committed. Event loss cannot replay computation.
        _logger.warning("Pipeline event publication failed")


async def _drain(*tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    joined=asyncio.gather(*tasks,return_exceptions=True)
    cancelled=False
    while not joined.done():
        try:
            await asyncio.shield(joined)
        except asyncio.CancelledError:
            cancelled=True
    joined.result()
    if cancelled:
        raise asyncio.CancelledError


async def run_stage(message,*,connection,storage,providers,event_store,
                    provider_timeout=1800,cancellation_interval=1):
    for setting in (provider_timeout,cancellation_interval):
        if isinstance(setting,bool) or not isinstance(setting,(int,float)) or not math.isfinite(setting) or setting<=0:
            raise ValueError("Invalid stage timing")
    provider=providers.get(message.stage)
    identity=provider.identity if provider else None
    async with PipelineRepository(connection).stage_session(message) as session:
        prepared=await session.prepare(identity)
        await _publish(event_store,prepared.transition)
        if prepared.action=="SKIP":
            return
        cancellation=asyncio.Event()
        attempt=prepared.context.attempt_id if prepared.context else None

        async def process():
            if prepared.action=="DUPLICATE":
                await validate_artifacts(prepared.completed_outputs,job_id=message.job_id,identity=identity,
                    storage=storage,attempt_id="",existing_inputs=prepared.completed_outputs,cancellation=cancellation)
                return ()
            context=prepared.context
            inputs=await validate_artifacts(context.inputs,job_id=message.job_id,identity=identity,
                storage=storage,attempt_id=attempt,existing_inputs=context.inputs,cancellation=cancellation,mode="input")
            # Providers may mutate Pydantic refs; preserve the verified DB snapshot.
            provider_inputs=tuple(ref.model_copy(deep=True) for ref in inputs)
            ctx=StageContext(message,attempt,context.source_type,context.source_url,context.target_instrument,provider_inputs,storage,cancellation)
            outputs=await asyncio.wait_for(provider.run(ctx),provider_timeout)
            return await validate_artifacts(outputs,job_id=message.job_id,identity=identity,storage=storage,
                attempt_id=attempt,existing_inputs=inputs,cancellation=cancellation)

        work=asyncio.create_task(process())
        async def monitor():
            while True:
                await asyncio.sleep(cancellation_interval)
                transition=await session.cancel_if_requested()
                if transition:
                    cancellation.set()
                    work.cancel()
                    return transition
                if not await session.check_ownership(attempt):
                    cancellation.set()
                    work.cancel()
                    return None

        guard=asyncio.create_task(monitor())
        try:
            await asyncio.wait((work,guard),return_when=asyncio.FIRST_COMPLETED)
            if guard.done():
                # Monitor errors fence results and must reach the runtime boundary.
                cancellation.set()
                work.cancel()
                transition=guard.result()
                await _drain(work)
                await _publish(event_store,transition)
                return
            await _drain(guard)
            transition=None
            try:
                outputs=work.result()
            except InvalidArtifact:
                transition=await session.invalidate_completed(code="ARTIFACT_INVALID") if attempt is None else await session.fail(attempt,code="ARTIFACT_INVALID",retryable=False)
            except RetryableProviderError:
                transition=await session.fail(attempt,code="PROVIDER_RETRYABLE",retryable=True)
            except TimeoutError:
                transition=await session.fail(attempt,code="PROVIDER_TIMEOUT",retryable=False)
            except Exception:
                transition=await session.fail(attempt,code="PROVIDER_FAILED",retryable=False)
            else:
                if attempt is not None:
                    try:
                        transition=await session.complete(attempt,outputs)
                    except InvalidArtifact:
                        transition=await session.fail(attempt,code="ARTIFACT_INVALID",retryable=False)
            await _publish(event_store,transition)
        finally:
            cancellation.set()
            await _drain(work,guard)
