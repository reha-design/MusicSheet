# Architecture Spec: System Overview

> **Canonical Owner:** `docs/architecture/system.md`  
> **관련 문서:** [docs/architecture/job-pipeline.md](./job-pipeline.md), [docs/backend/api.md](../backend/api.md)
>
> **구현 상태:** 목표 시스템 구성입니다. 현재 구현된 것은 공용 스키마와 PostgreSQL·Redis 개발용 Compose까지이며 API·워커·저장소·웹 앱은 아직 없습니다.

---

## 1. 목표 시스템 구성

```text
┌─────────────────────────────┐
│ Next.js Web (planned)       │
└──────────────┬──────────────┘
               │ REST / SSE
               ▼
┌─────────────────────────────┐       ┌──────────────────────┐
│ FastAPI API (planned)       │◄─────►│ PostgreSQL           │
└──────────┬──────────────────┘       │ job state / artifacts│
           │                          └──────────────────────┘
           │ task dispatch
           ▼
┌───────────────────────────────────────────┐
│ Redis 7 (one server, separate functions)  │
│ DB 0: Celery broker via Kombu transport   │
│       (Redis-backed task queues)          │
│ DB 1: Celery result backend               │
│ DB 2: application Redis Streams for SSE   │
└─────────────────────┬─────────────────────┘
                      │
             ┌────────┴────────┐
             ▼                 ▼
      CPU workers          GPU workers
       (planned)            (planned)
             └────────┬────────┘
                      ▼
            ArtifactStorage (planned)
```

Celery task queue와 애플리케이션 이벤트 Stream은 같은 Redis 서버에 둘 수 있지만 서로 다른 기능입니다. Celery/Kombu Redis transport의 task queue가 이 문서의 SSE Stream을 사용하지 않습니다. 상세 설정은 [Redis 이벤트 명세](../backend/redis-streams.md)를 참조하세요.

---

## 2. 목표 컴포넌트 책임

| 컴포넌트 | 목표 기술 | 주 책임 |
| :--- | :--- | :--- |
| Frontend | Next.js, OSMD | 오디오/URL 입력, SSE 진행 표시, 악보 뷰어 |
| API Gateway | FastAPI, Python 3.12 | 작업 생성·조회·취소, SSE 중계, 헬스체크 |
| State DB | PostgreSQL 16 | 작업 상태, 단계 실행 이력, 아티팩트 메타데이터 |
| Task broker | Celery + Kombu Redis transport | CPU·GPU 큐 작업 전달 |
| Event store | 애플리케이션 Redis Streams | 제한된 SSE 이벤트 재생 |
| CPU/GPU workers | Celery, Python, PyTorch | 다운로드·전처리·AI·후처리·렌더링 |
| Artifact storage | LocalStorage (MVP), 이후 S3 | 중간 파일과 최종 산출물 저장 |
