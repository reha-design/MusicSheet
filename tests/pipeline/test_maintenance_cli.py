import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from datetime import datetime, timezone
import json

import pytest
from musicsheet_pipeline.config import PipelineSettings
from .support import JOB, Connection
from .test_maintenance import stalled


def cli():
    from musicsheet_pipeline import maintenance_cli
    return maintenance_cli


def flags():
    return ["fail-stalled", "--job-id", JOB, "--observed-status", "RUNNING",
        "--observed-stage", "DOWNLOAD", "--observed-updated-at", "2026-10-06T00:00:00+00:00",
        "--observed-attempt-id", "none"]


@pytest.mark.parametrize("argv", [["--help"], ["scan", "--help"], ["fail-stalled", "--help"]])
def test_help_needs_no_configuration_or_connections(argv, monkeypatch, capsys):
    module = cli()
    def fail(*args, **kwargs):
        pytest.fail("Help opened configuration or connection")
    monkeypatch.setattr(module.PipelineSettings, "from_env", fail)
    monkeypatch.setattr(module.asyncpg, "connect", fail)
    assert module.main(argv) == 0
    assert "musicsheet-maintenance" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["secret-sentinel"], ["scan", "--limit", "1001"],
    ["scan", "--stale-seconds", "0"], ["scan", "--limit", "secret-sentinel"],
    ["fail-stalled", "--job-id", JOB],
    flags()[:-1]+["secret-sentinel"], flags()[:2]+["secret-sentinel"]+flags()[3:],
    flags()[:4]+["secret-sentinel"]+flags()[5:],
    flags()[:6]+["secret-sentinel"]+flags()[7:],
    flags()[:8]+["2026-10-06T00:00:00"]+flags()[9:],
])
def test_invalid_cli_arguments_are_fixed_errors_before_connect(argv, monkeypatch, capsys):
    module = cli()
    monkeypatch.setattr(module.asyncpg, "connect", lambda *a, **k: pytest.fail("Invalid args connected"))
    assert module.main(argv) == 2
    output = capsys.readouterr()
    assert "secret-sentinel" not in output.out+output.err and "Traceback" not in output.err


@pytest.mark.parametrize("env", [{}, {"DATABASE_URL": "secret-sentinel"}])
def test_invalid_or_missing_settings_exit_two(env, monkeypatch, capsys):
    module = cli()
    original = PipelineSettings.from_env
    monkeypatch.setattr(module.PipelineSettings, "from_env", lambda: original(env))
    assert module.main(["scan"]) == 2
    assert "secret-sentinel" not in str(capsys.readouterr())


def test_database_only_scan_and_dependency_failures_have_fixed_diagnostics(monkeypatch, capsys):
    module = cli()
    original = PipelineSettings.from_env
    monkeypatch.setattr(module.PipelineSettings, "from_env", lambda: original({"DATABASE_URL": "postgresql://test:secret-sentinel@localhost/test"}))
    class C(Connection):
        async def close(self, **kwargs):
            self.closed = True
    c = C()
    stalled(c)
    async def connect(*args, **kwargs):
        assert kwargs == {"timeout": 2, "command_timeout": 5}
        return c
    monkeypatch.setattr(module.asyncpg, "connect", connect)
    assert module.main(["scan"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1 and c.closed
    async def fail(*args, **kwargs):
        raise OSError("secret-sentinel")
    monkeypatch.setattr(module.asyncpg, "connect", fail)
    assert module.main(["scan"]) == 1
    assert "secret-sentinel" not in str(capsys.readouterr())


@pytest.mark.parametrize("mode,expected", [("change", 0), ("noop", 3), ("failure", 1)])
def test_cli_output_exit_and_owned_resource_cleanup(mode, expected, monkeypatch, capsys):
    module = cli()
    original = PipelineSettings.from_env
    monkeypatch.setattr(module.PipelineSettings, "from_env", lambda: original({"DATABASE_URL": "postgresql://localhost/test"}))
    c = Connection()
    obs = stalled(c)
    args = flags()
    args[8] = obs.updated_at.isoformat()
    args[10] = obs.active_attempt_id
    if mode == "noop":
        c.db.jobs[JOB]["updated_at"] = datetime.now(timezone.utc)
    if mode == "failure":
        c.fail_query = True
    closed = []
    @asynccontextmanager
    async def resources(settings, **kwargs):
        try:
            yield SimpleNamespace(connection=c, event_store=None)
        finally:
            closed.append(True)
    original_run = module._run
    async def run(settings, args):
        return await original_run(settings, args, runtime_factory=resources)
    monkeypatch.setattr(module, "_run", run)
    assert module.main(args) == expected and closed == [True]
    output = capsys.readouterr()
    assert "secret" not in output.out+output.err
    if expected != 1:
        assert json.loads(output.out)["changed"] == (mode == "change")


def test_repeated_cancellation_drains_cleanup(monkeypatch):
    module = cli()
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        class C(Connection):
            async def close(self, **kwargs):
                started.set()
                await release.wait()
                self.closed = True
        c = C()
        async def connect(*args, **kwargs):
            return c
        monkeypatch.setattr(module.asyncpg, "connect", connect)
        async def own():
            async with module._resources(PipelineSettings.from_env({"DATABASE_URL": "postgresql://localhost/test"})):
                pass
        task = asyncio.create_task(own())
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert c.closed
    asyncio.run(check())


@pytest.mark.parametrize("with_events", [False, True])
def test_optional_redis_is_bounded_and_all_owned_resources_close(with_events, monkeypatch):
    module = cli()
    async def check():
        closed, opened = [], []
        class C(Connection):
            async def close(self, **kwargs):
                closed.append("database")
        class Redis:
            async def aclose(self):
                closed.append("redis")
        async def connect(*args, **kwargs):
            return C()
        def redis(*args, **kwargs):
            assert kwargs == {"socket_connect_timeout": 2, "socket_timeout": 2}
            opened.append("redis")
            return Redis()
        monkeypatch.setattr(module.asyncpg, "connect", connect)
        monkeypatch.setattr(module.Redis, "from_url", redis)
        settings = PipelineSettings.from_env({"DATABASE_URL": "postgresql://localhost/test", "REDIS_URL": "redis://localhost/2"})
        async with module._resources(settings, with_events=with_events) as resources:
            assert (resources.event_store is not None) == with_events
        assert closed == (["redis", "database"] if with_events else ["database"])
        assert opened == (["redis"] if with_events else [])
    asyncio.run(check())
