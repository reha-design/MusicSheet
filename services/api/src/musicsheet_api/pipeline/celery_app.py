"""Celery configuration for the separate orchestration workers.

Run one worker per queue. Recommended concurrency is 4–8 for cpu_io_queue,
1 for gpu_ai_queue, and 2–4 for cpu_render_queue.
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from musicsheet_api.config import Settings


TASK_QUEUES = (
    Queue("cpu_io_queue"),
    Queue("gpu_ai_queue"),
    Queue("cpu_render_queue"),
)

TASK_ROUTES = {
    "musicsheet.pipeline.start_job": {"queue": "cpu_io_queue"},
    "musicsheet.pipeline.download_source": {"queue": "cpu_io_queue"},
    "musicsheet.pipeline.preprocess_audio": {"queue": "cpu_io_queue"},
    "musicsheet.pipeline.separate_audio": {"queue": "gpu_ai_queue"},
    "musicsheet.pipeline.transcribe_amt": {"queue": "gpu_ai_queue"},
    "musicsheet.pipeline.quantize_and_score": {"queue": "cpu_render_queue"},
    "musicsheet.pipeline.render_pdf": {"queue": "cpu_render_queue"},
}


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Configure the worker without opening a broker connection."""
    settings = settings or Settings.from_env()
    app = Celery(
        "musicsheet_pipeline",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    app.conf.update(
        task_queues=TASK_QUEUES,
        task_routes=TASK_ROUTES,
        task_default_queue="cpu_io_queue",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        broker_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout,
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
            "max_retries": 3,
        },
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 1,
        },
    )
    return app


celery_app = create_celery_app()
