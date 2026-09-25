# Infrastructure Spec: Docker & Development Environment

> **Canonical Owner:** `docs/infrastructure/docker.md`  
> **관련 문서:** [docs/backend/database.md](../backend/database.md), [docs/backend/redis-streams.md](../backend/redis-streams.md)

---

## 1. Local Compose Services (`docker/docker-compose.yml`)

로컬 개발 환경에서는 상태 저장소(PostgreSQL)와 메시지 브로커(Redis)를 Docker Compose로 띄우고, GPU 접근이 필요한 AI Worker 및 API는 로컬 호스트(CUDA가 직접 붙는 환경)에서 `uv run`으로 실행한다.

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: musicsheet_postgres
    environment:
      POSTGRES_DB: musicsheet
      POSTGRES_USER: musicsheet_user
      POSTGRES_PASSWORD: musicsheet_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    container_name: musicsheet_redis
    command: redis-server --appendonly yes
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```
