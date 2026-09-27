"""HTTP endpoints for creating and reading durable jobs."""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from musicsheet_common import ArtifactRef, JobStatus
from starlette.datastructures import UploadFile
from starlette.types import Receive, Scope, Send

from musicsheet_api.jobs.artifacts import ArtifactRecord, ArtifactRepository
from musicsheet_api.jobs.repository import JobRepository
from musicsheet_api.jobs.schemas import (
    ArtifactResponse,
    JobResponse,
    YouTubeJobCreateRequest,
)
from musicsheet_api.jobs.upload_body_limit import UploadRequestTooLarge
from musicsheet_api.jobs.uploads import UploadTooLarge, create_upload_job
from musicsheet_api.jobs.youtube import normalize_youtube_url


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
_logger = logging.getLogger(__name__)
_SAFE_MEDIA_TYPE = re.compile(
    r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$"
)


def _job_repository(request: Request) -> JobRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job database is unavailable",
        )
    return JobRepository(pool)


def _artifact_repository(request: Request) -> ArtifactRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact database is unavailable",
        )
    return ArtifactRepository(pool)


def _artifact_response(record: ArtifactRecord) -> ArtifactResponse:
    return ArtifactResponse(
        id=record.id,
        job_id=record.job_id,
        role=record.role,
        filename=record.filename,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        producer=record.producer,
        producer_version=record.producer_version,
        created_at=record.created_at,
        download_url=(
            f"/api/v1/jobs/{record.job_id}/artifacts/{record.id}/content"
        ),
    )


def _download_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    safe = "".join(
        char for char in basename if ord(char) >= 32 and ord(char) != 127
    )
    return safe.strip(" .") or "artifact"


async def _stream_content(stream: BinaryIO) -> AsyncIterator[bytes]:
    while True:
        try:
            chunk = await asyncio.to_thread(stream.read, 64 * 1024)
        except Exception:
            _logger.warning("Artifact download stream read failed")
            return
        if not chunk:
            break
        yield chunk


class _ClosingStreamingResponse(StreamingResponse):
    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        stream: BinaryIO,
        **kwargs: Any,
    ) -> None:
        self._stream = stream
        super().__init__(content, **kwargs)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await asyncio.to_thread(self._stream.close)
            except Exception:
                pass


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_youtube_job(
    body: YouTubeJobCreateRequest,
    request: Request,
) -> JobResponse:
    try:
        canonical_url = normalize_youtube_url(body.source_url)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid YouTube URL",
        ) from None

    repository = _job_repository(request)
    try:
        job = await repository.create_job(
            source_type="YOUTUBE",
            source_url=canonical_url,
            target_instrument=body.target_instrument,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job database is unavailable",
        ) from None
    return JobResponse.model_validate(job)


@router.post("/upload", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def upload_audio_job(request: Request) -> JobResponse:
    pool = getattr(request.app.state, "db_pool", None)
    storage = getattr(request.app.state, "storage", None)
    settings = request.app.state.settings
    if pool is None or storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload storage is unavailable",
        )

    try:
        form = await request.form(max_files=1, max_fields=1)
    except UploadRequestTooLarge:
        raise
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid upload form",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid upload form",
        ) from None

    try:
        items = list(form.multi_items())
        names = [name for name, _ in items]
        if any(name not in {"file", "target_instrument"} for name in names):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid upload form",
            )
        if names.count("file") != 1 or names.count("target_instrument") > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid upload form",
            )

        values = dict(items)
        upload = values["file"]
        if not isinstance(upload, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid upload form",
            )
        target_instrument = values.get("target_instrument", "piano")
        if not isinstance(target_instrument, str) or target_instrument != "piano":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid upload form",
            )

        try:
            job = await create_upload_job(
                file=upload.file,
                original_filename=upload.filename or "",
                target_instrument=target_instrument,
                pool=pool,
                storage=storage,
                max_upload_bytes=settings.max_upload_bytes,
            )
        except UploadTooLarge:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Uploaded file is too large",
            ) from None
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid upload form",
            ) from None
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Upload storage is unavailable",
            ) from None
        return JobResponse.model_validate(job)
    finally:
        await form.close()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request) -> JobResponse:
    repository = _job_repository(request)
    try:
        job = await repository.get_job(job_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job database is unavailable",
        ) from None
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return JobResponse.model_validate(job)


@router.delete(
    "/{job_id}",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_job(job_id: str, request: Request) -> JobResponse:
    repository = _job_repository(request)
    try:
        job = await repository.request_cancel(job_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job database is unavailable",
        ) from None
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job is already terminal",
        )
    return JobResponse.model_validate(job)


@router.get(
    "/{job_id}/artifacts",
    response_model=list[ArtifactResponse],
)
async def list_artifacts(job_id: str, request: Request) -> list[ArtifactResponse]:
    job_repository = _job_repository(request)
    artifact_repository = _artifact_repository(request)
    try:
        job = await job_repository.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            )
        records = await artifact_repository.list_for_job(job_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact database is unavailable",
        ) from None
    return [_artifact_response(record) for record in records]


@router.get("/{job_id}/artifacts/{artifact_id}/content")
async def download_artifact(
    job_id: str,
    artifact_id: str,
    request: Request,
) -> StreamingResponse:
    repository = _artifact_repository(request)
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact storage is unavailable",
        )
    try:
        record = await repository.get_for_job(job_id, artifact_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact database is unavailable",
        ) from None
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found",
        )

    artifact = ArtifactRef(
        id=record.id,
        job_id=record.job_id,
        role=record.role,
        filename=record.filename,
        uri=record.uri,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        producer=record.producer,
        producer_version=record.producer_version,
    )
    try:
        stream = await asyncio.to_thread(storage.open_read, artifact)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact content not found",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Artifact storage is unavailable",
        ) from None

    filename = quote(_download_filename(record.filename), safe="")
    media_type = (
        record.mime_type
        if _SAFE_MEDIA_TYPE.fullmatch(record.mime_type)
        else "application/octet-stream"
    )
    return _ClosingStreamingResponse(
        _stream_content(stream),
        stream=stream,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(record.size_bytes),
        },
    )
