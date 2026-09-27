"""HTTP endpoints for creating and reading durable jobs."""

from fastapi import APIRouter, HTTPException, Request, status
from starlette.datastructures import UploadFile

from musicsheet_api.jobs.repository import JobRepository
from musicsheet_api.jobs.schemas import JobResponse, YouTubeJobCreateRequest
from musicsheet_api.jobs.upload_body_limit import UploadRequestTooLarge
from musicsheet_api.jobs.uploads import UploadTooLarge, create_upload_job
from musicsheet_api.jobs.youtube import normalize_youtube_url


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _job_repository(request: Request) -> JobRepository:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job database is unavailable",
        )
    return JobRepository(pool)


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
