# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`
> **관련 문서:** [docs/adr/004-python-313-runtime.md](../adr/004-python-313-runtime.md)
>
> **구현 상태:** Python 3.13 workspace와 FastAPI/Celery W03 orchestration이 있습니다. Basic Pitch Python 3.12 worker는 독립 PoC이고 product pipeline에 연결되지 않았습니다. W04–W08의 실제 stage handler와 모델 런타임은 아직 구현 범위 밖입니다.

---

## 1. 런타임 전략

- **백엔드/workspace 표준:** ADR 004에 따라 루트 프로젝트, 공용 패키지, API·파이프라인 조정 및 일반 백엔드 작업의 목표 런타임을 Python 3.13으로 둡니다.
- 현재 루트, `packages/common`, `packages/storage`가 Python `>=3.13,<3.14`를 요구합니다.
- API는 `services/api`의 독립 Python 3.13 uv 프로젝트이고 Celery orchestration은 `services/api/src/musicsheet_api/pipeline/`에 있습니다. FastAPI API process와 Celery workers는 분리 실행합니다. Basic Pitch worker는 독립 Python 3.12 + ONNX CPU PoC이며, 상세 결과는 [Basic Pitch worker smoke 보고서](../reports/basic-pitch-worker-smoke-report.md)에 있습니다.
- **모델 추론 런타임은 호환성 그룹별로 선택:** 모델 의존성이 Python/OS/native library/framework/CUDA 조합에서 호환되면 같은 독립 AI 프로젝트를 공유할 수 있습니다. 검증되지 않은 조합을 한 환경으로 단정하지 않으며, 모델마다 무조건 환경 하나씩을 만들지도 않습니다.
- 모델 추론이 백엔드와 다른 Python 또는 native dependency를 요구하면 별도 uv 프로젝트·lockfile·`.venv`에서 실행하고 파일/버전 지정 JSON 또는 명시된 프로세스 계약으로 연결합니다. AI 프로젝트는 루트 uv workspace 멤버가 아니므로 백엔드 의존성을 오염시키지 않습니다. ADR 004의 런타임 범위 예외는 구현 전에 별도 ADR로 명시합니다.
- Spotify Basic Pitch PR [#201](https://github.com/spotify/basic-pitch/pull/201)의 미병합 Python 3.12 dependency marker를 고정한 격리 worker는 Windows에서 독립 설치 및 실제 ONNX CPU 추론을 검증했습니다. 이 저장소의 PoC 결과는 upstream 공식 지원이나 제품 default provider 채택을 뜻하지 않으며, root Python 3.13 workspace와 API/Celery는 연결되지 않았습니다 ([Basic Pitch smoke 보고서](../reports/basic-pitch-worker-smoke-report.md), [worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md)).
- uv 환경 분리는 패키지와 프로세스를 분리할 뿐 호스트의 GPU, GPU 메모리, CUDA 드라이버 및 CPU를 격리하지 않습니다. GPU 동시성은 worker scheduler가 제어해야 합니다.

---

## 2. 현재 workspace 설정

저장소 루트에서 기본 Python 환경을 동기화합니다.

```bash
uv python install 3.13
uv sync
```

PyTorch CUDA 휠과 모델별 의존성은 현재 workspace 및 `uv.lock`에 포함되지 않았습니다. 모델 구현 시 지원 버전과 CUDA 조합을 확정한 뒤 재현 가능한 의존성 설정에 추가합니다.

---

## 3. API와 오케스트레이션 worker 실행

아래 명령은 `services/api`에서 실행합니다. Worker를 시작하기 전에 `DATABASE_URL`을 설정하고 `musicsheet-migrate`로 v1/v2 migration을 명시적으로 적용합니다. 기본 설정은 `CELERY_BROKER_URL=redis://localhost:6379/0`, `CELERY_RESULT_BACKEND=redis://localhost:6379/1`, `REDIS_URL=redis://localhost:6379/2`, `CELERY_VISIBILITY_TIMEOUT=3600`초입니다. Visibility timeout을 늘리면 stale-job recovery threshold도 자동으로 두 배로 늘어납니다.

```powershell
# services/api에서 실행
uv sync --locked --python 3.13
uv run --locked --python 3.13 musicsheet-migrate

# 터미널 1: FastAPI
uv run --locked --python 3.13 musicsheet-api

# 터미널 2: CPU/I/O queue, concurrency 4 (권장 범위 4–8)
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q cpu_io_queue -c 4 -l info

# 터미널 3: GPU/AI queue, concurrency 1
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q gpu_ai_queue -c 1 -l info

# 터미널 4: CPU/render queue, concurrency 2 (권장 범위 2–4)
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q cpu_render_queue -c 2 -l info
```

`services/api/src/musicsheet_api/pipeline/tasks.py`는 stage orchestration만 수행합니다. 아직 없는 실제 처리 핸들러는 `STAGE_NOT_CONFIGURED`로 종료되며, 이 worker 명령만으로 Basic Pitch/다른 모델 지원을 의미하지 않습니다. 모델별 AI worker의 프로젝트 경로, Python 버전, framework 및 실행 명령은 별도 호환성 검증과 ADR/설계 승인을 마친 뒤 추가합니다. Basic Pitch 제안은 [독립 worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md)를 따릅니다.
