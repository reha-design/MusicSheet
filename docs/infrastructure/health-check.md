# Infrastructure Spec: Health Check & Model Prefetch

> **Canonical Owner:** `docs/infrastructure/health-check.md`  
> **관련 문서:** [docs/backend/api.md](../backend/api.md)

---

## 1. 3계층 Health Check 명세

| Endpoint | 역할 | 점검 대상 |
| :--- | :--- | :--- |
| `/health/live` | Liveness | FastAPI 이벤트 루프 생존 |
| `/health/ready` | Readiness | PostgreSQL 연결, Redis 연결, 스토리지 쓰기 권한, 필수 모델 체크포인트 로컬 존재 |
| `/health/detail` | Diagnostic | CUDA 디바이스명, 여유 VRAM(MB), FFmpeg 버전, MuseScore 바이너리 유무 |

---

## 2. 모델 프리페치 전략 (`scripts/prefetch_models.py`)

서버 부팅 도중 4GB 이상의 모델 가중치를 다운로드하면 네트워크 타임아웃으로 인한 서비스 시작 실패가 발생한다.  
따라서 배포/빌드 시점에 프리페치 스크립트로 사전에 가중치를 다운로드하고 Checksum을 검증한다.

```bash
uv run python scripts/prefetch_models.py
```
