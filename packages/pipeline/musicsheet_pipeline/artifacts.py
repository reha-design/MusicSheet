"""Artifact metadata and bounded file integrity checks in owned worker threads."""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from uuid import UUID

from musicsheet_common import ArtifactRef
from .contracts import InvalidArtifact

CHUNK_SIZE=64*1024
_SHA=re.compile(r"[0-9a-f]{64}",re.ASCII)


class _ValidationStopped(Exception):
    """Private cooperative stop signal, distinct from storage OSError."""


def _validate(refs,*,job_id,identity,storage,attempt_id,existing_inputs,stop,mode):
    try:
        if not isinstance(refs,tuple) or (not refs and mode!="input"):
            raise ValueError
        trusted={a.id:a.model_dump(warnings=False) for a in existing_inputs}
        result=[]
        ids=set()
        roles=identity.input_roles if mode=="input" else identity.output_roles
        for original in refs:
            if stop.is_set():
                raise _ValidationStopped
            data=original.model_dump(warnings=False)
            ref=ArtifactRef.model_validate(data)
            if ref.job_id!=job_id or ref.id in ids or str(UUID(ref.id))!=ref.id or str(UUID(ref.job_id))!=ref.job_id:
                raise ValueError
            if ref.role not in roles or not _SHA.fullmatch(ref.sha256) or type(data["size_bytes"]) is not int:
                raise ValueError
            reused=trusted.get(ref.id)==data
            if mode=="input" and not reused:
                raise ValueError
            if mode!="input" and not reused:
                if ref.producer!=identity.name or ref.producer_version!=identity.version or not ref.filename.startswith(f"attempt_{attempt_id}_"):
                    raise ValueError
            digest=hashlib.sha256()
            size=0
            with storage.open_read(ref) as stream:
                while True:
                    if stop.is_set():
                        raise _ValidationStopped
                    chunk=stream.read(CHUNK_SIZE)
                    if not isinstance(chunk,bytes) or len(chunk)>CHUNK_SIZE:
                        raise ValueError
                    if not chunk:
                        break
                    size+=len(chunk)
                    if size>ref.size_bytes:
                        raise ValueError
                    digest.update(chunk)
            if size!=ref.size_bytes or digest.hexdigest()!=ref.sha256:
                raise ValueError
            ids.add(ref.id)
            result.append(ref)
        return tuple(result)
    except _ValidationStopped:
        return None
    except Exception:
        raise InvalidArtifact() from None


async def validate_artifacts(artifacts,*,job_id,identity,storage,attempt_id,existing_inputs,cancellation,mode="output"):
    """Stop new reads on cancellation and drain the thread before returning."""
    if mode not in {"input","output"}:
        raise InvalidArtifact()
    stop=threading.Event()
    async def watch():
        await cancellation.wait()
        stop.set()
    watcher=asyncio.create_task(watch())
    thread=asyncio.create_task(asyncio.to_thread(_validate,artifacts,job_id=job_id,identity=identity,
        storage=storage,attempt_id=attempt_id,existing_inputs=existing_inputs,stop=stop,mode=mode))
    cancelled=False
    try:
        while not thread.done():
            try:
                await asyncio.shield(thread)
            except asyncio.CancelledError:
                cancelled=True
                stop.set()
            except InvalidArtifact:
                break
        if cancelled or cancellation.is_set():
            # Observe the owned result/exception before propagating cancellation.
            if not thread.cancelled():
                thread.exception()
            raise asyncio.CancelledError
        result=thread.result()
        if result is None:
            raise asyncio.CancelledError
        return result
    finally:
        watcher.cancel()
        await asyncio.gather(watcher,return_exceptions=True)
