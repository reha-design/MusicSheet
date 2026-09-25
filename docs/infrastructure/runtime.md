# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`  
> **관련 문서:** [docs/adr/001-python-runtime.md](../adr/001-python-runtime.md)

---

## 1. 런타임 표준화 전략 (Unified Runtime Strategy)

- **Python 3.12 단일 표준 런타임 채택:**
  - **대상 전체:** API Gateway, Celery Orchestrator, CPU Worker, GPU AI Worker(Demucs v4, ByteDance Piano AMT, Spotify Basic Pitch via ONNX).
  - **이유:**
    1. Python 3.10의 2026년 10월 EOL 대응 및 보안/유지보수 안정성 확보.
    2. ByteDance Piano AMT의 PyTorch 2.x 네이티브 실행 및 Basic Pitch의 `onnxruntime` 경량화로 레거시 격리 필요성 완전 소멸.
    3. 최신 MIR 고속 스택(`librosa 1.0+`, `NumPy 2.x`, 최신 PyTorch CUDA 12.1)의 성능 극대화.

---

## 2. Astral `uv` 표준 명령어

```bash
# 1. 표준 Python 3.12 설치
uv python install 3.12

# 2. 메인 가상환경 동기화
uv venv --python 3.12
uv sync

# 3. PyTorch CUDA 12.1 (RTX 3060 12GB 최적화) 설치
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 4. 서비스 기동 커맨드
# 터미널 1: FastAPI 게이트웨이
uv run --python 3.12 uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

# 터미널 2: CPU Worker (I/O, 비트분석, 악보 렌더링)
uv run --python 3.12 celery -A packages.pipeline.workers.celery_app worker -Q cpu_io_queue,cpu_render_queue -c 4 -l info

# 터미널 3: GPU AI Worker (Demucs 음원 분리, Piano AMT 전사)
uv run --python 3.12 celery -A packages.pipeline.workers.celery_app worker -Q gpu_ai_queue -c 1 -l info
```
