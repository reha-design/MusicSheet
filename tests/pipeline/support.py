"""Stateful external DB double. Only persistence effects, never stage decisions."""
import copy
import json
from datetime import datetime, timezone, timedelta

from musicsheet_common import ArtifactRef, ArtifactRole

JOB = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"


def artifact(job_id=JOB):
    return ArtifactRef(id=OTHER, job_id=job_id, role=ArtifactRole.SOURCE_ORIGINAL,
        filename="source.wav", uri="file:///tmp/source.wav", mime_type="audio/wav",
        size_bytes=3, sha256="a"*64, producer="test", producer_version="1")


class Database:
    def __init__(self):
        self.jobs = {JOB: dict(id=JOB, user_id=None, source_type="UPLOAD", source_url=None,
            target_instrument="piano", status="PENDING", current_stage="DOWNLOAD",
            stage_progress=0, overall_progress=0, active_attempt_id=None,
            error_code=None, error_message=None, created_at=None, updated_at=None, completed_at=None)}
        self.attempts = {}
        self.artifacts = {OTHER: artifact().model_dump()}
        self.outbox = {}
        self.locks = set()
        self.outbox_locks = set()


class Transaction:
    def __init__(self, connection):
        self.c = connection

    async def __aenter__(self):
        self.snapshot = copy.deepcopy((self.c.db.jobs, self.c.db.attempts, self.c.db.artifacts, self.c.db.outbox))
        self.c.transactions += 1
        self.c.in_transaction = True

    async def __aexit__(self, typ, value, tb):
        self.c.in_transaction = False
        self.c.db.outbox_locks.difference_update(self.c.locked_outbox)
        self.c.locked_outbox.clear()
        if typ or self.c.fail_commit:
            self.c.db.jobs, self.c.db.attempts, self.c.db.artifacts, self.c.db.outbox = self.snapshot
            if not typ:
                raise OSError("secret-commit")


class Connection:
    def __init__(self, database=None):
        self.db = database or Database()
        self.transactions = 0
        self.in_transaction = False
        self.closed = False
        self.listeners = []
        self.held_locks = set()
        self.locked_outbox = set()
        self.fail_outbox = False
        self.fail_commit = False
        self.fail_query = False
        self.queries = []

    def transaction(self):
        return Transaction(self)

    def is_closed(self):
        return self.closed

    def is_in_transaction(self):
        return self.in_transaction

    def add_termination_listener(self, listener):
        self.listeners.append(listener)

    def remove_termination_listener(self, listener):
        self.listeners.remove(listener)

    def terminate(self):
        self.closed = True
        self.db.locks.difference_update(self.held_locks)
        self.held_locks.clear()
        for listener in list(self.listeners):
            listener(self)

    def tag(self, query, args):
        self.queries.append((query, args))
        if self.closed or self.fail_query:
            raise OSError("secret-dsn")
        return query.split("*/", 1)[0].removeprefix("/* ").strip()

    async def fetchval(self, query, *args):
        tag = self.tag(query, args)
        if tag == "maintenance.stale":
            return args[0] <= datetime.now(timezone.utc)-timedelta(seconds=args[1])
        if tag == "pipeline.lock":
            if args[0] in self.db.locks and args[0] not in self.held_locks:
                return False
            self.db.locks.add(args[0])
            self.held_locks.add(args[0])
            return True
        if tag == "pipeline.unlock":
            self.db.locks.discard(args[0])
            self.held_locks.discard(args[0])
            return True
        if tag == "pipeline.artifact.insert":
            a = dict(zip(("id","job_id","role","filename","uri","mime_type","size_bytes","sha256","producer","producer_version"),args))
            old = self.db.artifacts.get(a["id"])
            if old and old != a:
                return None
            self.db.artifacts.setdefault(a["id"],a)
            return a["id"]
        raise AssertionError(tag)

    async def fetchrow(self, query, *args):
        tag = self.tag(query, args)
        if tag == "pipeline.dispatch.next":
            rows=[dict(row,status=self.db.jobs[row["job_id"]]["status"]) for row in self.db.outbox.values()
                  if row["published_at"] is None and row["available_at"]<=datetime.now(timezone.utc) and row["id"] not in self.db.outbox_locks]
            if not rows:
                return None
            row=sorted(rows,key=lambda r:(r["available_at"],r["id"]))[0]
            self.db.outbox_locks.add(row["id"])
            self.locked_outbox.add(row["id"])
            return row
        if tag == "pipeline.job":
            return copy.deepcopy(self.db.jobs.get(args[0]))
        if tag == "pipeline.reservation":
            values = [v for k,v in self.db.outbox.items() if k[:2] == args[:2]]
            value = self.db.outbox.get(tuple(args))
            return dict(current_generation=max(v["generation"] for v in values), ready=value["available_at"]<=datetime.now(timezone.utc)) if value else None
        if tag == "pipeline.job.update":
            job, status, stage, progress, overall, active, code, message = args
            row = self.db.jobs[job]
            row.update(status=status, current_stage=stage, stage_progress=progress,
                overall_progress=overall, active_attempt_id=active, error_code=code, error_message=message,
                updated_at=datetime.now(timezone.utc))
            if status in ("COMPLETED","FAILED","CANCELED"):
                row["completed_at"] = datetime.now(timezone.utc)
            return copy.deepcopy(row)
        raise AssertionError(tag)

    async def fetch(self, query, *args):
        tag = self.tag(query, args)
        if tag == "maintenance.scan":
            cutoff = datetime.now(timezone.utc)-timedelta(seconds=args[0])
            jobs = sorted((j for j in self.db.jobs.values() if j["status"] in ("PENDING","RUNNING","RETRYING","CANCEL_REQUESTED")
                and j["updated_at"] is not None and j["updated_at"] <= cutoff), key=lambda j: (j["updated_at"],j["id"]))[:args[1]]
            result = []
            for j in jobs:
                attempts = [a for a in self.db.attempts.values() if a["job_id"] == j["id"]]
                oldest = datetime.min.replace(tzinfo=timezone.utc)
                latest = max(attempts, key=lambda a: (a.get("started_at") is not None,a.get("started_at") or oldest,a["id"])) if attempts else None
                summary = {"latest_"+name: latest.get(name) if latest else None for name in ("stage","attempt","generation","status","error_code")}
                result.append(dict(j, **summary))
            return result
        if tag == "pipeline.attempts":
            return sorted([copy.deepcopy(a) for a in self.db.attempts.values() if (a["job_id"],a["stage"])==args], key=lambda a:a["attempt"], reverse=True)
        if tag == "pipeline.inputs":
            return [copy.deepcopy(a) for a in self.db.artifacts.values() if a["job_id"]==args[0] and a["role"]==args[1]]
        if tag == "pipeline.artifacts":
            return [copy.deepcopy(self.db.artifacts[i]) for i in args[1] if i in self.db.artifacts and self.db.artifacts[i]["job_id"]==args[0]]
        if tag == "pipeline.recover":
            return [dict(id=j["id"]) for j in self.db.jobs.values() if j["status"]=="PENDING" and j["current_stage"]=="DOWNLOAD" and not any(k[0]==j["id"] for k in self.db.outbox) and not any(a["job_id"]==j["id"] for a in self.db.attempts.values())][:args[0]]
        raise AssertionError(tag)

    async def execute(self, query, *args):
        tag = self.tag(query, args)
        if tag == "maintenance.attempts.close":
            now = datetime.now(timezone.utc)
            for row in self.db.attempts.values():
                if row["job_id"] == args[0] and row["status"] == "RUNNING":
                    start = row.get("started_at") or now
                    row.update(status="FAILED",error_code=args[1],error_detail=None,completed_at=now,
                               duration_ms=min(2147483647,max(0,int((now-start).total_seconds()*1000))))
            return "OK"
        if tag == "maintenance.consume":
            for row in self.db.outbox.values():
                if row["job_id"] == args[0] and row["published_at"] is None:
                    row["published_at"] = datetime.now(timezone.utc)
            return "OK"
        if tag == "pipeline.dispatch.sent":
            next(row for row in self.db.outbox.values() if row["id"]==args[0])["published_at"]=datetime.now(timezone.utc)
            return "UPDATE 1"
        if tag == "pipeline.enqueue":
            if self.fail_outbox:
                raise OSError("secret-outbox")
            id, job, stage, generation, delay = args
            self.db.outbox.setdefault((job,stage,generation), dict(id=id,job_id=job,stage=stage,generation=generation,available_at=datetime.now(timezone.utc)+timedelta(seconds=delay),published_at=None))
        elif tag == "pipeline.attempt.insert":
            id, job, stage, attempt, generation, provider, version, fingerprint = args
            self.db.attempts[id] = dict(id=id,job_id=job,stage=stage,attempt=attempt,generation=generation,provider=provider,model_version=version,input_fingerprint=fingerprint,status="RUNNING",output_artifact_ids=[],error_code=None)
        elif tag == "pipeline.attempt.finish":
            id,status,code,outputs = args
            self.db.attempts[id].update(status=status,error_code=code,output_artifact_ids=json.loads(outputs))
        elif tag == "pipeline.artifact.insert":
            a = dict(zip(("id","job_id","role","filename","uri","mime_type","size_bytes","sha256","producer","producer_version"),args))
            self.db.artifacts.setdefault(a["id"],a)
        else:
            raise AssertionError(tag)
        return "OK"
