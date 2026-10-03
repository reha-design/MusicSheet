import asyncio
import copy
from datetime import datetime, timezone, timedelta

import pytest
from musicsheet_common import JobStatus, PipelineStage
from musicsheet_pipeline.contracts import StageMessage, ProviderIdentity, StageBusy, InfrastructureUnavailable
from musicsheet_pipeline.outbox import enqueue_stage, recover_pending
from musicsheet_pipeline.repository import PipelineRepository

from .support import Connection, JOB, artifact

IDENTITY = ProviderIdentity("test","1",{},frozenset(),frozenset())
MESSAGE = StageMessage(JOB, PipelineStage.DOWNLOAD, 1)


async def start(c, message=MESSAGE):
    await enqueue_stage(c, message)
    return PipelineRepository(c).stage_session(message)


def test_enqueue_uses_callers_transaction():
    async def check():
        c = Connection()
        await enqueue_stage(c, MESSAGE)
        await enqueue_stage(c, MESSAGE)
        assert c.transactions == 0 and len(c.db.outbox)==1
    asyncio.run(check())


def test_recover_pending_is_idempotent():
    async def check():
        c = Connection()
        async with c.transaction():
            assert await recover_pending(c) == 1
            assert await recover_pending(c) == 0
        assert len(c.db.outbox)==1
    asyncio.run(check())


def test_prepare_records_running_and_target_input():
    async def check():
        c = Connection()
        async with await start(c) as session:
            prepared = await session.prepare(IDENTITY)
            assert prepared.action == "RUN"
            assert prepared.context.target_instrument == "piano"
            assert prepared.context.inputs[0].id == artifact().id
            assert c.db.jobs[JOB]["status"]=="RUNNING"
            assert await session.check_ownership(prepared.context.attempt_id)
    asyncio.run(check())


def test_finish_rolls_back_artifacts_and_next_message_together():
    async def check():
        c = Connection()
        async with await start(c) as session:
            p = await session.prepare(IDENTITY)
            before = copy.deepcopy((c.db.jobs,c.db.attempts,c.db.artifacts,c.db.outbox))
            c.fail_outbox = True
            with pytest.raises(InfrastructureUnavailable):
                await session.complete(p.context.attempt_id, (artifact().model_copy(update={"id":"00000000-0000-4000-8000-000000000003"}),))
            assert (c.db.jobs,c.db.attempts,c.db.artifacts,c.db.outbox)==before
    asyncio.run(check())


def test_complete_records_output_and_next_stage_atomically():
    async def check():
        c = Connection()
        async with await start(c) as session:
            p = await session.prepare(IDENTITY)
            t = await session.complete(p.context.attempt_id,(artifact(),))
            assert t.job.status == JobStatus.RUNNING
            assert t.job.overall_progress == 16 and t.job.active_attempt_id is None
            assert (JOB,"PREPROCESS",1) in c.db.outbox
            assert c.db.attempts[p.context.attempt_id]["output_artifact_ids"]==[artifact().id]
            assert len(c.db.artifacts)==1
            duplicate = await session.prepare(IDENTITY)
            assert duplicate.action=="DUPLICATE" and duplicate.completed_outputs==(artifact(),)
    asyncio.run(check())


def test_cancel_wins_before_completion():
    async def check():
        c = Connection()
        async with await start(c) as session:
            p = await session.prepare(IDENTITY)
            c.db.jobs[JOB]["status"] = "CANCEL_REQUESTED"
            t = await session.complete(p.context.attempt_id,(artifact(),))
            assert t.job.status==JobStatus.CANCELED
            assert len(c.db.outbox)==1
            assert c.db.attempts[p.context.attempt_id]["error_code"]=="CANCELED"
    asyncio.run(check())


@pytest.mark.parametrize("status", ["COMPLETED","FAILED","CANCELED"])
def test_terminal_is_immutable(status):
    async def check():
        c = Connection()
        async with await start(c) as session:
            p = await session.prepare(IDENTITY)
            c.db.jobs[JOB]["status"] = status
            assert await session.complete(p.context.attempt_id,()) is None
            assert await session.fail(p.context.attempt_id,code="PROVIDER_FAILED",retryable=True) is None
            assert c.db.jobs[JOB]["status"]==status and len(c.db.outbox)==1
    asyncio.run(check())


def test_retry_and_interrupted_third_attempt_fails_without_next_generation():
    async def check():
        c = Connection()
        for generation in (1,2,3):
            message = StageMessage(JOB,"DOWNLOAD",generation)
            if generation > 1:
                c.db.outbox[(JOB,"DOWNLOAD",generation)]["available_at"] = datetime.now(timezone.utc)
            async with await start(c,message) as session:
                p = await session.prepare(IDENTITY)
                if generation<3:
                    t = await session.fail(p.context.attempt_id,code="PROVIDER_RETRYABLE",retryable=True)
                    assert t.job.status==JobStatus.RETRYING
        async with PipelineRepository(c).stage_session(StageMessage(JOB,"DOWNLOAD",3)) as session:
            p = await session.prepare(IDENTITY)
            assert p.action=="SKIP" and p.transition.job.status==JobStatus.FAILED
            assert len(c.db.attempts)==3 and len(c.db.outbox)==3
    asyncio.run(check())


def test_busy_does_not_create_attempt():
    async def check():
        c = Connection()
        async with await start(c):
            second = Connection(c.db)
            with pytest.raises(StageBusy):
                async with PipelineRepository(second).stage_session(MESSAGE):
                    pass
            assert not c.db.attempts
        assert not c.db.locks
    asyncio.run(check())


@pytest.mark.parametrize("case", ["unreserved","early","future","stale"])
def test_early_future_or_unreserved_message_does_not_run(case):
    async def check():
        c = Connection()
        message = MESSAGE
        if case != "unreserved":
            await enqueue_stage(c, message)
        if case=="early":
            c.db.outbox[(JOB,"DOWNLOAD",1)]["available_at"] += timedelta(seconds=10)
        if case=="future":
            message=StageMessage(JOB,"RENDER",1)
            await enqueue_stage(c,message)
        if case=="stale":
            await enqueue_stage(c,StageMessage(JOB,"DOWNLOAD",2))
        async with PipelineRepository(c).stage_session(message) as session:
            assert (await session.prepare(IDENTITY)).action=="SKIP"
            assert not c.db.attempts and c.db.jobs[JOB]["status"]=="PENDING"
    asyncio.run(check())


def test_connection_loss_permanently_fences_results():
    async def check():
        c = Connection()
        async with await start(c) as session:
            p = await session.prepare(IDENTITY)
            c.terminate()
            with pytest.raises(InfrastructureUnavailable):
                await session.complete(p.context.attempt_id,(artifact(),))
            assert session.ownership_lost and len(c.db.outbox)==1
    asyncio.run(check())


def test_session_cannot_write_without_acquiring_lock():
    async def check():
        c = Connection()
        await enqueue_stage(c,MESSAGE)
        session = PipelineRepository(c).stage_session(MESSAGE)
        with pytest.raises(InfrastructureUnavailable):
            await session.prepare(IDENTITY)
        assert not c.db.attempts
    asyncio.run(check())


def test_same_connection_cannot_reenter_job_session():
    async def check():
        c = Connection()
        async with await start(c):
            with pytest.raises(StageBusy):
                async with PipelineRepository(c).stage_session(MESSAGE):
                    pass
    asyncio.run(check())


def test_generation_with_failed_attempt_cannot_run_again():
    async def check():
        c=Connection()
        async with await start(c) as s:
            p=await s.prepare(IDENTITY)
            await s.fail(p.context.attempt_id,code="PROVIDER_FAILED",retryable=True)
            # Even if its next reservation were missing, this generation already ran.
            c.db.outbox.pop((JOB,"DOWNLOAD",2))
            result=await s.prepare(IDENTITY)
            assert result.action=="SKIP" and len(c.db.attempts)==1
    asyncio.run(check())


def test_six_stages_progress_and_final_completion():
    async def check():
        c=Connection()
        await enqueue_stage(c,MESSAGE)
        for stage,overall in zip(("DOWNLOAD","PREPROCESS","SEPARATE","TRANSCRIBE","POSTPROCESS","RENDER"),(16,33,50,66,83,100)):
            async with PipelineRepository(c).stage_session(StageMessage(JOB,stage,1)) as session:
                p=await session.prepare(IDENTITY)
                assert p.action=="RUN"
                t=await session.complete(p.context.attempt_id,(artifact(),))
                assert t.job.overall_progress==overall
                assert t.job.status==(JobStatus.COMPLETED if stage=="RENDER" else JobStatus.RUNNING)
        assert len(c.db.attempts)==6 and len(c.db.outbox)==6
    asyncio.run(check())


def test_cancel_before_start_has_no_attempt_or_next_stage():
    async def check():
        c=Connection()
        c.db.jobs[JOB]["status"]="CANCEL_REQUESTED"
        async with await start(c) as session:
            p=await session.prepare(IDENTITY)
            assert p.action=="SKIP" and p.transition.job.status==JobStatus.CANCELED
            assert not c.db.attempts and len(c.db.outbox)==1
    asyncio.run(check())


def test_late_result_cannot_change_new_attempt():
    async def check():
        c=Connection()
        async with await start(c) as session:
            p=await session.prepare(IDENTITY)
            c.db.jobs[JOB]["active_attempt_id"]="new-owner"
            assert await session.complete(p.context.attempt_id,(artifact(),)) is None
            assert await session.fail(p.context.attempt_id,code="PROVIDER_FAILED",retryable=True) is None
            assert c.db.jobs[JOB]["active_attempt_id"]=="new-owner"
    asyncio.run(check())


def test_provider_missing_fails_without_fake_success():
    async def check():
        c=Connection()
        async with await start(c) as session:
            p=await session.prepare(None)
            assert p.action=="SKIP" and p.transition.job.status==JobStatus.FAILED
            assert p.transition.job.error_code=="PROVIDER_NOT_CONFIGURED"
            assert len(c.db.outbox)==1
    asyncio.run(check())


def test_changed_fingerprint_is_not_reused():
    async def check():
        c=Connection()
        async with await start(c) as session:
            p=await session.prepare(IDENTITY)
            await session.complete(p.context.attempt_id,(artifact(),))
            changed=ProviderIdentity("test","2",{},frozenset(),frozenset())
            duplicate=await session.prepare(changed)
            assert duplicate.transition.job.error_code=="INPUT_CHANGED"
            assert len(c.db.attempts)==1
    asyncio.run(check())


def test_missing_completed_metadata_fails_without_rerun():
    async def check():
        c=Connection()
        async with await start(c) as session:
            p=await session.prepare(IDENTITY)
            await session.complete(p.context.attempt_id,(artifact(),))
            c.db.artifacts.clear()
            duplicate=await session.prepare(IDENTITY)
            assert duplicate.transition.job.status==JobStatus.FAILED
            assert len(c.db.attempts)==1
    asyncio.run(check())


def test_database_exceptions_are_sanitized():
    import traceback
    async def check():
        c=Connection()
        c.fail_query=True
        with pytest.raises(InfrastructureUnavailable) as failure:
            async with PipelineRepository(c).stage_session(MESSAGE):
                pass
        assert "secret-dsn" not in "".join(traceback.format_exception(failure.value))
        assert not c.listeners
    asyncio.run(check())


def test_transaction_error_releases_its_advisory_lock():
    async def check():
        c=Connection()
        async with await start(c) as session:
            p=await session.prepare(IDENTITY)
            c.fail_outbox=True
            with pytest.raises(InfrastructureUnavailable):
                await session.complete(p.context.attempt_id,(artifact(),))
        assert not c.db.locks and not c.listeners
    asyncio.run(check())


def test_youtube_download_duplicate_keeps_empty_input_fingerprint():
    async def check():
        c=Connection()
        c.db.jobs[JOB].update(source_type="YOUTUBE",source_url="https://www.youtube.com/watch?v=abcdefghijk")
        c.db.artifacts.clear()
        async with await start(c) as s:
            p=await s.prepare(IDENTITY)
            assert p.context.inputs==()
            await s.complete(p.context.attempt_id,(artifact(),))
            duplicate=await s.prepare(IDENTITY)
            assert duplicate.action=="DUPLICATE"
            assert c.db.jobs[JOB]["status"]=="RUNNING" and len(c.db.attempts)==1
    asyncio.run(check())


def test_youtube_interrupted_retry_ignores_partially_registered_source():
    async def check():
        c=Connection()
        c.db.jobs[JOB].update(source_type="YOUTUBE",source_url="https://www.youtube.com/watch?v=abcdefghijk")
        c.db.artifacts.clear()
        async with await start(c) as s:
            first=await s.prepare(IDENTITY)
        # A interrupted worker cannot turn a registered source into DOWNLOAD input.
        c.db.artifacts[artifact().id]=artifact().model_dump()
        async with PipelineRepository(c).stage_session(MESSAGE) as s:
            interrupted=await s.prepare(IDENTITY)
            assert interrupted.transition.job.status==JobStatus.RETRYING
        c.db.outbox[(JOB,"DOWNLOAD",2)]["available_at"]=datetime.now(timezone.utc)
        async with PipelineRepository(c).stage_session(StageMessage(JOB,"DOWNLOAD",2)) as s:
            retry=await s.prepare(IDENTITY)
            assert retry.context.inputs==()
            assert c.db.attempts[first.context.attempt_id]["input_fingerprint"]==c.db.attempts[retry.context.attempt_id]["input_fingerprint"]
    asyncio.run(check())


def test_unlock_failure_terminates_uncertain_connection_and_sanitizes_error():
    import traceback
    async def check():
        class BrokenUnlock(Connection):
            async def fetchval(self,query,*args):
                if "pipeline.unlock */" in query:
                    raise RuntimeError("secret-dsn")
                return await super().fetchval(query,*args)
        c=BrokenUnlock()
        with pytest.raises(InfrastructureUnavailable) as failure:
            async with await start(c):
                pass
        assert c.is_closed() and not c.db.locks and not c.listeners
        assert "secret-dsn" not in "".join(traceback.format_exception(failure.value))
    asyncio.run(check())


def test_busy_acquisition_cleanup_preserves_caller_cancellation():
    from musicsheet_pipeline.repository import StageSession
    async def check():
        ready,release=asyncio.Event(),asyncio.Event()
        class SlowCleanup(StageSession):
            async def _release(self):
                ready.set()
                await release.wait()
                await super()._release()
        c=Connection()
        second=Connection(c.db)
        async with await start(c):
            task=asyncio.create_task(SlowCleanup(second,MESSAGE).__aenter__())
            try:
                await asyncio.wait_for(ready.wait(),1)
                task.cancel()
                await asyncio.sleep(0)
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not second.listeners
            finally:
                release.set()
                await asyncio.gather(task,return_exceptions=True)
        assert not c.db.locks
    asyncio.run(check())


@pytest.mark.parametrize("phase", ["acquire","unlock"])
@pytest.mark.parametrize("cancels", [1,2])
def test_cancellation_drains_lock_acquisition_and_release(phase,cancels):
    async def check():
        ready,release=asyncio.Event(),asyncio.Event()
        class SlowConnection(Connection):
            async def fetchval(self,query,*args):
                if phase=="acquire" and "pipeline.lock */" in query:
                    result=await super().fetchval(query,*args)
                    ready.set()
                    await release.wait()
                    return result
                if phase=="unlock" and "pipeline.unlock */" in query:
                    ready.set()
                    await release.wait()
                return await super().fetchval(query,*args)
        c=SlowConnection()
        await enqueue_stage(c,MESSAGE)
        async def work():
            async with PipelineRepository(c).stage_session(MESSAGE):
                pass
        task=asyncio.create_task(work())
        try:
            await asyncio.wait_for(ready.wait(),1)
            for _ in range(cancels):
                task.cancel()
                await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not c.db.locks and not c.listeners
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())
