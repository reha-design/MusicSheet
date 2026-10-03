# MusicSheet Main Specification (Router & Agent Contract)

이 문서는 MusicSheet 프로젝트 스펙의 **진입점(Router)**이자 **AI Agent 작업 규약(Agent Contract)**이다.

AI Agent는 작업 시작 시 이 문서의 라우팅 규칙과 [현재 현황](./roadmap.md)을 확인하고, **현재 작업과 관련된 세부 Canonical Spec(2~4개)만 선택적으로 로드**한다. 토큰 사용을 줄이기 위해 전체 backlog는 다음 작업 선택 때만, 완료 색인은 이력 확인 때만 읽는다.

## 현재 구현 상태와 사양의 범위

현재 저장소에는 Python 3.13 uv workspace와 공용 Pydantic 스키마, `put`/`open_read`/`exists`/`delete`/`materialize`를 제공하는 LocalStorage, PostgreSQL·Redis용 Compose 설정, 그리고 별도 Python 3.12 + ONNX CPU 환경의 Basic Pitch PoC worker가 있습니다. Basic Pitch worker는 JSON/MIDI 결과를 생성하지만 API·Celery pipeline에는 연결되지 않았습니다. 별도 `services/api` FastAPI 프로젝트에는 인프라 health endpoint, 명시적 PostgreSQL migration 명령, 선택적 DB pool, 작업 생성·조회·진행률·취소 저장소, YouTube/업로드 등록·조회·취소 REST API, 아티팩트 목록·다운로드 API, Redis Streams 발행 모듈과 SSE 재생 API가 구현되어 있습니다. worker 자동 이벤트 발행, Celery orchestration, 기본 AI provider 선택, 프리페치 스크립트, 악보 렌더링, 웹 앱은 아직 구현되지 않았습니다.

이 문서 아래의 아키텍처·백엔드·AI·인프라 사양은 **목표 설계**입니다. 예제 명령과 인터페이스는 대응 구현이 저장소에 추가되기 전까지 실행 가능한 기능으로 간주하지 않습니다. 현재 실행 가능한 범위는 README를 기준으로 확인하고, 구현 결과는 작업 보고서에 기록합니다.

---

## 1. Agent Instructions & 작업 규약

1. **단일 진입점:** 모든 에이전트 작업은 `docs/main_spec.md`에서 시작한다.
2. **작업 현황:** [docs/roadmap.md](./roadmap.md)에서 진행 중인 작업과 다음 후보를 확인한다. backlog는 다음 작업을 선택할 때만 읽고, 완료 색인은 과거 결과 확인이 필요할 때만 읽는다.
3. **Context Routing:** 전체 문서를 한꺼번에 로드하지 않고, [Agent Routing Rules](#2-agent-routing-rules)에 따라 필요한 Canonical Spec만 읽는다.
4. **Spec 우선 원칙:** 코드와 Spec이 충돌할 경우 Spec을 단일 진실 소스(Single Source of Truth)로 인정한다.
5. **선 Spec 갱신, 후 구현:** 아키텍처나 스키마 변경이 필요한 경우, 코드를 수정하기 전에 관련 Spec 문서를 먼저 갱신한다.
6. **단일 책임(Canonical Owner):** 하나의 규칙은 오직 하나의 문서에만 상세 정의하며, 다른 문서에서는 링크로 참조한다.
7. **테스트 우선 검증 (TDD):** 구현 완료 후 반드시 자동화 테스트(`uv run pytest`)를 실행하여 `PASSED`를 확인한다. 테스트 실패 시 커밋하지 않는다.
8. **결과보고서 작성 (`docs/reports/`):** 각 Task가 완료될 때마다 [docs/reports/](./reports/) 디렉터리에 커밋 단위 작업 결과보고서를 작성하고, `main_spec.md`의 Reports 색인을 갱신한다.
9. **작업단위 원자적 커밋 (Atomic Commit):** 테스트 검증과 보고서 작성이 완료되면 관련 파일만 명시적으로 스테이징하여 Conventional Commit 규격으로 커밋한다.

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

### 개발 계획
- **현재 작업 및 다음 후보:** [docs/roadmap.md](./roadmap.md)
- **남은 작업 전체:** [docs/backlog.md](./backlog.md) (다음 작업 선택 시에만 로드)
- **완료 작업 색인:** [docs/completed-work.md](./completed-work.md) (이력 확인 시에만 로드)
- **저장소 및 uv 실행환경 구조 결정:** [모노레포 + 독립 uv 프로젝트](./plans/repository-and-uv-environment-structure-plan.md)
- **FastAPI 헬스 체크 구현 계획:** [독립 API 환경, readiness probes, host diagnostics](./plans/fastapi-health-check-implementation-plan.md)
- **PostgreSQL 작업 영속성 구현 계획:** [버전 migration, API DB pool, job repository](./plans/postgresql-job-persistence-implementation-plan.md)
- **Job REST API v1 구현 계획:** [YouTube/업로드 등록, 조회·취소, 아티팩트 API](./plans/job-rest-api-v1-implementation-plan.md) (계획 Revision 6 독립 리뷰 99/100 통과)
- **Job REST API v1 설계:** [등록과 처리 경계, 요청·데이터 흐름](./superpowers/specs/2026-09-27-job-rest-api-v1-design.md)
- **W02 Redis Streams 및 SSE 설계:** [이벤트 저장·재생, 연결 수명과 오류 계약](./superpowers/specs/2026-10-02-redis-streams-sse-design.md) (Revision 1, 사용자 설계 승인)
- **W02 Redis Streams 및 SSE 구현 계획:** [저장소·SSE·통합 검증의 단위별 실행 계획](./plans/redis-streams-sse-implementation-plan.md) (계획 Revision 2 100/100, 구현 최종 98/100, 실제 Redis 성공 경로 미검증)
- **W03 Celery 오케스트레이션 설계:** [등록·단계 전달·재시도·취소와 DB 실행 기록](./superpowers/specs/2026-10-03-celery-orchestration-design.md) (Revision 1, 사용자 설계 승인, Task1 저장소·Task2 실행 엔진·Task3 Celery/API 연결 완료)
- **W03 Celery 오케스트레이션 실행 계획:** [DB·runner·dispatch·통합 검증](./plans/celery-orchestration-implementation-plan.md) (Revision 3, 독립 계획 99점, 사용자 실행 승인, Task1·Task2·Task3 각 구현99점 완료)
- **Basic Pitch 독립 worker 구현 계획:** [Python 3.12 + ONNX worker 및 versioned JSON 계약](./plans/basic-pitch-isolated-worker-implementation-plan.md)
- **Basic Pitch worker 구현 기준 설계:** [백엔드·AI 실행환경 분리 설계](./superpowers/specs/2026-09-26-basic-pitch-worker-design.md)

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
  - `XADD`, 독립 `XREAD`, `Last-Event-ID` 기반 재접속 복원
- **데이터베이스:** [docs/backend/database.md](./backend/database.md)
  - PostgreSQL 테이블 DDL, 인덱스, 마이그레이션 정책

### Infrastructure
- **Python 런타임 전략:** [docs/infrastructure/runtime.md](./infrastructure/runtime.md)
  - Python 3.13 단일 표준 런타임 및 `uv` 가이드
- **컨테이너 환경:** [docs/infrastructure/docker.md](./infrastructure/docker.md)
  - `docker-compose.yml` 및 로컬 개발용 서비스 구성
- **헬스 체크 & 관측성:** [docs/infrastructure/health-check.md](./infrastructure/health-check.md)
  - `/health/live`, `/health/ready`, `/health/detail`, 가중치 사전 검증

### ADR (Architecture Decision Records)
- [001: Python 3.12 단일 표준 런타임 채택 (ADR 004로 대체)](./adr/001-python-runtime.md)
- [002: Replayable SSE를 위한 Redis Streams 채택](./adr/002-redis-streams.md)
- [003: ArtifactRef 기반 Storage 추상화](./adr/003-storage-abstraction.md)
- [004: Python 3.13 단일 표준 런타임 채택](./adr/004-python-313-runtime.md)
- [005: Basic Pitch worker 전용 Python 3.12 예외 (승인됨, PoC smoke 검증 완료)](./adr/005-basic-pitch-python-312-exception.md)

### Reports (작업 결과보고서)
- [현재 구현 현황 브리핑 (2026-10-01, 기준 `148040c`)](./reports/current-implementation-briefing.md)
- [01: 베이스라인 구축 작업 결과보고서 (Task 1~3)](./reports/baseline-execution-report.md)
- [02: 런타임 단일화 작업 결과보고서 (Python 3.12 일원화)](./reports/python-312-unification-report.md)
- [03: 문서 정합성 패치 보고서](./reports/documentation-alignment-report.md)
- [04: 작업목록 문서 단일화 보고서](./reports/worklist-consolidation-report.md)
- [05: Python 3.13 런타임 전환 및 스토리지 패키지 기반 구현 보고서](./reports/python-313-and-storage-scaffold-report.md)
- [06: Basic Pitch 평가 및 Python 3.13 호환성 보고서](./reports/basic-pitch-python-313-compatibility-report.md)
- [07: Basic Pitch Python 3.12 예외 ADR 제안 보고서](./reports/basic-pitch-runtime-exception-report.md)
- [08: TranscriptionResult 계약 구현 보고서](./reports/transcription-result-contract-report.md)
- [09: Basic Pitch worker Python 3.12 독립 환경 구성 보고서](./reports/basic-pitch-worker-environment-report.md)
- [10: Basic Pitch 입력 WAV 검사 및 note event 매핑 보고서](./reports/basic-pitch-audio-mapping-report.md)
- [11: Basic Pitch inference adapter 및 CLI 보고서](./reports/basic-pitch-cli-report.md)
- [12: Basic Pitch worker 실제 추론 smoke 보고서](./reports/basic-pitch-worker-smoke-report.md)
- [13: LocalStorage 아티팩트 어댑터 구현 보고서](./reports/local-storage-implementation-report.md)
- [14: FastAPI 헬스 체크 구현 보고서](./reports/fastapi-health-check-implementation-report.md)
- [15: PostgreSQL 마이그레이션 러너 구현 보고서](./reports/postgresql-migration-runner-implementation-report.md)
- [16: PostgreSQL API 풀 및 작업 저장소 구현 보고서](./reports/postgresql-api-pool-job-repository-implementation-report.md)
- [17: PostgreSQL 작업 영속성 통합 검증 보고서](./reports/postgresql-job-persistence-implementation-report.md)
- [18: YouTube 작업 등록 및 상태 조회 API 보고서](./reports/job-api-youtube-registration-report.md)
- [19: 오디오 업로드 및 아티팩트 메타데이터 트랜잭션 보고서](./reports/job-api-upload-report.md)
- [20: Job REST API v1 구현 보고서](./reports/job-rest-api-v1-implementation-report.md)
- [21: W02 Redis Streams 및 SSE 계획 리뷰 보고서](./reports/redis-streams-sse-planning-report.md)
- [22: W02 Redis 이벤트 저장소 보고서](./reports/redis-event-store-report.md)
- [23: W02 진행 이벤트 SSE API 보고서](./reports/job-sse-api-report.md)
- [24: W02 Redis Streams 및 SSE 구현 보고서](./reports/redis-streams-sse-implementation-report.md)
- [25: W03 Celery 오케스트레이션 설계 착수 보고서](./reports/celery-orchestration-design-report.md)
- [26: W03 Celery 오케스트레이션 계획 리뷰 보고서](./reports/celery-orchestration-planning-report.md)
- [27: W03 단계 실행·발행 대기 저장소 보고서](./reports/pipeline-persistence-report.md)
- [28: W03 provider 실행·무결성·취소·이벤트 보고서](./reports/pipeline-stage-runner-report.md)
- [29: W03 Celery·dispatcher·API 원자성 보고서](./reports/celery-dispatch-api-report.md)
