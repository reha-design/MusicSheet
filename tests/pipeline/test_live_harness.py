import asyncio
import signal
import subprocess

import pytest
from .integration.support import Secret,namespace_keys,stop_owned_process,OwnedProcess,wait_until,HarnessUnavailable,parse_sse,REPO


def test_harness_redacts_urls_and_only_selects_owned_keys():
    assert (REPO/"pyproject.toml").is_file() and (REPO/"services/api").is_dir()
    assert "secret-sentinel" not in repr(Secret("redis://secret-sentinel"))
    prefix="ms_live_aaaaaaaa:"
    assert namespace_keys([prefix+"queue","other","job:owned:events","job:foreign:events"],prefix,{"owned"})==[prefix+"queue","job:owned:events"]


def test_process_cleanup_refuses_reused_leader_and_stops_owned_process():
    class Process:
        pid=123
        def wait(self,timeout): return 0
    identities={123:("S",123,123,42)}
    process=OwnedProcess(Process(),identity=identities.get)
    signals=[]
    identities[123]=("S",123,123,43)
    with pytest.raises(HarnessUnavailable):
        stop_owned_process(process,group_alive=lambda:process.group_alive(pids=[123]),killpg=lambda *args:signals.append(args))
    assert not signals
    states=iter([True,False,False])
    stop_owned_process(process,group_alive=lambda:next(states),killpg=lambda *args:signals.append(args))
    assert signals==[(123,signal.SIGTERM)]


def test_wait_has_bounded_deadline_and_sse_parser_retains_id_and_status():
    async def check():
        calls=[]
        async def ready():
            calls.append(1)
            return len(calls)==2
        assert await wait_until(ready,timeout=.1)
        with pytest.raises(HarnessUnavailable):
            await wait_until(lambda:asyncio.sleep(0,result=False),timeout=.01)
    asyncio.run(check())
    assert parse_sse(['id: 1-0','data: {"status":"COMPLETED"}',''])==[("1-0",{"status":"COMPLETED"})]


def test_scoped_publisher_connection_keeps_broker_key_prefix():
    from .integration.support import scoped_publisher
    from musicsheet_pipeline.config import PipelineSettings
    settings=PipelineSettings.from_env({"DATABASE_URL":"postgresql://localhost/test","CELERY_BROKER_URL":"redis://localhost/0"})
    publisher=scoped_publisher(settings,"ms_live_aaaaaaaa_","ms_live_aaaaaaaa:")
    try:
        assert publisher.connection.transport_options["global_keyprefix"]=="ms_live_aaaaaaaa:"
        assert publisher.connection.transport_options["visibility_timeout"]==5
    finally:
        publisher.close()


def test_live_transport_restores_expired_delivery_on_next_scan_without_changing_production(monkeypatch):
    """Catch the initial pre-expiry scan suppressing recovery for 100 seconds."""
    import json
    import socket
    from contextlib import nullcontext
    from types import SimpleNamespace
    from kombu.transport import redis as transport

    def no_network(*args, **kwargs):
        raise AssertionError("Transport module import opened a socket")

    with monkeypatch.context() as imports:
        imports.setattr(socket, "socket", no_network)
        from .integration.redis_transport import VerificationRedisTransport

    clock = [1000]
    monkeypatch.setattr(transport, "time", lambda: clock[0])
    monkeypatch.setattr(transport, "Mutex", lambda *a, **k: nullcontext())

    class RedisBoundary:
        def __init__(self):
            self.scores = {"delivery": 1000}
            self.messages = {"delivery": json.dumps([{"body": "original"}, "exchange", "queue"])}

        def zrevrangebyscore(self, key, maximum, minimum, **kwargs):
            return [(tag, score) for tag, score in self.scores.items() if minimum <= score <= maximum]

        def transaction(self, callback, key):
            callback(self)

        def hget(self, key, tag):
            return self.messages.get(tag)

        def multi(self):
            return None

        def zrem(self, key, tag):
            self.scores.pop(tag, None)
            return self

        def hdel(self, key, tag):
            self.messages.pop(tag, None)
            return self

    def exercise(qos_type):
        clock[0] = 1000
        client = RedisBoundary()
        restored = []
        channel = SimpleNamespace(
            do_restore=False,  # No delivered messages are owned by this boundary double at shutdown.
            visibility_timeout=5, unacked_key="unacked", unacked_index_key="index",
            unacked_mutex_key="mutex", unacked_mutex_expire=300,
            conn_or_acquire=lambda supplied=None: nullcontext(client),
            _do_restore_message=lambda message, exchange, key, pipe, leftmost:
                restored.append((message, exchange, key, leftmost)),
        )
        qos = qos_type(channel)
        qos.restore_visible()
        assert restored == []  # The delivery has not yet expired.
        clock[0] = 1010
        qos.restore_visible()
        return restored

    assert exercise(transport.QoS) == []  # Production retains Kombu's scan cadence.
    assert exercise(VerificationRedisTransport.Channel.QoS) == [
        ({"body": "original"}, "exchange", "queue", False)
    ]


def test_harness_cleanup_is_drained_on_repeated_cancel_and_hides_primary_secret(tmp_path,monkeypatch):
    import traceback
    from .integration import support
    async def check():
        closing,release=asyncio.Event(),asyncio.Event()
        closed=[]
        class Connection:
            async def fetchrow(self,*args): return {"name":"musicsheet_test","marker":"MUSICSHEET_DISPOSABLE_TEST_DB_V1"}
            async def fetchval(self,*args): return 2
            async def execute(self,*args): return None
            async def close(self,**kwargs):
                closing.set()
                await release.wait()
                closed.append("database")
            def terminate(self): closed.append("terminate")
        class Client:
            async def ping(self): return True
            async def client_list(self): return []
            async def scan_iter(self,**kwargs):
                if False: yield "unused"
            async def delete(self,*args): return 0
            async def aclose(self): closed.append("redis")
        async def connect(*args,**kwargs): return Connection()
        def fail_proxy(*args): raise RuntimeError("secret-sentinel")
        monkeypatch.setattr(support.asyncpg,"connect",connect)
        monkeypatch.setattr(support.Redis,"from_url",lambda *a,**k:Client())
        monkeypatch.setattr(support,"Proxy",fail_proxy)
        task=asyncio.create_task(support._scenario(tmp_path,"normal",support.Secret("postgresql://secret-sentinel"),support.Secret("redis://secret-sentinel")))
        try:
            await asyncio.wait_for(closing.wait(),1)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError) as failure:
                await task
            assert closed==["redis","database"]
            assert "secret-sentinel" not in "".join(traceback.format_exception(failure.value))
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())


def test_process_cleanup_reserves_bounded_time_for_kill_fallback():
    waits,signals=[],[]
    class Process:
        pid=123
        def poll(self): return None
        def wait(self,timeout):
            waits.append(timeout)
            if len(waits)==1:
                raise subprocess.TimeoutExpired("owned",timeout)
            return 0
    states=iter([True,True,False])
    stop_owned_process(Process(),group_alive=lambda:next(states),killpg=lambda *args:signals.append(args))
    assert waits==[3,2] and len(signals)==2


def test_process_cleanup_stops_descendants_after_parent_exit():
    class Process:
        pid=123
        def poll(self): return 0
        def wait(self,timeout): return 0
    identities={123:("Z",123,123,42),124:("S",123,123,44)}
    process=OwnedProcess(Process(),identity=identities.get)
    identities.pop(123)  # Parent reaped; the original session still owns child124.
    signals=[]
    def kill(group,value):
        signals.append((group,value))
        if value==9: identities.clear()
    stop_owned_process(process,group_alive=lambda:process.group_alive(pids=[124]),killpg=kill)
    assert signals==[(123,signal.SIGTERM),(123,9)]


def test_configured_invalid_live_url_fails_without_secret_in_subprocess(tmp_path):
    import os
    import sys
    code='import asyncio,pytest; from pathlib import Path; from pipeline.integration import support; support._configured=lambda:(support.Secret("invalid-database-secret-sentinel"),support.Secret("redis://secret-sentinel"));\ntry: asyncio.run(support.live_harness(Path("'+str(tmp_path).replace('\\','/')+'"),"normal"))\nexcept pytest.fail.Exception as error: print(str(error)); raise SystemExit(1)'
    result=subprocess.run([sys.executable,"-c",code],cwd=REPO,env=dict(os.environ,PYTHONPATH=str(REPO/"tests")),capture_output=True,text=True,timeout=10)
    assert result.returncode==1 and "Live pipeline verification failed" in result.stdout
    assert "secret-sentinel" not in result.stdout+result.stderr and "Traceback" not in result.stderr
