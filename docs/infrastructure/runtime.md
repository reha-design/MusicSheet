# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`
> **관련 문서:** [docs/adr/004-python-313-runtime.md](../adr/004-python-313-runtime.md)
>
> **구현 상태:** Python 3.13 workspace, 공용 스키마, 스토리지 기반 및 격리된 Basic Pitch Python 3.12 PoC worker가 있습니다. API/Celery 연동과 다른 모델 실행환경은 아직 구현되지 않았습니다.

---

## 1. 런타임 전략

- **백엔드/workspace 표준:** ADR 004에 따라 루트 프로젝트, 공용 패키지, API·파이프라인 조정 및 일반 백엔드 작업의 목표 런타임을 Python 3.13으로 둡니다.
- 현재 루트, `packages/common`, `packages/storage`가 Python `>=3.13,<3.14`를 요구합니다.
- API와 Celery orchestration은 아직 저장소에 없습니다. Python 3.13 공용 스키마/스토리지 검증 외에 Basic Pitch worker는 독립 Python 3.12 + ONNX CPU 환경에서 smoke 검증을 마쳤으며, 상세 결과는 [Basic Pitch worker smoke 보고서](../reports/basic-pitch-worker-smoke-report.md)에 있습니다.
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

## 3. 목표 서비스 실행 명령

아래는 Python 3.13 백엔드 workspace의 목표 명령입니다. 현재 저장소에는 `apps.api` 및 `packages.pipeline`가 없어 실행되지 않습니다. AI 모델 worker는 호환성 그룹의 독립 프로젝트에서 별도로 실행하며, 이 예시의 Python 3.13 worker 명령만으로 모델 호환성을 주장하지 않습니다.

```bash
# 터미널 1: FastAPI 게이트웨이
uv run --python 3.13 uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 터미널 2: CPU Worker
uv run --python 3.13 celery -A packages.pipeline.workers.celery_app worker -Q cpu_io_queue,cpu_render_queue -c 4 -l info

# 터미널 3: 백엔드 workspace와 호환성이 확인된 GPU worker만 실행
uv run --python 3.13 celery -A packages.pipeline.workers.celery_app worker -Q gpu_ai_queue -c 1 -l info
```

모델별 AI worker의 프로젝트 경로, Python 버전, 프레임워크 및 실행 명령은 해당 모델의 호환성 검증과 ADR/설계 승인을 마친 뒤 추가합니다. Basic Pitch 제안은 [독립 worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md)를 따릅니다.
