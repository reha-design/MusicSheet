# Infrastructure Spec: Health Check & Model Prefetch

> **Canonical Owner:** `docs/infrastructure/health-check.md`  
> **관련 문서:** [docs/backend/api.md](../backend/api.md)
>
> **구현 상태:** 목표 명세입니다. 현재 저장소에는 API health endpoint나 model prefetch script가 없습니다.

---

## 1. 목표 Health Check

| Endpoint | 역할 | 점검 대상 |
| :--- | :--- | :--- |
| `/health/live` | Liveness | API 프로세스 생존 |
| `/health/ready` | Readiness | DB, Redis, 스토리지 등 API 의존성 연결 |
| `/health/detail` | Diagnostic | worker 환경에 필요한 CUDA, FFmpeg, MuseScore 정보 |

실제 서비스별 readiness 범위는 API와 worker가 분리 구현될 때 확정합니다. GPU나 렌더러가 없는 API 프로세스가 해당 의존성 때문에 일괄적으로 준비 실패로 판정되지 않도록 합니다.

---

## 2. 목표 모델 프리페치

`scripts/prefetch_models.py`는 설계상 사전 다운로드·checksum 검증용 스크립트이며 현재 파일은 없습니다. 아래 명령은 해당 스크립트가 구현된 뒤에만 실행할 수 있습니다.

```bash
uv run python scripts/prefetch_models.py
```
