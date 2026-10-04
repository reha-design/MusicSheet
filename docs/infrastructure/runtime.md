# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`
> **관련 문서:** [docs/adr/004-python-313-runtime.md](../adr/004-python-313-runtime.md)
>
> **구현 상태:** Python 3.13 workspace·공용 스키마·LocalStorage·독립 FastAPI 프로젝트·Celery 단계 실행기와 격리된 Basic Pitch Python 3.12 worker가 있습니다. Basic Pitch 제품 provider 연결은 W04 계획 중이며 다른 모델 실행환경은 아직 구현되지 않았습니다.

---

## 1. 런타임 전략

- **백엔드/workspace 표준:** ADR 004에 따라 루트 프로젝트, 공용 패키지, API·파이프라인 조정 및 일반 백엔드 작업의 목표 런타임을 Python 3.13으로 둡니다.
- 현재 루트, `packages/common`, `packages/storage`, `packages/pipeline`, `services/api`가 Python `>=3.13,<3.14`를 요구합니다.
- API와 Celery orchestration은 구현됐고 테스트 provider를 사용하는 Linux 실제 worker 검증을 완료했습니다 ([후속 검증 보고서](../reports/celery-live-verification-report.md)). Basic Pitch worker는 독립 Python 3.12 + ONNX CPU 환경에서 Windows smoke 검증을 마쳤으며, 상세 결과는 [Basic Pitch worker smoke 보고서](../reports/basic-pitch-worker-smoke-report.md)에 있습니다. 두 증거를 Linux 모델 검증으로 합쳐 해석하지 않습니다.
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

## 3. 구현된 서비스 실행 명령

아래 명령은 저장소 루트에서 사용합니다. DB migration과 연결 환경 설정은 서비스 README를 먼저 확인합니다. 실제 Celery worker는 Linux/WSL2 환경에서 실행하고 Windows에서는 단위·eager 검증을 수행합니다. 제품 provider가 미구성인 단계는 명시적 실패하며 이 명령만으로 실제 모델이나 전체 pipeline 지원을 주장하지 않습니다.

```bash
# 터미널 1: FastAPI 게이트웨이
uv run --project services/api --python 3.13 musicsheet-api

# 터미널 2: CPU Worker
uv run --project . --python 3.13 celery -A musicsheet_pipeline.celery_app worker -Q cpu_io_queue,cpu_render_queue -c 4 -l info

# 터미널 3: AI 단계 큐 (큐 이름은 GPU 모델 설치나 사용을 의미하지 않음)
uv run --project . --python 3.13 celery -A musicsheet_pipeline.celery_app worker -Q gpu_ai_queue -c 1 -l info
```

모델별 실행환경은 해당 모델의 호환성 검증과 ADR을 따릅니다. Basic Pitch 독립 설치·실행 명령은 [worker README](../../services/ml/basic-pitch-worker/README.md), 제품 연결은 [W04 승인 설계](../superpowers/specs/2026-10-04-basic-pitch-pipeline-design.md)와 [실행 계획](../plans/basic-pitch-pipeline-implementation-plan.md)을 따릅니다. W04의 절대 경로 설정과 probe는 계획 단계이며 아직 실행 가능한 제품 기능이 아닙니다.
