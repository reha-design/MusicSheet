"""Persistence models and operations for jobs."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from musicsheet_api.jobs.models import JobRecord
    from musicsheet_api.jobs.repository import JobRepository

__all__ = ["JobRecord", "JobRepository"]


def __getattr__(name: str) -> Any:
    if name == "JobRecord":
        from musicsheet_api.jobs.models import JobRecord

        return JobRecord
    if name == "JobRepository":
        from musicsheet_api.jobs.repository import JobRepository

        return JobRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
