# Infrastructure Spec: Python Runtime Strategy & uv Standard

> **Canonical Owner:** `docs/infrastructure/runtime.md`  
> **관련 문서:** [docs/adr/001-python-runtime.md](../adr/001-python-runtime.md)

---

## 1. 런타임 분리 전략 (Runtime Isolation)

- **기본 최신 런타임 (Python 3.12):**
  - 대상: API Gateway, Celery Orchestrator, Modern MIR Worker (`librosa 1.0+`, `NumPy 2.x`, `SciPy`, 최신 PyTorch).
  - 이유: Python 3.10의 2026년 10월 EOL 대응 및 최신 고속 MIR 스택 활용.
- **레거시 격리 런타임 (Python 3.10 / 3.11):**
  - 대상: 아카이빙된 구형 모델 `ByteDance Piano AMT` (`piano_transcription_inference`).
  - 패키지: `numpy==1.26.4` 등 검증된 휠 고정.
  - 실행: 메인 런타임을 오염시키지 않고 `uv run --python 3.10` 또는 격리 워커 프로세스로만 구동.

---

## 2. Astral `uv` 표준 명령어

```bash
# 1. 멀티 파이썬 설치
uv python install 3.12 3.10

# 2. 메인 가상환경 동기화
uv venv --python 3.12
uv sync

# 3. PyTorch CUDA 12.1 (RTX 3060 12GB 최적화) 설치
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 4. 서비스 기동 커맨드
uv run --python 3.12 uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
uv run --python 3.12 celery -A packages.pipeline.workers.celery_app worker -Q cpu_io_queue,cpu_render_queue -c 4 -l info
uv run --python 3.12 celery -A packages.pipeline.workers.celery_app worker -Q gpu_ai_queue -c 1 -l info
uv run --python 3.10 celery -A packages.pipeline.workers.legacy_amt_worker worker -Q legacy_amt_queue -c 1 -l info
```
