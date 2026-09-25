# Backend Spec: FastAPI Gateway

> **Canonical Owner:** `docs/backend/api.md`  
> **관련 문서:** [docs/domain/job-state.md](../domain/job-state.md), [docs/backend/redis-streams.md](./redis-streams.md)

---

## 1. REST API 엔드포인트 명세

| Method | Endpoint | 설명 |
| :--- | :--- | :--- |
| `POST` | `/api/v1/jobs` | YouTube URL 등록 또는 오디오 파일 업로드 작업 생성 |
| `GET` | `/api/v1/jobs/{job_id}` | 작업 기본 상태 및 진행률 단건 조회 (PostgreSQL) |
| `GET` | `/api/v1/jobs/{job_id}/events` | SSE 스트림 연결 (`Last-Event-ID` 지원) |
| `DELETE` | `/api/v1/jobs/{job_id}` | 작업 취소 요청 (`CANCEL_REQUESTED` 전이) |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | 작업의 산출물 목록 및 다운로드 URL 조회 |
| `GET` | `/health/live` | 프로세스 생존 검사 |
| `GET` | `/health/ready` | DB, Redis, 스토리지 연결성 검사 |
| `GET` | `/health/detail` | CUDA VRAM, FFmpeg, MuseScore 바이너리 진단 정보 |

---

## 2. SSE 스트리밍 & 재접속 규격
- 브라우저는 `EventSource('/api/v1/jobs/{job_id}/events')`로 구독한다.
- 클라이언트 재연결 시 `Last-Event-ID` 헤더를 전송하여 끊긴 시점 이후의 이벤트를 Redis Streams에서 복원(Replay)받는다.
