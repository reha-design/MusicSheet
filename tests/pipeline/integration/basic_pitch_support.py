"""Guarded disposable PostgreSQL fixtures; never reset a shared schema."""
import asyncio
from contextlib import asynccontextmanager
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import asyncpg
import pytest

from musicsheet_common import ArtifactRole, PipelineStage
from musicsheet_pipeline.contracts import ProviderIdentity, StageMessage
from musicsheet_pipeline.outbox import enqueue_stage
from musicsheet_pipeline.runner import run_stage
from musicsheet_pipeline.tasks import _owned_cleanup
from musicsheet_storage import LocalStorage


class SecretUrl(str):
    def __repr__(self):
        return "<redacted disposable database URL>"


async def assert_disposable(connection):
    row = await connection.fetchrow("SELECT current_database() AS name, "
        "shobj_description(oid,'pg_database') AS marker FROM pg_database WHERE datname=current_database()")
    if row["name"] != "musicsheet_test" or row["marker"] != "MUSICSHEET_DISPOSABLE_TEST_DB_V1":
        raise ValueError("Refusing an unmarked disposable database")
    if await connection.fetchval("SELECT max(version) FROM schema_migrations") != 2:
        raise ValueError("Disposable database requires explicit migrations 1 and 2")


async def wait_until(predicate):
    deadline = asyncio.get_running_loop().time() + 30
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "Controlled worker did not start"
        await asyncio.sleep(.02)


@asynccontextmanager
async def owned_job(root, audio):
    value = os.getenv("MUSICSHEET_TEST_DATABASE_URL")
    if not value:
        pytest.skip("MUSICSHEET_TEST_DATABASE_URL is required for disposable DB verification")
    connection = observer = None
    directory = None
    job = str(uuid4())
    guarded = False
    try:
        observer = await asyncpg.connect(SecretUrl(value), timeout=5, command_timeout=5)
        await assert_disposable(observer)
        guarded = True
        connection = await asyncpg.connect(SecretUrl(value), timeout=5, command_timeout=5)
        await assert_disposable(connection)
        directory = TemporaryDirectory(prefix="w04-artifacts-", dir=root)
        storage = LocalStorage(directory.name)
        await observer.execute("INSERT INTO jobs(id,source_type) VALUES($1,'UPLOAD')", job)
        ref = storage.put(job, "source.wav", ArtifactRole.SOURCE_ORIGINAL, io.BytesIO(audio), "upload", "1")
        await observer.execute("INSERT INTO artifacts(id,job_id,role,filename,uri,mime_type,size_bytes,sha256,producer,producer_version) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)", ref.id, job, ref.role.value, ref.filename,
            ref.uri, ref.mime_type, ref.size_bytes, ref.sha256, ref.producer, ref.producer_version)

        class Before:
            def __init__(self, incoming, outgoing):
                self.outgoing = outgoing
                self.identity = ProviderIdentity("test-before", "1", {}, frozenset({incoming}), frozenset({outgoing}))
            async def run(self, ctx):
                if ctx.message.stage == PipelineStage.DOWNLOAD:
                    return ctx.inputs
                return (storage.put(job, f"attempt_{ctx.attempt_id}_audio.wav", self.outgoing,
                    io.BytesIO(audio), self.identity.name, self.identity.version),)
        providers = {PipelineStage.DOWNLOAD: Before(ArtifactRole.SOURCE_ORIGINAL, ArtifactRole.SOURCE_ORIGINAL),
            PipelineStage.PREPROCESS: Before(ArtifactRole.SOURCE_ORIGINAL, ArtifactRole.CANONICAL_AUDIO),
            PipelineStage.SEPARATE: Before(ArtifactRole.CANONICAL_AUDIO, ArtifactRole.SEPARATED_AUDIO)}
        await enqueue_stage(connection, StageMessage(job, "DOWNLOAD", 1))
        for stage in providers:
            await run_stage(StageMessage(job, stage, 1), connection=connection, storage=storage,
                providers=providers, event_store=None)
        assert await observer.fetchval("SELECT count(*) FROM stage_attempts WHERE job_id=$1 AND status='COMPLETED'", job) == 3
        yield connection, observer, storage, job
    finally:
        async def cleanup():
            try:
                try:
                    if connection is not None and not connection.is_closed():
                        try:
                            await connection.close(timeout=5)
                        except Exception:
                            connection.terminate()
                            raise
                finally:
                    if observer is not None and not observer.is_closed() and guarded:
                        await assert_disposable(observer)
                        await observer.execute("DELETE FROM jobs WHERE id=$1", job)
            finally:
                try:
                    if observer is not None and not observer.is_closed():
                        try:
                            await observer.close(timeout=5)
                        except Exception:
                            observer.terminate()
                            raise
                finally:
                    if directory is not None:
                        await asyncio.to_thread(directory.cleanup)
        await _owned_cleanup(cleanup())


def run_live(coroutine):
    try:
        asyncio.run(coroutine)
    except (AssertionError, ValueError):
        raise
    except Exception:
        pytest.fail("Disposable Basic Pitch DB verification failed", pytrace=False)
