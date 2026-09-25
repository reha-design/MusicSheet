# MusicSheet Specification Redirect

> **안내:** MusicSheet의 공식 사양서는 AI Agent의 컨텍스트 최적화 및 도메인 라우팅을 위해 모듈화되었습니다.  
> 작업 시작 시 **[docs/main_spec.md](./main_spec.md)**를 진입점으로 사용하십시오.

---

## 진입점 바로가기

👉 **[MusicSheet Main Specification (Router & Agent Contract)](./main_spec.md)**

### 세부 도메인별 바로가기
- **시스템 전체 아키텍처:** [docs/architecture/system.md](./architecture/system.md)
- **작업 파이프라인 & 큐 라우팅:** [docs/architecture/job-pipeline.md](./architecture/job-pipeline.md)
- **스토리지 추상화:** [docs/architecture/storage.md](./architecture/storage.md)
- **Job 상태 머신:** [docs/domain/job-state.md](./domain/job-state.md)
- **아티팩트 규격:** [docs/domain/artifacts.md](./domain/artifacts.md)
- **노트 이벤트 스키마:** [docs/domain/note-events.md](./domain/note-events.md)
- **악보 모델:** [docs/domain/score-model.md](./domain/score-model.md)
- **음원 분리 (Demucs & QC):** [docs/ai/separation.md](./ai/separation.md)
- **음악 전사 (AMT):** [docs/ai/transcription.md](./ai/transcription.md)
- **비트 및 템포:** [docs/ai/rhythm.md](./ai/rhythm.md)
- **스마트 퀀타이즈:** [docs/ai/quantization.md](./ai/quantization.md)
- **모델 어댑터 규약:** [docs/ai/model-adapters.md](./ai/model-adapters.md)
- **FastAPI 게이트웨이:** [docs/backend/api.md](./backend/api.md)
- **Celery 오케스트레이션:** [docs/backend/celery.md](./backend/celery.md)
- **Redis Streams:** [docs/backend/redis-streams.md](./backend/redis-streams.md)
- **데이터베이스 (PostgreSQL):** [docs/backend/database.md](./backend/database.md)
- **Python 런타임 전략 (uv):** [docs/infrastructure/runtime.md](./infrastructure/runtime.md)
- **Docker 환경:** [docs/infrastructure/docker.md](./infrastructure/docker.md)
- **헬스 체크 & 프리페치:** [docs/infrastructure/health-check.md](./infrastructure/health-check.md)