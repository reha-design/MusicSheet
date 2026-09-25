# Backend Spec: Celery Orchestration

> **Canonical Owner:** `docs/backend/celery.md`  
> **관련 문서:** [docs/architecture/job-pipeline.md](../architecture/job-pipeline.md)
>
> **구현 상태:** 아래 코드는 목표 설정 예시입니다. 현재 저장소에는 Celery 앱과 worker가 없습니다. Redis Streams는 SSE 이벤트용이며 Celery 브로커 큐와 별도 역할입니다. [Redis 이벤트 명세](./redis-streams.md)를 참조하세요.

---

## 1. Celery 기본 설정

```python
# packages/pipeline/workers/celery_app.py
from celery import Celery

celery_app = Celery("musicsheet_pipeline")

celery_app.conf.update(
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/1",
    task_acks_late=True,                     # 멱등성 보장
    task_reject_on_worker_lost=True,         # 워커 크래시 시 태스크 재전달
    task_track_started=True,
    task_routes={
        "pipeline.tasks.download": {"queue": "cpu_io_queue"},
        "pipeline.tasks.preprocess": {"queue": "cpu_io_queue"},
        "pipeline.tasks.separate": {"queue": "gpu_ai_queue"},
        "pipeline.tasks.transcribe": {"queue": "gpu_ai_queue"},
        "pipeline.tasks.postprocess": {"queue": "cpu_render_queue"},
        "pipeline.tasks.render": {"queue": "cpu_render_queue"},
    }
)
```

---

## 2. Task Chaining & 취소 처리

- Celery `chain` 또는 `chord`를 통해 Stage 간 데이터(`job_id`, `artifact_id`)를 파이프라인으로 연결한다.
- 각 Task 시작 시점에 `jobs` 테이블을 조회하여 상태가 `CANCEL_REQUESTED`이면 실행을 중단하고 `CANCELED`로 종료한다.
