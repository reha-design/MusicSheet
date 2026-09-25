# Infrastructure Spec: Docker & Development Environment

> **Canonical Owner:** `docs/infrastructure/docker.md`  
> **관련 문서:** [docs/backend/database.md](../backend/database.md), [docs/backend/redis-streams.md](../backend/redis-streams.md)
>
> **구현 상태:** PostgreSQL·Redis Compose 설정은 구현되어 있습니다. API와 worker 컨테이너는 포함되지 않습니다.

---

## 1. 현재 로컬 인프라

Compose의 단일 기준은 [docker/docker-compose.yml](../../docker/docker-compose.yml)입니다. 이 문서에 Compose YAML을 복사하지 않아 실제 설정과 예제가 어긋나지 않게 합니다.

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml down
```

Compose는 PostgreSQL 16과 Redis 7을 시작합니다. 기본 개발 접속 값은 `.env.example`에 있으며, Compose에 적힌 기본값과도 일치합니다. 사용자별 설정이 필요하면 프로젝트 루트의 `.env`에 값을 지정합니다.

현재 Compose는 데이터 볼륨과 기본 healthcheck를 제공합니다. 애플리케이션, Celery workers, CUDA는 시작하지 않습니다.
