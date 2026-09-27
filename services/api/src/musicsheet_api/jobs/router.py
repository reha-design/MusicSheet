"""HTTP endpoints for creating and reading durable jobs."""

from fastapi import APIRouter, HTTPException, Request, status

from musicsheet_api.jobs.repository import JobRepository
from musicsheet_api.jobs.schemas import JobResponse, YouTubeJobCreateRequest
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
