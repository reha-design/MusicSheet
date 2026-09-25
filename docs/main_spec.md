# MusicSheet Main Specification (Router & Agent Contract)

이 문서는 MusicSheet 프로젝트 스펙의 **진입점(Router)**이자 **AI Agent 작업 규약(Agent Contract)**이다.

AI Agent는 작업 시작 시 반드시 이 문서를 먼저 읽고, **현재 작업과 관련된 세부 Canonical Spec(2~4개)만 선택적으로 로드**하여 작업한다.

---

## 1. Agent Instructions & 작업 규약

1. **단일 진입점:** 모든 에이전트 작업은 `docs/main_spec.md`에서 시작한다.
2. **Context Routing:** 전체 문서를 한꺼번에 로드하지 않고, [Agent Routing Rules](#2-agent-routing-rules)에 따라 필요한 Canonical Spec만 읽는다.
3. **Spec 우선 원칙:** 코드와 Spec이 충돌할 경우 Spec을 단일 진실 소스(Single Source of Truth)로 인정한다.
4. **선 Spec 갱신, 후 구현:** 아키텍처나 스키마 변경이 필요한 경우, 코드를 수정하기 전에 관련 Spec 문서를 먼저 갱신한다.
5. **단일 책임(Canonical Owner):** 하나의 규칙은 오직 하나의 문서에만 상세 정의하며, 다른 문서에서는 링크로 참조한다.

---

## 2. Agent Routing Rules (작업별 필수 로드 문서)

| 작업 유형 (Task Type) | 필수 로드 문서 (Primary Specs) | 필요 시 참조 문서 (Secondary Specs) |
| :--- | :--- | :--- |
| **API / Gateway 개발** | `docs/backend/api.md`<br>`docs/domain/job-state.md`<br>`docs/domain/artifacts.md` | `docs/backend/redis-streams.md`<br>`docs/architecture/job-pipeline.md` |
| **음원 분리 (Separation) 개발** | `docs/ai/separation.md`<br>`docs/ai/model-adapters.md`<br>`docs/domain/artifacts.md` | `docs/architecture/job-pipeline.md` |
| **피아노 전사 (AMT) 개발** | `docs/ai/transcription.md`<br>`docs/ai/model-adapters.md`<br>`docs/domain/note-events.md` | `docs/infrastructure/runtime.md` |
| **리듬 & 퀀타이즈 개발** | `docs/ai/rhythm.md`<br>`docs/ai/quantization.md`<br>`docs/domain/note-events.md`<br>`docs/domain/score-model.md` | `docs/ai/model-adapters.md` |
| **악보 렌더링 (Score/PDF)** | `docs/domain/score-model.md`<br>`docs/ai/model-adapters.md`<br>`docs/domain/artifacts.md` | `docs/infrastructure/health-check.md` |
| **Celery 워커 / 오케스트레이션** | `docs/backend/celery.md`<br>`docs/architecture/job-pipeline.md`<br>`docs/domain/job-state.md` | `docs/backend/redis-streams.md` |
| **스토리지 & 아티팩트 관리** | `docs/architecture/storage.md`<br>`docs/domain/artifacts.md` | `docs/domain/job-state.md` |
| **인프라 / 배포 / 헬스체크** | `docs/infrastructure/runtime.md`<br>`docs/infrastructure/health-check.md`<br>`docs/infrastructure/docker.md` | `docs/backend/database.md` |

---

## 3. Canonical Specs 인덱스

### Architecture
- **전체 시스템 구조:** [docs/architecture/system.md](./architecture/system.md)
  - 웹, API, DB, 큐, 워커의 전체 물리적 배치도 및 흐름
- **작업 파이프라인 & 큐 라우팅:** [docs/architecture/job-pipeline.md](./architecture/job-pipeline.md)
  - CPU Worker Queue와 GPU Worker Queue의 분리 및 Stage별 처리 규칙
- **스토리지 추상화:** [docs/architecture/storage.md](./architecture/storage.md)
  - LocalStorage / S3Storage 추상화 및 `outputs/{job_id}/` 디렉터리 레이아웃

### Domain Models
- **Job 상태 머신:** [docs/domain/job-state.md](./domain/job-state.md)
  - `JobStatus`(수명주기)와 `PipelineStage`(단계) 분리, `stage_attempts` 테이블
- **아티팩트 규격:** [docs/domain/artifacts.md](./domain/artifacts.md)
  - `ArtifactRef`, `ArtifactRole` 정의, SHA-256 캐싱 및 멱등성
- **노트 이벤트 스키마:** [docs/domain/note-events.md](./domain/note-events.md)
  - `RawNoteEvent` ➔ `CleanNoteEvent` ➔ `ScoreNote` 3계층 분리 및 `PedalEvent`
- **악보 모델:** [docs/domain/score-model.md](./domain/score-model.md)
  - Rational 박자/길이, Staff/Voice/Hand 분리, 딴이름한소리(Enharmonic)

### AI Pipeline
- **음원 분리 (Source Separation):** [docs/ai/separation.md](./ai/separation.md)
  - Demucs v4 (`htdemucs_6s`), `SeparationQuality` 점수, Solo Piano Bypass 로직
- **음악 전사 (AMT):** [docs/ai/transcription.md](./ai/transcription.md)
  - ByteDance Piano AMT vs Basic Pitch 비교, 모델별 요구 Sample Rate
- **비트 및 템포 분석:** [docs/ai/rhythm.md](./ai/rhythm.md)
  - `BeatProvider` 인터페이스, 동적 `TempoEvent`/`MeterEvent`, 라이선스 안전 대안
- **스마트 퀀타이즈:** [docs/ai/quantization.md](./ai/quantization.md)
  - 비용 함수 기반 퀀타이즈 ($Cost = w_t E_{timing} + w_c E_{complexity} + w_v E_{voice}$)
- **모델 어댑터 규약:** [docs/ai/model-adapters.md](./ai/model-adapters.md)
  - `AudioSeparator`, `AMTProvider`, `BeatProvider`, `ScoreRenderer` 추상 클래스

### Backend
- **FastAPI 게이트웨이:** [docs/backend/api.md](./backend/api.md)
  - REST 엔드포인트 명세 및 SSE 스트리밍
- **Celery 워커 오케스트레이션:** [docs/backend/celery.md](./backend/celery.md)
  - 큐 설정, Task Chaining, 멱등성 보장
- **Redis Streams 이벤트 버스:** [docs/backend/redis-streams.md](./backend/redis-streams.md)
  - `XADD`, Consumer Groups, `Last-Event-ID` 기반 재접속 복원
- **데이터베이스:** [docs/backend/database.md](./backend/database.md)
  - PostgreSQL 테이블 DDL, 인덱스, 마이그레이션 정책

### Infrastructure
- **Python 런타임 전략:** [docs/infrastructure/runtime.md](./infrastructure/runtime.md)
  - Python 3.12 기본 런타임 + 격리된 Python 3.10 레거시 런타임, `uv` 가이드
- **컨테이너 환경:** [docs/infrastructure/docker.md](./infrastructure/docker.md)
  - `docker-compose.yml` 및 로컬 개발용 서비스 구성
- **헬스 체크 & 관측성:** [docs/infrastructure/health-check.md](./infrastructure/health-check.md)
  - `/health/live`, `/health/ready`, `/health/detail`, 가중치 사전 검증

### ADR (Architecture Decision Records)
- [001: Python 3.12 기본 및 레거시 런타임 격리](./adr/001-python-runtime.md)
- [002: Replayable SSE를 위한 Redis Streams 채택](./adr/002-redis-streams.md)
- [003: ArtifactRef 기반 Storage 추상화](./adr/003-storage-abstraction.md)

### Reports (작업 결과보고서)
- [01: 베이스라인 구축 작업 결과보고서 (Task 1~3)](./reports/baseline-execution-report.md)
