"""Drain owned I/O before cancellation returns; retain partial-success refs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
import threading

from musicsheet_common import ArtifactRef, ArtifactRole
from ..contracts import InvalidArtifact, ProviderIdentity, StageContext
from ..providers import PermanentProviderError
from .process import _drain


def check_stop(stop: threading.Event) -> None:
    if stop.is_set():
        raise InterruptedError


async def run_owned_io[T](operation: Callable[[threading.Event], T], *, cancellation: asyncio.Event) -> T:
    if cancellation.is_set():
        raise asyncio.CancelledError
    stop = threading.Event()
    work = asyncio.create_task(asyncio.to_thread(operation, stop))
    watcher = asyncio.create_task(cancellation.wait())
    cancelled = False
    try:
        try:
            await asyncio.wait([work, watcher], return_when=asyncio.FIRST_COMPLETED)
            cancelled = cancellation.is_set()
        except asyncio.CancelledError:
            cancelled = True
        if cancelled:
            stop.set()
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                cancelled = True
                stop.set()
            except Exception:
                break  # Observe the operation's exception below after drain.
        if cancelled or cancellation.is_set():
            if not work.cancelled():
                work.exception()
            raise asyncio.CancelledError
        result = work.result()
    finally:
        async def close_watcher():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await _drain(close_watcher())
    if cancellation.is_set():
        raise asyncio.CancelledError
    return result


class _Reader:
    def __init__(self, stream, stop, limit):
        self.stream, self.stop, self.remaining = stream, stop, limit

    def read(self, size=-1):
        check_stop(self.stop)
        data = self.stream.read(min(65536 if size < 0 else min(size, 65536), self.remaining + 1))
        self.remaining -= len(data)
        if self.remaining < 0:
            raise InvalidArtifact()
        return data


async def rollback_outputs(storage, refs) -> None:
    def remove():
        failed = False
        for ref in refs:
            try:
                storage.delete(ref)
            except Exception:
                failed = True
        if failed:
            raise PermanentProviderError() from None
    await _drain(asyncio.to_thread(remove))


async def store_outputs(context: StageContext, files: tuple[Path, Path], *, identity: ProviderIdentity) -> tuple[ArtifactRef, ...]:
    saved: list[ArtifactRef] = []
    loop, owner_task = asyncio.get_running_loop(), asyncio.current_task()
    initial_cancels = owner_task.cancelling()

    def permit_put(stop):
        check_stop(stop)
        permission = Future()
        def decide():
            # Event/Task APIs stay on their loop; a stalled loop cannot grant a new put.
            if context.cancellation.is_set() or owner_task.cancelling() > initial_cancels:
                permission.set_exception(InterruptedError())
            else:
                permission.set_result(None)
        loop.call_soon_threadsafe(decide)
        permission.result()
        check_stop(stop)

    def store(stop):
        from .result import JSON_LIMIT, MIDI_LIMIT, validate_result_files
        if len(files) != 2 or tuple(files) != validate_result_files(files[0].parent, stop=stop):
            raise InvalidArtifact()
        for path, role, limit in zip(files, (ArtifactRole.RAW_TRANSCRIPTION, ArtifactRole.MIDI),
                (JSON_LIMIT, MIDI_LIMIT), strict=True):
            permit_put(stop)
            with path.open("rb") as stream:
                ref = context.storage.put(context.message.job_id,
                    f"attempt_{context.attempt_id}_{path.name}", role, _Reader(stream, stop, limit),
                    identity.name, identity.version)
                saved.append(ref)  # Record inside the thread before a cancelled await can lose it.
        check_stop(stop)
        return tuple(saved)
    try:
        return await run_owned_io(store, cancellation=context.cancellation)
    except BaseException as error:
        await rollback_outputs(context.storage, saved)
        if isinstance(error, (asyncio.CancelledError, InvalidArtifact)):
            raise
        raise PermanentProviderError() from None
