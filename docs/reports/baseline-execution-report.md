# MusicSheet 베이스라인 구축 작업 결과보고서 (Commit 단위)

> **문서 번호:** REPORT-20260925-01  
> **작성 일자:** 2026-09-25  
> **작성자:** Senior ML/Backend Architect  
> **프로젝트:** MusicSheet (AI Audio-to-Score Transcription Pipeline)  
> **전체 상태:** 14/14 테스트 통과 (100% PASSED, 경고 0건)

---

## 1. 개요 (Executive Summary)

본 보고서는 MusicSheet 시스템의 **초기 베이스라인 3단계(uv 워크스페이스 ➔ Docker Compose 인프라 ➔ Core Pydantic 스키마)** 구축 과정을 커밋(Commit) 단위로 상세히 기록한 공식 결과보고서다.

모든 작업은 **TDD(테스트 주도 개발)** 원칙에 따라 사전 검증 테스트를 작성하고, 실제 환경에서 실행 확인(`PASSED`)한 후 **독립적인 Atomic Commit**으로 안전하게 기록되었다.

```text
[Commit 1: 07bfe66] docs: initialize project specification, architecture docs, and README
         │
         ▼
[Commit 2: ab84a4e] build: initialize uv workspace with Python 3.12 (Task 1)
         │
         ▼
[Commit 3: ba8e8c4] feat(infra): add docker-compose configuration for postgresql and redis (Task 2)
         │
         ▼
[Commit 4: bc8d249] feat(common): implement core pydantic schemas and unit tests (Task 3)
```

---

## 2. 커밋별 작업 상세 보고

### Commit 1: `07bfe66` (설계 및 사양서 모듈화)

- **커밋 해시:** `07bfe665c20e7f3b132ee9d43d18f4fe682c7dce`
- **커밋 메시지:** `docs: initialize project specification, architecture docs, and README`
- **변경 사항:** 28개 파일 생성, 1,417줄 추가

#### 작업 내용
1. **AI Agent 친화적 Context Router 구축:**
   - 단일 거대 문서의 토큰 낭비와 환각을 방지하기 위해 [docs/main_spec.md](../main_spec.md)를 Router 및 Agent Contract로 수립.
   - 세부 도메인을 `architecture/`, `domain/`, `ai/`, `backend/`, `infrastructure/`, `adr/`로 완전 분리.
2. **16대 핵심 엔지니어링 의사결정 반영:**
   - Worker 물리적 분리 (CPU I/O, GPU AI, CPU Render)
   - Celery 멱등성 및 SHA-256 아티팩트 캐싱
   - Redis Streams (`XADD`) 기반 재생 가능한(Replayable) SSE 스트리밍 채택
   - 3계층 Note Schema (`Raw` ➔ `Clean` ➔ `Score`)
   - Python 3.12 기본 런타임 및 레거시 모델 격리 전략
3. **프로젝트 안내서 및 Git 베이스라인:**
   - [README.md](../../README.md) 작성 및 대용량 가중치/오디오 제외 [.gitignore](../../.gitignore) 구성.

---

### Commit 2: `ab84a4e` (Task 1: uv Workspace & Python 3.12)

- **커밋 해시:** `ab84a4eb17d060d89c87a9f81a9363ec904e83b0`
- **커밋 메시지:** `build: initialize uv workspace with Python 3.12`
- **변경 사항:** 4개 파일 생성, 116줄 추가

#### 작업 내용
1. **Python 3.12 런타임 고정:**
   - [.python-version](../../.python-version)에 `3.12` 명시.
   - [pyproject.toml](../../pyproject.toml)에 `requires-python = ">=3.12,<3.13"` 선언.
2. **Astral `uv` 워크스페이스 세팅:**
   - `uv` 가상환경(`.venv`) 생성 및 단일 락파일 [uv.lock](../../uv.lock) 생성/추적.
   - 루트 환경을 AI 패키지로 오염시키지 않고 최소 개발 의존성(`pytest>=8.0.0`)만 격리 설치.

#### 검증 및 테스트 결과
- **테스트 파일:** [tests/test_project_baseline.py](../../tests/test_project_baseline.py)
  - `test_python_runtime_version`: 활성 런타임이 CPython 3.12.13인지 검증 (`PASSED`)
  - `test_project_root_structure`: `pyproject.toml` 및 Python 3.12 제약 선언 여부 검증 (`PASSED`)
- **실행 명령:** `uv run pytest tests/test_project_baseline.py` ➔ **2 passed**

---

### Commit 3: `ba8e8c4` (Task 2: Docker Compose 인프라)

- **커밋 해시:** `ba8e8c4257b9fd60cce428cfdd5c0291a05ea325`
- **커밋 메시지:** `feat(infra): add docker-compose configuration for postgresql and redis`
- **변경 사항:** 3개 파일 생성, 128줄 추가

#### 작업 내용
1. **Docker Compose 명세 ([docker/docker-compose.yml](../../docker/docker-compose.yml)):**
   - Compose Spec v2+ 준수 (경고 유발하는 구형 `version` 속성 배제).
   - **PostgreSQL 16 (`postgres:16-alpine`)**: 영속 볼륨(`postgres_data`), `pg_isready` 헬스체크 설정 (포트 5432).
   - **Redis 7 (`redis:7-alpine`)**: AOF 영속성(`--appendonly yes`), 영속 볼륨(`redis_data`), `redis-cli ping` 헬스체크 설정 (포트 6379).
2. **환경변수 템플릿 ([.env.example](../../.env.example)):**
   - 애플리케이션 환경, DB 접속 URL, Redis 및 Celery Broker/Backend URL, 로컬 스토리지 경로 표준화.

#### 검증 및 테스트 결과
- **테스트 파일:** [tests/infra/test_docker_compose.py](../../tests/infra/test_docker_compose.py)
  - `test_compose_files_exist`: 파일 물리 존재 검증 (`PASSED`)
  - `test_env_example_contains_required_keys`: 필수 환경변수 키 12종 선언 검증 (`PASSED`)
  - `test_docker_compose_config_validation`: `docker compose config --format json` 호출을 통한 서비스/볼륨/헬스체크 구문 검증 (`PASSED`)
- **실행 명령:** `uv run pytest tests/infra/test_docker_compose.py` ➔ **3 passed**

---

### Commit 4: `bc8d249` (Task 3: packages/common 도메인 스키마)

- **커밋 해시:** `bc8d249b2f8a6cbbaa7ffcf8ec80c34a60e01b68`
- **커밋 메시지:** `feat(common): implement core pydantic schemas and unit tests`
- **변경 사항:** 12개 파일 수정/생성, 577줄 추가, 2줄 삭제

#### 작업 내용
1. **워크스페이스 패키지 등록:**
   - `packages/common/pyproject.toml` 작성 및 루트 `pyproject.toml`에 `musicsheet-common` 워크스페이스 멤버로 연동.
2. **도메인 Pydantic v2 스키마 구현 ([packages/common/musicsheet_common/schemas/](../../packages/common/musicsheet_common/schemas/)):**
   - **`job_state.py`**: `JobStatus`(7종 수명주기)와 `PipelineStage`(6종 파이프라인 단계) 분리, `JobProgressEvent` (Timezone-aware UTC 적용).
   - **`artifacts.py`**: `ArtifactRole`(11종 역할), 64자 SHA-256 해시 검증을 갖춘 `ArtifactRef`.
   - **`note_events.py`**:
     - `RawNoteEvent`: 단일 진실 소스(`onset_sec`, `offset_sec`) 및 동적 `duration_sec` 계산 프로퍼티, MIDI pitch 0~127 허용.
     - `ConfidenceScores`: 다단계 신뢰도(AMT, 분리 품질, 리듬 적합도, 종합).
     - `CleanNoteEvent`: 필터링 플래그(`flags`)를 포함한 정제 노트.
     - `PedalEvent`: 서스테인 페달(CC64) 제어 이벤트 분리.
   - **`score_model.py`**: `ScoreNote` (유리수 기반 박자/길이 표기, Treble/Bass `staff`, `voice`, `hand`, `enharmonic_spelling`).
   - **`beats.py`**: `TempoEvent`, `MeterEvent`, 루바토 대응 `BeatGrid`.
   - **`quality.py`**: `SeparationQuality` (피아노 솔로 감지 및 Bypass 플래그).

#### 검증 및 테스트 결과
- **테스트 파일:** [tests/unit/test_schemas.py](../../tests/unit/test_schemas.py)
  - `test_job_status_and_pipeline_stage_enums`: Enum 정의 및 중복 배제 (`PASSED`)
  - `test_job_progress_event_validation`: 진행률 0~100 유효 범위 (`PASSED`)
  - `test_artifact_ref_validation`: 64자 SHA-256 해시 및 아티팩트 역할 검증 (`PASSED`)
  - `test_raw_note_event_duration_and_pitch`: 피치 0~127 및 `duration_sec` 동적 계산 (`PASSED`)
  - `test_clean_note_event_and_confidence_scores`: 신뢰도 0.0~1.0 및 플래그 검증 (`PASSED`)
  - `test_pedal_event`: 서스테인 페달 이벤트 유효성 (`PASSED`)
  - `test_score_note_rational_representation`: 유리수 박자/길이 및 Staff 1/2 제약 (`PASSED`)
  - `test_beat_grid_and_tempo_map`: 템포 맵 및 미터 맵 다중 이벤트 검증 (`PASSED`)
  - `test_separation_quality_and_solo_bypass`: 솔로 피아노 바이패스 플래그 (`PASSED`)
- **실행 명령:** `uv run pytest tests/unit/test_schemas.py` ➔ **9 passed**

---

## 3. 누적 테스트 검증 매트릭스 (Test Matrix)

| 테스트 스위트 (Test Suite) | 파일 경로 | 테스트 항목 수 | 실행 결과 | 경고 |
| :--- | :--- | :---: | :---: | :---: |
| **Project Baseline** | `tests/test_project_baseline.py` | 2 | **PASSED** | 0 |
| **Docker Compose Spec** | `tests/infra/test_docker_compose.py` | 3 | **PASSED** | 0 |
| **Core Domain Schemas**| `tests/unit/test_schemas.py` | 9 | **PASSED** | 0 |
| **총계 (Total)** | **전체 3개 스위트** | **14** | **100% PASSED (0.22s)** | **0** |

---

## 4. Git 커밋 이력 요약

```bash
* bc8d249 (HEAD -> master) feat(common): implement core pydantic schemas and unit tests
* ba8e8c4 feat(infra): add docker-compose configuration for postgresql and redis
* ab84a4e build: initialize uv workspace with Python 3.12
* 07bfe66 docs: initialize project specification, architecture docs, and README
```

---

## 5. 다음 마일스톤 제안 (Next Milestone)

초기 베이스라인 3단계가 100% 완결되었으므로, 다음 단계는 **서비스 및 어댑터 구현 계층**으로 진입합니다:

1. **`packages/storage` 구현:**
   - [docs/architecture/storage.md](../architecture/storage.md)에 따른 `LocalStorage` 어댑터 구현 (`put`, `open_read`, `materialize`)
2. **`apps/api` 스캐폴딩:**
   - [docs/backend/api.md](../backend/api.md) 및 [docs/infrastructure/health-check.md](../infrastructure/health-check.md)에 따른 FastAPI 게이트웨이 및 `/health` 3단계 진단 엔드포인트 구축
