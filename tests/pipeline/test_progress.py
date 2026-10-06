"""Progress must describe only the still-owned execution, never expose completion early."""
import asyncio
import copy
from dataclasses import replace

import pytest
from musicsheet_common import JobStatus
from musicsheet_pipeline.contracts import InfrastructureUnavailable, StageMessage
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.repository import PipelineRepository
from musicsheet_pipeline.runner import run_stage

from .runner_support import Events, IDENTITY, Provider, environment
from .support import JOB, OTHER, Connection

MESSAGE = StageMessage(JOB, "DOWNLOAD", 1)


async def opened(connection):
    await enqueue_stage(connection, MESSAGE)
    return PipelineRepository(connection).stage_session(MESSAGE)


def test_runner_persists_increasing_progress_before_emitting_and_reserves_completion(tmp_path):
    async def check():
        c, storage, _ = environment(tmp_path)
        events = Events(c)
        results = []
        async def action(ctx):
            assert callable(ctx.report_progress)
            for value in (25, 25, 10, 75):
                results.append(await ctx.report_progress(value))
            assert c.db.jobs[JOB]["stage_progress"] == 75
            assert c.db.jobs[JOB]["overall_progress"] == 12
            assert all(a["status"] == "RUNNING" for a in c.db.attempts.values())
            return ctx.inputs
        await enqueue_stage(c, MESSAGE)
        await run_stage(MESSAGE, connection=c, storage=storage,
                        providers={MESSAGE.stage: Provider(action=action)}, event_store=events)
        assert results == [True, False, False, True]
        assert [e.stage_progress for e in events.events] == [0, 25, 75, 100]
        assert all(events.committed)
        assert c.db.jobs[JOB]["overall_progress"] == 16
    asyncio.run(check())


@pytest.mark.parametrize("value", [True, False, -1, 100, 101, 1.5, "30", None])
def test_invalid_progress_never_mutates_or_loses_a_live_session(value):
    async def check():
        c = Connection()
        async with await opened(c) as session:
            prepared = await session.prepare(IDENTITY)
            before = copy.deepcopy(c.db.jobs)
            with pytest.raises(ValueError):
                await session.report_progress(prepared.context.attempt_id, value)
            assert c.db.jobs == before
            assert await session.report_progress(prepared.context.attempt_id, 30) is not None
    asyncio.run(check())


@pytest.mark.parametrize("change", ["attempt", "generation", "reservation", "stage", "retry", "cancel", "terminal"])
def test_stale_or_inactive_progress_cannot_change_database(change):
    async def check():
        c = Connection()
        async with await opened(c) as session:
            prepared = await session.prepare(IDENTITY)
            attempt = prepared.context.attempt_id
            row = c.db.jobs[JOB]
            if change == "attempt":
                row["active_attempt_id"] = OTHER
            elif change == "generation":
                c.db.attempts[attempt]["generation"] = 2
            elif change == "reservation":
                await enqueue_stage(c, StageMessage(JOB, "DOWNLOAD", 2))
            elif change == "stage":
                row["current_stage"] = "PREPROCESS"
            else:
                row["status"] = {"retry": "RETRYING", "cancel": "CANCEL_REQUESTED", "terminal": "FAILED"}[change]
            before = copy.deepcopy((c.db.jobs, c.db.attempts, c.db.outbox))
            assert await session.report_progress(attempt, 50) is None
            assert (c.db.jobs, c.db.attempts, c.db.outbox) == before
    asyncio.run(check())


def test_retry_progress_preserves_overall_progress():
    async def check():
        c = Connection()
        c.db.jobs[JOB]["overall_progress"] = 14
        async with await opened(c) as session:
            prepared = await session.prepare(IDENTITY)
            result = await session.report_progress(prepared.context.attempt_id, 20)
            assert result.job.stage_progress == 20 and result.job.overall_progress == 14
    asyncio.run(check())


def test_finished_callback_is_a_noop_even_when_next_stage_is_waiting(tmp_path):
    async def check():
        c, storage, _ = environment(tmp_path)
        saved = []
        async def action(ctx):
            saved.append(ctx.report_progress)
            return ctx.inputs
        await enqueue_stage(c, MESSAGE)
        await run_stage(MESSAGE, connection=c, storage=storage,
                        providers={MESSAGE.stage: Provider(action=action)}, event_store=Events(c))
        before = copy.deepcopy((c.db.jobs, c.db.attempts, c.db.outbox))
        assert await saved[0](80) is False
        assert (c.db.jobs, c.db.attempts, c.db.outbox) == before
    asyncio.run(check())


def test_concurrent_callbacks_keep_database_and_event_order_together(tmp_path):
    async def check():
        c, storage, _ = environment(tmp_path)
        observed = []
        class SlowEvents(Events):
            async def publish(self, event):
                await asyncio.sleep(.01)
                observed.append((event.stage_progress, c.db.jobs[JOB]["stage_progress"]))
                return await super().publish(event)
        async def action(ctx):
            assert await asyncio.gather(ctx.report_progress(25), ctx.report_progress(70)) == [True, True]
            return ctx.inputs
        await enqueue_stage(c, MESSAGE)
        await run_stage(MESSAGE, connection=c, storage=storage,
                        providers={MESSAGE.stage: Provider(action=action)}, event_store=SlowEvents(c))
        assert observed == [(0, 0), (25, 25), (70, 70), (100, 100)]
    asyncio.run(check())


def test_progress_commit_failure_rolls_back_and_uses_infrastructure_boundary():
    async def check():
        c = Connection()
        async with await opened(c) as session:
            prepared = await session.prepare(IDENTITY)
            before = copy.deepcopy(c.db.jobs)
            c.fail_commit = True
            with pytest.raises(InfrastructureUnavailable, match="Pipeline infrastructure is unavailable"):
                await session.report_progress(prepared.context.attempt_id, 50)
            assert c.db.jobs == before
    asyncio.run(check())


@pytest.mark.parametrize("mode", ["direct", "wrapped", "swallowed"])
def test_runner_preserves_progress_database_failure_when_provider_handles_it(tmp_path, mode):
    async def check():
        c, storage, _ = environment(tmp_path)
        async def action(ctx):
            c.fail_commit = True
            try:
                await ctx.report_progress(50)
            except InfrastructureUnavailable:
                if mode == "direct":
                    raise
                if mode == "wrapped":
                    raise RuntimeError("secret-provider") from None
            return ctx.inputs
        await enqueue_stage(c, MESSAGE)
        with pytest.raises(InfrastructureUnavailable):
            await run_stage(MESSAGE, connection=c, storage=storage,
                            providers={MESSAGE.stage: Provider(action=action)}, event_store=None)
        assert c.db.jobs[JOB]["status"] == "RUNNING" and c.db.jobs[JOB]["stage_progress"] == 0
        assert all(a["status"] == "RUNNING" for a in c.db.attempts.values())
        assert not c.db.locks and not c.listeners
    asyncio.run(check())


def test_redis_failure_does_not_replay_or_undo_progress(tmp_path):
    async def check():
        c, storage, _ = environment(tmp_path)
        async def action(ctx):
            assert await ctx.report_progress(60) is True
            assert c.db.jobs[JOB]["stage_progress"] == 60
            return ctx.inputs
        provider = Provider(action=action)
        await enqueue_stage(c, MESSAGE)
        await run_stage(MESSAGE, connection=c, storage=storage, providers={MESSAGE.stage: provider},
                        event_store=Events(c, error=OSError("secret-redis")))
        assert len(provider.calls) == 1
        assert next(iter(c.db.attempts.values()))["status"] == "COMPLETED"
    asyncio.run(check())


def test_basic_pitch_reports_processing_milestones_before_database_completion(tmp_path, monkeypatch):
    from .test_basic_pitch_provider import provider, input_context
    instance, _ = provider(tmp_path, monkeypatch)
    ctx = input_context(tmp_path)
    observations = []
    async def report(value):
        observations.append((value, len(list((ctx.storage.base_dir / ctx.message.job_id).iterdir()))))
        return True
    ctx = replace(ctx, report_progress=report)
    refs = asyncio.run(instance.run(ctx))
    assert [x[0] for x in observations] == [20, 70, 85, 95]
    assert observations[-1][1] == 3 and len(refs) == 2
    assert all(value < 100 for value, _ in observations)


def test_basic_pitch_does_not_reclassify_progress_database_failure(tmp_path, monkeypatch):
    from .test_basic_pitch_provider import provider, input_context
    instance, counter = provider(tmp_path, monkeypatch)
    async def report(value):
        raise InfrastructureUnavailable()
    ctx = replace(input_context(tmp_path), report_progress=report)
    with pytest.raises(InfrastructureUnavailable):
        asyncio.run(instance.run(ctx))
    assert not counter.exists()
    assert len(list((ctx.storage.base_dir / ctx.message.job_id).iterdir())) == 1
