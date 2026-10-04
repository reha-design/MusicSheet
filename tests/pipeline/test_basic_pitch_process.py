import asyncio
import json
import os
from pathlib import Path
import sys
import time

import pytest

from musicsheet_pipeline.basic_pitch.process import run_owned_process
from musicsheet_pipeline.providers import PermanentProviderError
from musicsheet_pipeline.basic_pitch import process as process_module

FIXTURE = Path(__file__).with_name("process_fixture.py")


def command(mode, root, *extra):
    return [sys.executable, str(FIXTURE), mode, str(root), *extra]


def alive(pid):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_uint32()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    path = Path("/proc") / str(pid) / "stat"
    return path.exists() and path.read_text().rsplit(")", 1)[1].split()[0] != "Z"


async def ready(root):
    deadline = time.monotonic() + 8
    while not (root / "ready").exists():
        assert time.monotonic() < deadline, "child did not become ready"
        await asyncio.sleep(.02)


def assert_stopped(root):
    for name in ("parent.pid", "child.pid"):
        assert not alive(int((root / name).read_text()))


def test_process_argv_is_literal(tmp_path):
    async def run():
        result = await run_owned_process(command("echo", tmp_path, "한글 space", "$(touch nope);&"),
            cwd=tmp_path, cancellation=asyncio.Event(), capture_stdout=True, timeout=10)
        assert result.returncode == 0
        assert json.loads(result.stdout) == ["한글 space", "$(touch nope);&"]
        assert not (tmp_path / "nope").exists()
    asyncio.run(run())


def test_cancel_before_gate_release_never_launches_tool(tmp_path):
    async def run():
        event = asyncio.Event()
        event.set()
        with pytest.raises(asyncio.CancelledError):
            await run_owned_process(command("wait", tmp_path), cwd=tmp_path, cancellation=event)
        assert not (tmp_path / "ready").exists()
    asyncio.run(run())


def test_repeated_cancel_reaps_parent_and_grandchild(tmp_path):
    async def run():
        event = asyncio.Event()
        task = asyncio.create_task(run_owned_process(command("wait", tmp_path), cwd=tmp_path, cancellation=event))
        try:
            await ready(tmp_path)
            event.set()
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 9)
            assert_stopped(tmp_path)
        finally:
            event.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_timeout_kills_uncooperative_descendant(tmp_path, monkeypatch):
    async def run():
        scopes = []
        timeout = asyncio.timeout
        def capture_deadline(value):
            scope = timeout(value)
            scopes.append(scope)
            return scope
        monkeypatch.setattr(asyncio, "timeout", capture_deadline)
        task = asyncio.create_task(run_owned_process(command("wait", tmp_path),
            cwd=tmp_path, cancellation=asyncio.Event(), timeout=30))
        try:
            await ready(tmp_path)
            # Expire the real public runner deadline after actual descendants exist.
            scopes[0].reschedule(asyncio.get_running_loop().time() + .05)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 10)
            assert_stopped(tmp_path)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_normal_exit_with_grandchild_inheriting_stdout_completes_without_provider_timeout(tmp_path):
    async def run():
        started = time.monotonic()
        result = await run_owned_process(command("linger", tmp_path), cwd=tmp_path,
            cancellation=asyncio.Event(), capture_stdout=True, timeout=15)
        assert result.returncode == 0 and result.stdout.strip() == b"done"
        assert time.monotonic() - started < 10
        assert_stopped(tmp_path)
    asyncio.run(run())


def test_probe_overflow_is_bounded(tmp_path):
    async def run():
        with pytest.raises(PermanentProviderError):
            await run_owned_process(command("overflow", tmp_path), cwd=tmp_path,
                cancellation=asyncio.Event(), capture_stdout=True, timeout=10)
    asyncio.run(run())


def test_child_environment_excludes_database_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "secret-sentinel")
    async def run():
        result = await run_owned_process(command("env", tmp_path), cwd=tmp_path,
            cancellation=asyncio.Event(), capture_stdout=True, timeout=10)
        assert result.stdout.strip() == b"absent"
    asyncio.run(run())


def track_creation(monkeypatch, records, created=None, release=None):
    original = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        records.append(child)
        if created is not None:
            created.set()
            await release.wait()
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)


def test_cancel_during_spawn_drains_created_process(tmp_path, monkeypatch):
    async def run():
        records, created, release = [], asyncio.Event(), asyncio.Event()
        track_creation(monkeypatch, records, created, release)
        task = asyncio.create_task(run_owned_process(command("wait", tmp_path),
            cwd=tmp_path, cancellation=asyncio.Event()))
        try:
            await asyncio.wait_for(created.wait(), 5)
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 8)
            assert records[0].returncode is not None
            assert not alive(records[0].pid)
            assert not (tmp_path / "ready").exists()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object boundary")
def test_job_assignment_failure_is_closed(tmp_path, monkeypatch):
    records = []
    track_creation(monkeypatch, records)
    def fail(self, pid):
        raise OSError("secret-sentinel")
    monkeypatch.setattr(process_module.WindowsJob, "assign", fail)
    async def run():
        with pytest.raises(PermanentProviderError) as error:
            await run_owned_process(command("wait", tmp_path), cwd=tmp_path,
                cancellation=asyncio.Event())
        assert "secret-sentinel" not in str(error.value)
        assert records[0].returncode is not None
        assert not alive(records[0].pid)
        assert not (tmp_path / "ready").exists()
    asyncio.run(run())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process group boundary")
def test_gate_remains_alive_during_sigterm_grace_period(tmp_path, monkeypatch):
    records = []
    track_creation(monkeypatch, records)
    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(run_owned_process(command("wait", tmp_path),
            cwd=tmp_path, cancellation=stop))
        try:
            await ready(tmp_path)
            stop.set()
            await asyncio.sleep(.15)
            assert alive(records[0].pid)
            assert alive(int((tmp_path / "child.pid").read_text()))
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 9)
            assert_stopped(tmp_path)
        finally:
            stop.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux identity boundary")
def test_unexpected_gate_exit_never_signals_reused_group(tmp_path, monkeypatch):
    import signal
    records, signals, owned = [], [], {}
    track_creation(monkeypatch, records)
    real_killpg = os.killpg
    def signal_group(pid, sig):
        signals.append((pid, sig))
        real_killpg(pid, sig)
    monkeypatch.setattr(os, "killpg", signal_group)
    async def run():
        task = asyncio.create_task(run_owned_process(command("wait", tmp_path),
            cwd=tmp_path, cancellation=asyncio.Event()))
        try:
            await ready(tmp_path)
            for name in ("parent.pid", "child.pid"):
                pid = int((tmp_path / name).read_text())
                owned[pid] = process_module._identity(pid)[3]
            records[0].kill()
            with pytest.raises(PermanentProviderError):
                await asyncio.wait_for(task, 8)
            assert signals == []
            # A replacement identity also fails closed before any group signal.
            gate = process_module._LinuxGroup.__new__(process_module._LinuxGroup)
            gate.pid, gate.start = records[0].pid, -1
            with monkeypatch.context() as boundary:
                boundary.setattr(process_module, "_identity", lambda pid: ("S", pid, pid, 42))
                with pytest.raises(OSError):
                    gate.check_leader()
        finally:
            for pid, start in owned.items():
                identity = process_module._identity(pid)
                if identity and identity[3] == start and identity[0] != "Z":
                    os.kill(pid, signal.SIGKILL)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux launch/cancel race")
def test_cancel_after_release_before_tool_spawn_reaps_late_tool(tmp_path, monkeypatch):
    import signal
    gate_file = Path(process_module.__file__).with_name("_process_gate.py")
    delayed = gate_file.read_text().replace("    captured = bytearray()",
        f"    open({str(tmp_path / 'released')!r}, 'w').close()\n    time.sleep(.5)\n    captured = bytearray()")
    (tmp_path / "_process_gate.py").write_text(delayed)
    monkeypatch.setattr(process_module, "__file__", str(tmp_path / "process.py"))
    records = []
    track_creation(monkeypatch, records)
    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(run_owned_process(command("wait", tmp_path),
            cwd=tmp_path, cancellation=stop))
        try:
            deadline = time.monotonic() + 5
            while not (tmp_path / "released").exists():
                assert time.monotonic() < deadline
                await asyncio.sleep(.01)
            stop.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 12)
            assert records[0].returncode is not None
            assert_stopped(tmp_path)
        finally:
            # Fault injection may fail before product cleanup is fixed.
            for name in ("parent.pid", "child.pid"):
                marker = tmp_path / name
                if marker.exists():
                    pid = int(marker.read_text())
                    identity = process_module._identity(pid)
                    if identity and identity[1:3] == (records[0].pid, records[0].pid) and identity[0] != "Z":
                        os.kill(pid, signal.SIGKILL)
            if records and alive(records[0].pid):
                records[0].kill()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_cleanup_timeout_is_permanent():
    import traceback
    from types import SimpleNamespace
    async def fail(completion):
        raise TimeoutError("secret-sentinel")
    process = SimpleNamespace(stdin=SimpleNamespace(close=lambda: None))
    owner = SimpleNamespace(stop=fail)
    async def run():
        with pytest.raises(PermanentProviderError) as caught:
            await process_module._cleanup(process, owner, [], True, None)
        formatted = "".join(traceback.format_exception(caught.value))
        assert "secret-sentinel" not in formatted
    asyncio.run(run())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux EOF ownership fence")
def test_gate_death_after_sigterm_never_records_cleanup_success(tmp_path, monkeypatch):
    import signal
    signals = []
    original = os.killpg
    def fail_after_signal(pid, sig):
        signals.append(sig)
        original(pid, sig)
        os.kill(pid, signal.SIGKILL)
        time.sleep(.03)
    monkeypatch.setattr(os, "killpg", fail_after_signal)
    async def run():
        with pytest.raises(PermanentProviderError):
            await run_owned_process([sys.executable, "-c", "pass"], cwd=tmp_path,
                cancellation=asyncio.Event(), timeout=10)
        assert signals == [signal.SIGTERM]
    asyncio.run(run())
