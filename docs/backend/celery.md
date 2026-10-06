# Backend Spec: Celery Orchestration

> **Canonical Owner:** `docs/backend/celery.md`  
> **관련 문서:** [docs/architecture/job-pipeline.md](../architecture/job-pipeline.md)
>
> **구현 상태:** `packages/pipeline/musicsheet_pipeline`에 Celery 앱·여섯 task·durable outbox dispatcher·실행 엔진이 구현됐습니다. [운영 명령](../../packages/pipeline/README.md)을 참조하세요. 제품 provider registry는 비어 있어 실제 다운로드·AI·렌더링은 후속 범위입니다. 테스트 provider를 사용한 Docker Linux prefork worker8개 시나리오는 [실제 검증](../reports/celery-live-verification-report.md)을 통과했습니다. 테스트 visibility/복구 scan 조건은 운영과 다릅니다. 아래 코드는 목표 예시이며 실제 설정은 factory 코드가 기준입니다. Redis Streams는 SSE 이벤트용이며 Celery 브로커 큐와 별도 역할입니다.
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

## 3. 단계 내부 진행률

runner는 실행 중인 provider의 `StageContext.report_progress`에 async callback을 연결한다. provider는 callback을 await하며 실행 후 보관해 사용하지 않는다. 기존 직접 생성자는 callback을 생략할 수 있다.

값은 bool 제외 정수0~99이며 100은 결과 검증·DB 완료 후 runner만 기록한다. 현재 RUNNING job/attempt, stage, active_attempt_id와 message/예약 generation이 일치하는 경우에만 증가시킨다. 반복·역행·취소/최종 상태·오래된 실행의 보고는 무변경 false다. 전체 진행률은 재시도에서도 감소하지 않는다.

동시 callback의 DB 기록과 이벤트 발행을 직렬화한다. DB commit 후 기존 Redis `payload` 이벤트를 발행하며 Redis 실패는 DB 상태를 되돌리지 않는다. DB 소유권·연결 장애는 InfrastructureUnavailable로 실행 경계에 전달된다.

Basic Pitch는 입력 준비20, 모델 실행70, 결과 검증85, 파일 저장95의 처리 이정표를 보고한다. 이 수치는 시간 비율이나 전사 정확도가 아니며, 결과 metadata 공개와 다음 단계 예약은 기존 runner 완료 transaction에서 수행한다.

## 4. 운영자 정체 작업 점검

`musicsheet-maintenance scan`/`fail-stalled`는 기존 PostgreSQL stage session의 job advisory lock을 재사용한다. 별도 orchestration이나 task namespace를 만들지 않는다. scan은 읽기 전용이고 종료는 필수 관측값5개와 정체 시간을 잠금 안에서 재검사한다. 상태 전이·attempt 종료·outbox 소비의 원자성 및 무변경 이유는 [Job 상태 계약](../domain/job-state.md#운영자-정체-작업-종료), 환경·exit code·명령은 [pipeline README](../../packages/pipeline/README.md)를 따른다. API의 cancel 요청과 worker가 없는 CANCEL_REQUESTED를 운영자가 명시적으로 CANCELED로 마무리하는 명령은 별도 동작이다.
