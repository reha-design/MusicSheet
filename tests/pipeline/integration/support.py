"""Opt-in process harness. Owns only its jobs, Redis namespace and process groups."""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import select
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from redis.asyncio import Redis
from musicsheet_pipeline.config import PipelineSettings
from musicsheet_pipeline.contracts import StageMessage
from musicsheet_pipeline.dispatcher import CeleryPublisher,dispatch_once
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.tasks import _owned_cleanup

REPO=Path(__file__).resolve().parents[3]


class Secret(str):
    def __repr__(self): return "<redacted live URL>"


class HarnessUnavailable(Exception):
    def __init__(self): super().__init__("Live pipeline verification failed")


def namespace_keys(keys,prefix,jobs):
    if not prefix.startswith("ms_live_") or len(prefix)<16:
        raise HarnessUnavailable()
    streams={f"job:{job}:events" for job in jobs}
    return [key for key in keys if key.startswith(prefix) or key in streams]


def _process_identity(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        return (fields[0],int(fields[2]),int(fields[3]),int(fields[19]))
    except FileNotFoundError:
        return None


class OwnedProcess:
    """Capture the session leader's start time before any poll can reap it."""
    def __init__(self,process,*,identity=_process_identity):
        self.process=process
        self.pid=process.pid
        self.identity=identity
        leader=identity(self.pid)
        if leader is None or leader[1:3]!=(self.pid,self.pid):
            raise HarnessUnavailable()
        self.start=leader[3]
    def __getattr__(self,name):
        return getattr(self.process,name)
    def group_alive(self,*,pids=None):
        leader=self.identity(self.pid)
        if leader is not None and leader[3]!=self.start:
            # A reused numeric PID/session must never receive our signals.
            raise HarnessUnavailable()
        alive=False
        pids=pids if pids is not None else [int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()]
        for pid in pids:
            member=self.identity(pid)
            if member is not None and member[1]==self.pid:
                if member[2]!=self.pid:
                    raise HarnessUnavailable()
                alive=alive or member[0] not in {'Z','X'}
        return alive


def stop_owned_process(process,*,group_alive=None,killpg=None,kill_signal=9):
    group_alive=group_alive or process.group_alive
    killpg=killpg or os.killpg
    def send(value):
        try:
            killpg(process.pid,value)
        except ProcessLookupError:
            pass
    if group_alive():
        send(signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    # Parent termination does not imply prefork/uv descendants terminated.
    if group_alive():
        send(kill_signal)
    process.wait(timeout=2)
    deadline=time.monotonic()+2
    while group_alive():
        if time.monotonic()>=deadline:
            raise HarnessUnavailable()
        time.sleep(.02)


async def wait_until(predicate,*,timeout=30):
    if not 0<timeout<=30:
        raise HarnessUnavailable()
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if await predicate():
            return True
        await asyncio.sleep(.05)
    raise HarnessUnavailable()


def parse_sse(lines):
    result=[]
    event_id=None
    data=[]
    for line in lines:
        if line.startswith("id:"):
            event_id=line[3:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            result.append((event_id,json.loads("\n".join(data))))
            event_id,data=None,[]
    return result


def _read_sse(port,job,stop):
    deadline=time.monotonic()+30
    cursor=None
    result=[]
    while time.monotonic()<deadline and not stop.is_set():
        connection=http.client.HTTPConnection("127.0.0.1",port,timeout=2)
        try:
            headers={"Accept":"text/event-stream"}
            if cursor:
                headers["Last-Event-ID"]=cursor
            connection.request("GET",f"/api/v1/jobs/{job}/events",headers=headers)
            response=connection.getresponse()
            if response.status!=200:
                raise HarnessUnavailable()
            lines=[]
            while time.monotonic()<deadline and not stop.is_set():
                raw=response.readline()
                if not raw:
                    break
                line=raw.decode("utf-8").rstrip("\r\n")
                lines.append(line)
                if not line:
                    for event_id,event in parse_sse(lines):
                        cursor=event_id
                        result.append((event_id,event))
                        if event["status"] in {"COMPLETED","FAILED","CANCELED"}:
                            return result
                    lines=[]
        except (TimeoutError,OSError):
            continue
        finally:
            connection.close()
    raise HarnessUnavailable()


class Proxy:
    """Test-owned TCP forwarding; cut never stops the shared Redis server."""
    def __init__(self,url):
        parsed=urlsplit(url)
        if parsed.scheme!="redis":
            raise HarnessUnavailable()
        self.target=(parsed.hostname,parsed.port or 6379)
        self.blocked=threading.Event()
        self.sockets=set()
        self.lock=threading.Lock()
        proxy=self
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                upstream=None
                try:
                    if proxy.blocked.is_set():
                        return
                    upstream=socket.create_connection(proxy.target,timeout=2)
                    pair=(self.request,upstream)
                    with proxy.lock:
                        proxy.sockets.update(pair)
                    while not proxy.blocked.is_set():
                        readable,_,_=select.select(pair,[],[],.1)
                        for source in readable:
                            data=source.recv(65536)
                            if not data:
                                return
                            (upstream if source is self.request else self.request).sendall(data)
                except OSError:
                    pass
                finally:
                    with proxy.lock:
                        proxy.sockets.discard(self.request)
                        if upstream:
                            proxy.sockets.discard(upstream)
                    if upstream:
                        upstream.close()
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads=False
            block_on_close=True
            def handle_error(self,request,address):
                pass
        self.server=Server(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={"poll_interval":.05})
        self.thread.start()
        auth=parsed.netloc.rsplit("@",1)[0]+"@" if "@" in parsed.netloc else ""
        self.url=Secret(urlunsplit(parsed._replace(netloc=auth+f"127.0.0.1:{self.server.server_address[1]}")))
    def cut(self):
        self.blocked.set()
        with self.lock:
            for connection in list(self.sockets):
                try: connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                connection.close()
    def restore(self):
        self.blocked.clear()
    def close(self):
        self.cut()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise HarnessUnavailable()


class ScopedConnection:
    def __init__(self,connection,jobs):
        self.connection,self.jobs=connection,jobs
        self.fail_commit=False
    def transaction(self):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def transaction():
            async with self.connection.transaction():
                yield
                if self.fail_commit:
                    raise HarnessUnavailable()
        return transaction()
    async def fetchrow(self,query,*args):
        if "pipeline.dispatch.next" in query:
            query=query.replace("ORDER BY o.available_at", "AND j.id=ANY($1::varchar[]) ORDER BY o.available_at")
            args=(list(self.jobs),)
        return await self.connection.fetchrow(query,*args)
    async def execute(self,*args):
        return await self.connection.execute(*args)


def scoped_publisher(settings,queue_prefix,key_prefix):
    publisher=CeleryPublisher(settings,queue_prefix=queue_prefix)
    publisher.app.conf.broker_transport_options={**publisher.app.conf.broker_transport_options,"global_keyprefix":key_prefix,"visibility_timeout":5}
    publisher.app.conf.visibility_timeout=5
    # connection_for_write captured the original transport options at construction.
    publisher.connection.release()
    publisher.connection=publisher.app.connection_for_write()
    return publisher


async def _guard(connection):
    row=await connection.fetchrow("SELECT current_database() AS name,shobj_description(oid,'pg_database') AS marker FROM pg_database WHERE datname=current_database()")
    if row["name"]!="musicsheet_test" or row["marker"]!="MUSICSHEET_DISPOSABLE_TEST_DB_V1":
        raise HarnessUnavailable()
    if await connection.fetchval("SELECT max(version) FROM schema_migrations")!=2:
        raise HarnessUnavailable()


def _configured():
    if sys.platform!="linux":
        pytest.skip("Real prefork worker checks require Linux/WSL2")
    db,redis=os.getenv("MUSICSHEET_TEST_DATABASE_URL"),os.getenv("MUSICSHEET_TEST_REDIS_URL")
    if not db or not redis or os.getenv("MUSICSHEET_TEST_CELERY")!="1":
        pytest.skip("Live database/Redis URLs and MUSICSHEET_TEST_CELERY=1 are required")
    if os.getenv("PYTEST_XDIST_WORKER"):
        raise HarnessUnavailable()
    return Secret(db),Secret(redis)


async def live_harness(tmp_path,scenario):
    failed=False
    try:
        urls=_configured()
        # Reserve cleanup time within the planned 120s test budget.
        await asyncio.wait_for(_scenario(tmp_path,scenario,*urls),80)
    except Exception:
        failed=True
    # Generate failure outside the original exception context; never print URLs.
    if failed:
        pytest.fail("Live pipeline verification failed; check configured dependencies and owned test resources",pytrace=False)


async def _scenario(root,scenario,database_url,redis_url):
    connection=client=publisher=proxy=None
    processes=[]
    logs=[]
    job=str(uuid4())
    jobs={job}
    token=uuid4().hex
    key_prefix=f"ms_live_{token}:"
    queue_prefix=f"ms_live_{token}_"
    control=root/job
    control.mkdir()
    (control/"scenario.json").write_text(json.dumps(scenario))
    stop=threading.Event()
    sse=None
    cleanup_failed=False
    body_error=None
    try:
        connection=await asyncpg.connect(database_url,timeout=2,command_timeout=5)
        await _guard(connection)
        client=Redis.from_url(redis_url,decode_responses=True,socket_connect_timeout=2,socket_timeout=2)
        await client.ping()
        await client.client_list()
        proxy=Proxy(redis_url)
        env=dict(os.environ,DATABASE_URL=str(database_url),CELERY_BROKER_URL=str(proxy.url),REDIS_URL=str(redis_url),
            LOCAL_STORAGE_DIR=str(root/"storage"),MUSICSHEET_LIVE_CONTROL=str(root),
            MUSICSHEET_LIVE_KEY_PREFIX=key_prefix,MUSICSHEET_LIVE_QUEUE_PREFIX=queue_prefix,
            PYTHONPATH=os.pathsep.join((str(REPO/"tests"),str(REPO))))
        env.pop("CELERY_RESULT_BACKEND",None)
        settings=PipelineSettings.from_env(env,working_directory=REPO)
        publisher=scoped_publisher(settings,queue_prefix,key_prefix)
        node=f"{queue_prefix}@live"
        def launch(command,name):
            log=(root/f"{name}.log").open("wb")
            logs.append(log)
            process=OwnedProcess(subprocess.Popen(command,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
            processes.append(process)
            return process
        worker_command=[sys.executable,"-m","celery","-A","pipeline.integration.worker_app:app","worker",
            "--pool","prefork","--concurrency","2","--hostname",node,"--loglevel","INFO",
            "--without-gossip","--without-mingle","--without-heartbeat","-Q",
            ",".join(queue_prefix+q for q in ("cpu_io_queue","gpu_ai_queue","cpu_render_queue"))]
        worker=launch(worker_command,"worker")
        async def worker_ready():
            if worker.poll() is not None:
                raise HarnessUnavailable()
            return bool(await asyncio.to_thread(publisher.app.control.ping,destination=[node],timeout=.2))
        await wait_until(worker_ready)
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1",0))
            port=port_socket.getsockname()[1]
        api=launch(["uv","run","--offline","--no-sync","--project","services/api","--python","3.13","python","-m","uvicorn",
            "musicsheet_api.app:app","--host","127.0.0.1","--port",str(port)],"api")
        def health():
            http_connection=http.client.HTTPConnection("127.0.0.1",port,timeout=2)
            try:
                http_connection.request("GET","/health/live")
                return http_connection.getresponse().status==200
            except OSError:
                return False
            finally:
                http_connection.close()
        async def api_ready():
            if api.poll() is not None:
                raise HarnessUnavailable()
            return await asyncio.to_thread(health)
        await wait_until(api_ready)
        await connection.execute("INSERT INTO jobs(id,source_type,source_url) VALUES($1,'YOUTUBE','https://www.youtube.com/watch?v=abcdefghijk')",job)
        message=StageMessage(job,"DOWNLOAD",1)
        await enqueue_stage(connection,message)
        scoped=ScopedConnection(connection,jobs)
        if scenario=="commit_failure":
            scoped.fail_commit=True
            from musicsheet_pipeline.dispatcher import DispatchUnavailable
            try:
                await dispatch_once(scoped,publisher)
            except DispatchUnavailable:
                pass
            else:
                raise HarnessUnavailable()
            scoped.fail_commit=False
        await dispatch_once(scoped,publisher)
        async def entered(): return (control/"entered").exists()
        await wait_until(entered)
        if scenario in {"duplicate","contend"}:
            await asyncio.to_thread(publisher.publish,message,task_id=str(uuid4()))
        if scenario=="contend":
            async def contention(): return "retry" in (root/"worker.log").read_text(errors="replace").lower()
            await wait_until(contention)
            assert len([r for r in _calls(control) if r["stage"]=="DOWNLOAD"])==1
            (control/"release").touch()
        elif scenario=="kill":
            # SIGKILL the owned group after provider-start proof, then restart it.
            if os.getpgid(worker.pid)!=worker.pid:
                raise HarnessUnavailable()
            os.killpg(worker.pid,signal.SIGKILL)
            worker.wait(timeout=5)
            (control/"release").touch()
            worker=launch(worker_command,"worker-restarted")
            await wait_until(worker_ready)
        elif scenario=="cancel":
            await connection.execute("UPDATE jobs SET status='CANCEL_REQUESTED' WHERE id=$1 AND status='RUNNING'",job)
        elif scenario=="broker_failure":
            proxy.cut()
            (control/"release").touch()
            delay_file=root/"retry-delay.jsonl"
            async def retry_started(): return delay_file.exists()
            await wait_until(retry_started)
            async def retry_ended(): return len(delay_file.read_text().splitlines())>=2
            await wait_until(retry_ended)
            delay=[json.loads(line) for line in delay_file.read_text().splitlines()]
            assert delay[1]["time"]-delay[0]["time"]>=5
            proxy.restore()
        sse=asyncio.create_task(asyncio.to_thread(_read_sse,port,job,stop))
        async def finished():
            await dispatch_once(scoped,publisher)
            status=await connection.fetchval("SELECT status FROM jobs WHERE id=$1",job)
            return status in {"COMPLETED","FAILED","CANCELED"}
        await wait_until(finished)
        expected="CANCELED" if scenario=="cancel" else "COMPLETED"
        assert await connection.fetchval("SELECT status FROM jobs WHERE id=$1",job)==expected
        events=await asyncio.wait_for(asyncio.shield(sse),30)
        assert events[-1][1]["status"]==expected and all(i for i,_ in events)
        rows=await connection.fetch("SELECT stage,attempt,generation,status FROM stage_attempts WHERE job_id=$1 ORDER BY started_at,attempt",job)
        if scenario!="cancel":
            assert [r["stage"] for r in rows if r["status"]=="COMPLETED"]==[s.value for s in __import__("musicsheet_common").PipelineStage]
            assert await connection.fetchval("SELECT count(*) FROM artifacts WHERE job_id=$1",job)==6
        if scenario in {"duplicate","contend","commit_failure"}:
            assert len([r for r in _calls(control) if r["stage"]=="DOWNLOAD"])==1
        if scenario=="retry_once":
            assert [(r["attempt"],r["generation"]) for r in rows if r["stage"]=="DOWNLOAD"]==[(1,1),(2,2)]
    except BaseException as error:
        body_error=error
        raise
    finally:
        async def cleanup():
            nonlocal cleanup_failed
            stop.set()
            if sse is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(sse),5)
                except Exception:
                    if not sse.done():
                        cleanup_failed=True
                        await asyncio.shield(asyncio.gather(sse,return_exceptions=True))
            for process in reversed(processes):
                try: await asyncio.to_thread(stop_owned_process,process)
                except Exception: cleanup_failed=True
            for log in logs:
                try: log.close()
                except Exception: cleanup_failed=True
            if publisher:
                try: publisher.close()
                except Exception: cleanup_failed=True
            if proxy:
                try: await asyncio.to_thread(proxy.close)
                except Exception: cleanup_failed=True
            if client:
                try:
                    keys=[key async for key in client.scan_iter(match=key_prefix+"*")]
                    keys.extend(f"job:{id}:events" for id in jobs)
                    owned=namespace_keys(keys,key_prefix,jobs)
                    if owned: await client.delete(*owned)
                except Exception: cleanup_failed=True
                finally:
                    try: await asyncio.wait_for(client.aclose(),2)
                    except Exception: cleanup_failed=True
            if connection:
                try:
                    await _guard(connection)
                    await connection.execute("DELETE FROM jobs WHERE id=ANY($1::varchar[])",list(jobs))
                    await connection.close(timeout=5)
                except Exception:
                    cleanup_failed=True
                    connection.terminate()
            if cleanup_failed:
                raise HarnessUnavailable()
        try:
            await _owned_cleanup(cleanup())
        except Exception:
            if body_error is None:
                raise HarnessUnavailable() from None
            body_error.add_note("Owned live harness cleanup also failed")


def _calls(control):
    path=control/"calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
