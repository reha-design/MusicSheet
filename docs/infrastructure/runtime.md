# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`
> **관련 문서:** [docs/adr/001-python-runtime.md](../adr/001-python-runtime.md)
>
> **구현 상태:** Python 3.12 workspace만 현재 구현되어 있습니다. API와 worker, 모델별 의존성은 아직 구현되지 않았습니다.

---

## 1. 런타임 전략

- **Python 3.12 단일 표준 런타임:** 최신 ADR 001에 따라 API, Celery, CPU/GPU worker의 목표 런타임을 통일합니다.
- 현재 루트와 `packages/common`이 Python `>=3.12,<3.13`을 요구합니다.
- API, Celery worker, AI 모델 의존성과 실행 모듈은 아직 저장소에 없습니다.

---

## 2. 현재 workspace 설정

저장소 루트에서 기본 Python 환경을 동기화합니다.

```bash
uv python install 3.12
uv sync
```

PyTorch CUDA 휠과 모델별 의존성은 현재 workspace 및 `uv.lock`에 포함되지 않았습니다. 모델 구현 시 지원 버전과 CUDA 조합을 확정한 뒤 재현 가능한 의존성 설정에 추가합니다.

---

## 3. 목표 서비스 실행 명령

아래 명령은 목표 모듈이 구현된 후 사용할 예시입니다. 현재 저장소에는 `apps.api` 및 `packages.pipeline`가 없어 실행되지 않습니다.

```bash
# 터미널 1: FastAPI 게이트웨이
uv run --python 3.12 uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 터미널 2: CPU Worker
uv run --python 3.12 celery -A packages.pipeline.workers.celery_app worker -Q cpu_io_queue,cpu_render_queue -c 4 -l info

# 터미널 3: GPU AI Worker
uv run --python 3.12 celery -A packages.pipeline.workers.celery_app worker -Q gpu_ai_queue -c 1 -l info
```
