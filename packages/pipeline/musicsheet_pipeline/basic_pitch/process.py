"""Bounded subprocess protocol with cancellation-safe tree cleanup."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

from ..providers import PermanentProviderError
from .windows_job import WindowsJob

_ENV = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL"}


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes


def _identity(pid):
    try:
        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return fields[0], int(fields[2]), int(fields[3]), int(fields[19])
    except FileNotFoundError:
        return None


class _LinuxGroup:
    def __init__(self, process):
        self.process, self.pid = process, process.pid
        identity = _identity(self.pid)
        if identity is None or identity[1:3] != (self.pid, self.pid):
            raise OSError
        self.start = identity[3]

    def check_leader(self):
        identity = _identity(self.pid)
        if identity is None or identity[0] in {"Z", "X"} or identity[3] != self.start:
            raise OSError

    def members_alive(self, *, include_gate=False):
        identity = _identity(self.pid)
        if identity is not None and identity[3] != self.start:
            raise OSError
        for path in Path("/proc").iterdir():
            if not path.name.isdigit() or (not include_gate and int(path.name) == self.pid):
                continue
            member = _identity(int(path.name))
            if member and member[1] == self.pid and member[0] not in {"Z", "X"}:
                if member[2] != self.pid:
                    raise OSError
                return True
        return False

    async def stop(self, completion):
        self.check_leader()
        os.killpg(self.pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        killed = False
        # Absence before Popen finishes is not completion: a late tool may spawn.
        while not completion.done() or self.members_alive():
            self.check_leader()
            if time.monotonic() >= deadline:
                os.killpg(self.pid, signal.SIGKILL)  # Last group signal; never signal again.
                killed = True
                break
            await asyncio.sleep(.02)
        else:
            self.check_leader()
            self.process.stdin.close()
        code = await asyncio.wait_for(self.process.wait(), 5)
        if code != (-signal.SIGKILL if killed else 0):
            raise OSError
        deadline = time.monotonic() + 5
        while self.members_alive(include_gate=True):
            if time.monotonic() >= deadline:
                raise OSError
            await asyncio.sleep(.02)


async def _cleanup(process, owner, readers, released, completion):
    try:
        if isinstance(owner, WindowsJob):
            owner.terminate()
            deadline = time.monotonic() + 5
            while owner.active_process_count():
                if time.monotonic() >= deadline:
                    raise OSError
                await asyncio.sleep(.02)
            await asyncio.wait_for(process.wait(), 5)
        elif owner is not None and released:
            await owner.stop(completion)
        else:
            # The gate was never released; no actual tool can exist.
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), 5)
    except Exception:
        raise PermanentProviderError() from None
    finally:
        process.stdin.close()
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        if isinstance(owner, WindowsJob):
            owner.close()


async def _drain(coroutine):
    task = asyncio.create_task(coroutine)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _execute(argv, cwd, cancellation, capture_stdout):
    environment = {key: value for key, value in os.environ.items() if key.upper() in _ENV}
    gate = Path(__file__).with_name("_process_gate.py")
    creation = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable, "-I", str(gate),
        "1" if capture_stdout else "0", *argv, cwd=cwd, env=environment,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=8192, start_new_session=os.name != "nt"))
    cancelled = False
    while not creation.done():
        try:
            await asyncio.shield(creation)
        except asyncio.CancelledError:
            cancelled = True
    process = creation.result()
    owner, readers, released, frame = None, [], False, None
    try:
        if cancelled or cancellation.is_set():
            raise asyncio.CancelledError
        if os.name == "nt":
            candidate = WindowsJob()
            try:
                candidate.assign(process.pid)
            except BaseException:
                candidate.close()
                raise
            owner = candidate
        else:
            owner = _LinuxGroup(process)
        ready = asyncio.create_task(process.stdout.readline())
        stop = asyncio.create_task(cancellation.wait())
        readers = [ready, stop]
        await asyncio.wait(readers, return_when=asyncio.FIRST_COMPLETED)
        if stop.done():
            raise asyncio.CancelledError
        if ready.result() != b"READY\n":
            raise ValueError
        frame = asyncio.create_task(process.stdout.readline())
        readers.append(frame)
        process.stdin.write(b"R")
        released = True
        await process.stdin.drain()
        await asyncio.wait([frame, stop], return_when=asyncio.FIRST_COMPLETED)
        if stop.done():
            raise asyncio.CancelledError
        raw = frame.result()
        if not raw.endswith(b"\n") or len(raw) > 8192:
            raise ValueError
        value = json.loads(raw)
        if (type(value.get("version")) is not int or value["version"] != 1
                or type(value.get("returncode")) is not int
                or type(value.get("overflow")) is not bool or value["overflow"]
                or type(value.get("launch_failed")) is not bool or value["launch_failed"]):
            raise ValueError
        stdout = base64.b64decode(value["stdout"], validate=True)
        if len(stdout) > 4096:
            raise ValueError
        result = ProcessResult(value["returncode"], stdout)
    finally:
        await _drain(_cleanup(process, owner, readers, released, frame))
    if cancellation.is_set():
        raise asyncio.CancelledError
    return result


async def run_owned_process(argv, *, cwd, cancellation, timeout=None, capture_stdout=False):
    """Return only after all owned children are stopped, including on cancellation."""
    try:
        if (not argv or isinstance(argv, (str, bytes)) or not all(isinstance(arg, str) and "\0" not in arg for arg in argv)
                or not isinstance(cancellation, asyncio.Event) or type(capture_stdout) is not bool):
            raise ValueError
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError
        if os.name != "nt" and not sys.platform.startswith("linux"):
            raise ValueError
        if cancellation.is_set():
            raise asyncio.CancelledError
        async with asyncio.timeout(timeout):
            return await _execute(tuple(argv), Path(cwd), cancellation, capture_stdout)
    except (asyncio.CancelledError, TimeoutError):
        raise
    except Exception:
        raise PermanentProviderError() from None
