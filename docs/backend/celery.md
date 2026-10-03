# Backend Spec: Celery Orchestration

> **Canonical Owner:** `docs/backend/celery.md`  
> **관련 문서:** [docs/architecture/job-pipeline.md](../architecture/job-pipeline.md)
>
> **구현 상태:** `packages/pipeline/musicsheet_pipeline`에 Celery 앱·여섯 task·durable outbox dispatcher·실행 엔진이 구현됐습니다. [운영 명령](../../packages/pipeline/README.md)을 참조하세요. 제품 provider registry는 비어 있어 실제 다운로드·AI·렌더링은 후속 범위입니다. 현재 호스트에서는 실제 Linux worker 성공·복구 경로가 미검증입니다. 아래 코드는 목표 예시이며 실제 설정은 factory 코드가 기준입니다. Redis Streams는 SSE 이벤트용이며 Celery 브로커 큐와 별도 역할입니다.
>
> **W03 승인 설계:** [DB outbox와 단계 실행 계약](../superpowers/specs/2026-10-03-celery-orchestration-design.md), [실행 계획](../plans/celery-orchestration-implementation-plan.md).

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

## 2. 단계 연결과 취소 처리

- 단계 성공 상태·출력 아티팩트·다음 단계 발행 대기 기록을 같은 PostgreSQL 트랜잭션에 저장하고, dispatcher가 outbox를 통해 Celery 큐에 전달한다. W03에서는 이 순차 연결을 사용하며 `chain`/`chord`를 필수로 요구하지 않는다. 상세 장애·중복·재시도 계약은 승인 설계를 참조한다.
- 각 Task 시작 시점에 `jobs` 테이블을 조회하여 상태가 `CANCEL_REQUESTED`이면 실행을 중단하고 `CANCELED`로 종료한다.
