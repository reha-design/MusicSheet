from pathlib import Path

import pytest

from musicsheet_api.config import Settings
from musicsheet_api.pipeline.celery_app import create_celery_app


def test_celery_defaults_and_transport_options(tmp_path: Path) -> None:
    settings = Settings.from_env({}, working_directory=tmp_path)
    app = create_celery_app(settings)

    assert settings.celery_broker_url == "redis://localhost:6379/0"
    assert settings.celery_result_backend == "redis://localhost:6379/1"
    assert settings.celery_visibility_timeout == 3600
    assert app.conf.broker_url == settings.celery_broker_url
    assert app.conf.result_backend == settings.celery_result_backend
    assert app.conf.broker_transport_options == {
        "visibility_timeout": 3600,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "max_retries": 3,
    }
    assert app.conf.task_publish_retry_policy["max_retries"] == 3
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True


def test_celery_environment_overrides(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "CELERY_BROKER_URL": "redis://broker.internal:6379/3",
            "CELERY_RESULT_BACKEND": "redis://results.internal:6379/4",
            "CELERY_VISIBILITY_TIMEOUT": "7200",
            "REDIS_URL": "redis://events.internal:6379/2",
        },
        working_directory=tmp_path,
    )
    app = create_celery_app(settings)

    assert app.conf.broker_url == "redis://broker.internal:6379/3"
    assert app.conf.result_backend == "redis://results.internal:6379/4"
    assert app.conf.broker_transport_options["visibility_timeout"] == 7200
    assert settings.redis_url == "redis://events.internal:6379/2"


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_visibility_timeout_must_be_positive_integer(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="CELERY_VISIBILITY_TIMEOUT"):
        Settings.from_env(
            {"CELERY_VISIBILITY_TIMEOUT": value}, working_directory=tmp_path
        )


def test_celery_queues_and_explicit_task_routes(tmp_path: Path) -> None:
    app = create_celery_app(Settings.from_env({}, working_directory=tmp_path))

    assert {queue.name for queue in app.conf.task_queues} == {
        "cpu_io_queue",
        "gpu_ai_queue",
        "cpu_render_queue",
    }
    assert app.conf.task_routes == {
        "musicsheet.pipeline.start_job": {"queue": "cpu_io_queue"},
        "musicsheet.pipeline.download_source": {"queue": "cpu_io_queue"},
        "musicsheet.pipeline.preprocess_audio": {"queue": "cpu_io_queue"},
        "musicsheet.pipeline.separate_audio": {"queue": "gpu_ai_queue"},
        "musicsheet.pipeline.transcribe_amt": {"queue": "gpu_ai_queue"},
        "musicsheet.pipeline.quantize_and_score": {"queue": "cpu_render_queue"},
        "musicsheet.pipeline.render_pdf": {"queue": "cpu_render_queue"},
    }
