from celery import Celery

from musicsheet_api.pipeline.dispatcher import CeleryWorkflowDispatcher


def test_dispatch_publishes_one_start_task_with_job_id_only() -> None:
    app = Celery("test-dispatch", broker="memory://", backend="cache+memory://")
    dispatcher = CeleryWorkflowDispatcher(app)

    dispatcher.submit("job-123")

    with app.connection_for_read() as connection:
        with connection.SimpleQueue("cpu_io_queue") as queue:
            message = queue.get(block=False)
            assert message.headers["task"] == "musicsheet.pipeline.start_job"
            assert message.payload[0] == ["job-123"]
            assert message.payload[1] == {}
            assert queue.qsize() == 0
            message.ack()
