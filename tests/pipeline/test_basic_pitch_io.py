import asyncio
import threading
import time
import traceback

import pytest

from musicsheet_pipeline.basic_pitch.io import run_owned_io, store_outputs
from musicsheet_pipeline.providers import PermanentProviderError
from musicsheet_pipeline.contracts import InvalidArtifact
from .basic_pitch_support import IDENTITY, context, result_files


async def entered(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 5), 6)


def test_blocked_materialize_drains_before_temp_cleanup():
    async def run():
        start, release, finished = threading.Event(), threading.Event(), threading.Event()
        stop = asyncio.Event()
        def operation(cancel):
            start.set()
            assert release.wait(5)
            finished.set()
            return "finished"
        task = asyncio.create_task(run_owned_io(operation, cancellation=stop))
        try:
            await entered(start)
            stop.set()
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
            assert not task.done() and not finished.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_cancel_during_put_keeps_returned_ref_for_rollback(tmp_path, monkeypatch):
    async def run():
        ctx = context(tmp_path)
        files = result_files(tmp_path / "result")
        start, release = threading.Event(), threading.Event()
        saved, calls = [], []
        original = ctx.storage.put
        def blocked(*args):
            calls.append(args[1])
            ref = original(*args)
            saved.append(ref)
            start.set()
            assert release.wait(5)
            return ref
        monkeypatch.setattr(ctx.storage, "put", blocked)
        task = asyncio.create_task(store_outputs(ctx, files, identity=IDENTITY))
        try:
            await entered(start)
            ctx.cancellation.set()
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert len(calls) == 1 and len(saved) == 1
            assert not ctx.storage.exists(saved[0])
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_second_put_failure_rolls_back_first_and_sanitizes_errors(tmp_path, monkeypatch, cleanup_fails):
    ctx = context(tmp_path)
    files = result_files(tmp_path / "result")
    refs = []
    original = ctx.storage.put
    def fail_second(*args):
        if refs:
            raise OSError("secret-sentinel")
        ref = original(*args)
        refs.append(ref)
        return ref
    monkeypatch.setattr(ctx.storage, "put", fail_second)
    if cleanup_fails:
        def fail_delete(ref):
            raise OSError("secret-sentinel")
        monkeypatch.setattr(ctx.storage, "delete", fail_delete)
    with pytest.raises(PermanentProviderError) as caught:
        asyncio.run(store_outputs(ctx, files, identity=IDENTITY))
    assert "secret-sentinel" not in "".join(traceback.format_exception(caught.value))
    assert ctx.storage.exists(refs[0]) is cleanup_fails


def test_output_names_roles_and_producer(tmp_path):
    ctx = context(tmp_path)
    files = result_files(tmp_path / "result")
    refs = asyncio.run(store_outputs(ctx, files, identity=IDENTITY))
    assert [ref.role.value for ref in refs] == ["RAW_TRANSCRIPTION", "MIDI"]
    assert [ref.filename for ref in refs] == [f"attempt_{ctx.attempt_id}_raw_transcription.json",
        f"attempt_{ctx.attempt_id}_transcription.mid"]
    assert all(ref.producer == IDENTITY.name and ref.producer_version == IDENTITY.version for ref in refs)


def test_both_results_are_validated_before_any_put(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    raw, mid = result_files(tmp_path / "result")
    mid.write_bytes(b"invalid-midi")
    calls = []
    def unexpected(*args):
        calls.append(args)
        raise AssertionError("no partial write before validation")
    monkeypatch.setattr(ctx.storage, "put", unexpected)
    with pytest.raises(InvalidArtifact):
        asyncio.run(store_outputs(ctx, (raw, mid), identity=IDENTITY))
    assert calls == []


@pytest.mark.parametrize("cancel_kind", ["event", "task"])
def test_cancel_before_second_put_is_fenced_without_loop_resuming(tmp_path, monkeypatch, cancel_kind):
    async def run():
        ctx = context(tmp_path)
        files = result_files(tmp_path / "result")
        start, release = threading.Event(), threading.Event()
        calls, saved = [], []
        original = ctx.storage.put
        def block_first(*args):
            calls.append((args[1], ctx.cancellation.is_set()))
            ref = original(*args)
            saved.append(ref)
            if len(calls) == 1:
                start.set()
                assert release.wait(5)
            return ref
        monkeypatch.setattr(ctx.storage, "put", block_first)
        task = asyncio.create_task(store_outputs(ctx, files, identity=IDENTITY))
        try:
            await entered(start)
            if cancel_kind == "event":
                ctx.cancellation.set()
            else:
                task.cancel()
            release.set()
            time.sleep(.1)  # Thread can proceed while the loop cannot relay cancellation.
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert len(calls) == 1 and not calls[0][1]
            assert all(not ctx.storage.exists(ref) for ref in saved)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
