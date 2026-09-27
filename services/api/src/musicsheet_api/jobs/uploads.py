"""Store uploaded audio and transactionally register its metadata."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import BinaryIO, TypeVar
from uuid import uuid4

import asyncpg
from musicsheet_common import ArtifactRef, ArtifactRole
from musicsheet_storage import ArtifactStorage

from musicsheet_api.jobs.artifacts import ArtifactRepository
from musicsheet_api.jobs.models import JobRecord
from musicsheet_api.jobs.repository import JobRepository


_ALLOWED_MIME_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}
_CLEANUP_WARNING = "Upload rollback cleanup failed"
_logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class UploadTooLarge(ValueError):
    """Raised when the uploaded file exceeds its configured byte limit."""


class _LimitedReader:
    def __init__(self, source: BinaryIO, max_bytes: int) -> None:
        self._source = source
        self._max_bytes = max_bytes
        self._read_bytes = 0

    def read(self, size: int = -1) -> bytes:
        remaining_with_probe = self._max_bytes - self._read_bytes + 1
        requested = remaining_with_probe if size < 0 else min(size, remaining_with_probe)
        chunk = self._source.read(requested)
        if not isinstance(chunk, bytes):
            raise TypeError("upload source must be a binary stream")
        if self._read_bytes + len(chunk) > self._max_bytes:
            raise UploadTooLarge
        self._read_bytes += len(chunk)
        return chunk


async def _wait_for_task(task: asyncio.Task[_T]) -> _T:
    """Wait for an operation to finish despite repeated caller cancellation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    return task.result()


async def _delete_best_effort(
    storage: ArtifactStorage,
    artifact: ArtifactRef,
) -> None:
    cleanup_task = asyncio.create_task(asyncio.to_thread(storage.delete, artifact))
    try:
        await _wait_for_task(cleanup_task)
    except BaseException:
        _logger.warning(_CLEANUP_WARNING)


async def create_upload_job(
    *,
    file: BinaryIO,
    original_filename: str,
    target_instrument: str,
    pool: asyncpg.Pool,
    storage: ArtifactStorage,
    max_upload_bytes: int,
) -> JobRecord:
    """Write bytes once, then commit job and artifact metadata atomically."""
    suffix = os.path.splitext(original_filename)[1].lower()
    mime_type = _ALLOWED_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError("unsupported audio extension")
    if target_instrument != "piano":
        raise ValueError("unsupported target instrument")

    job_id = str(uuid4())
    artifact: ArtifactRef | None = None
    async with pool.acquire() as connection:
        try:
            put_task = asyncio.create_task(
                asyncio.to_thread(
                    storage.put,
                    job_id=job_id,
                    filename=f"source_original{suffix}",
                    role=ArtifactRole.SOURCE_ORIGINAL,
                    source=_LimitedReader(file, max_upload_bytes),
                    producer="musicsheet-api",
                    producer_version="0.1.0",
                )
            )
            try:
                artifact = await asyncio.shield(put_task)
            except asyncio.CancelledError:
                try:
                    artifact = await _wait_for_task(put_task)
                except BaseException:
                    pass
                else:
                    await _delete_best_effort(storage, artifact)
                    artifact = None
                raise

            if artifact.mime_type != mime_type:
                artifact = artifact.model_copy(update={"mime_type": mime_type})

            async def register_metadata() -> JobRecord:
                async with connection.transaction():
                    job_record = await JobRepository(pool).create_job(
                        source_type="UPLOAD",
                        source_url=None,
                        target_instrument=target_instrument,
                        job_id=job_id,
                        connection=connection,
                    )
                    await ArtifactRepository(pool).add(artifact, connection=connection)
                return job_record

            metadata_task = asyncio.create_task(register_metadata())
            try:
                job = await asyncio.shield(metadata_task)
            except asyncio.CancelledError:
                try:
                    await _wait_for_task(metadata_task)
                except BaseException:
                    pass
                else:
                    # The transaction committed; its file must remain available.
                    artifact = None
                raise
            return job
        except BaseException:
            if artifact is not None:
                await _delete_best_effort(storage, artifact)
            raise
