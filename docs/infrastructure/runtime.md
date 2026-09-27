# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`
> **관련 문서:** [docs/adr/004-python-313-runtime.md](../adr/004-python-313-runtime.md)
>
> **구현 상태:** Python 3.13 workspace와 공용 스키마 및 스토리지 기반이 구현 중입니다. API, worker, 모델별 의존성은 아직 구현되지 않았습니다.

---

## 1. 런타임 전략

- **Python 3.13 단일 표준 런타임:** ADR 004에 따라 API, Celery, CPU/GPU worker의 목표 런타임을 통일합니다.
- 현재 루트, `packages/common`, `packages/storage`가 Python `>=3.13,<3.14`를 요구합니다.
- API, Celery worker, AI 모델 의존성과 실행 모듈은 아직 저장소에 없습니다.
- 현재 workspace의 Python 3.13 호환성 검증은 공용 스키마와 스토리지 기반에 한정됩니다. Spotify Basic Pitch upstream 메타데이터는 Python 3.8–3.11을 분류하고 TensorFlow를 `<2.15.1`로 제한하므로, 해당 provider는 3.13 호환성을 별도로 해결하기 전까지 설치 가능하다고 간주하지 않습니다 ([공식 pyproject](https://github.com/spotify/basic-pitch/blob/main/pyproject.toml), [설치 안내](https://github.com/spotify/basic-pitch/blob/main/README.md)).

---

## 2. 현재 workspace 설정

저장소 루트에서 기본 Python 환경을 동기화합니다.

```bash
uv python install 3.13
uv sync
```

PyTorch CUDA 휠과 모델별 의존성은 현재 workspace 및 `uv.lock`에 포함되지 않았습니다. 모델 구현 시 지원 버전과 CUDA 조합을 확정한 뒤 재현 가능한 의존성 설정에 추가합니다.

---

## 3. 목표 서비스 실행 명령

아래 명령은 목표 모듈이 구현된 후 사용할 예시입니다. 현재 저장소에는 `apps.api` 및 `packages.pipeline`가 없어 실행되지 않습니다.

```bash
# 터미널 1: FastAPI 게이트웨이
uv run --python 3.13 uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 터미널 2: CPU Worker
uv run --python 3.13 celery -A packages.pipeline.workers.celery_app worker -Q cpu_io_queue,cpu_render_queue -c 4 -l info

# 터미널 3: GPU AI Worker
uv run --python 3.13 celery -A packages.pipeline.workers.celery_app worker -Q gpu_ai_queue -c 1 -l info
```
