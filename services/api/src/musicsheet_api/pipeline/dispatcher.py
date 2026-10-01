"""Synchronous boundary for submitting a persisted job to Celery."""

from __future__ import annotations

from celery import Celery

from musicsheet_api.pipeline.celery_app import celery_app


class CeleryWorkflowDispatcher:
    def __init__(self, app: Celery | None = None) -> None:
        self._app = app or celery_app

    def submit(self, job_id: str) -> None:
        """Publish exactly one start task; worker stages are chained downstream."""
        self._app.send_task(
            "musicsheet.pipeline.start_job",
            args=(job_id,),
            queue="cpu_io_queue",
        )
