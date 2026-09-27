# Backend Spec: FastAPI Gateway

> **Canonical Owner:** `docs/backend/api.md`  
> **관련 문서:** [docs/domain/job-state.md](../domain/job-state.md), [docs/domain/artifacts.md](../domain/artifacts.md), [docs/backend/database.md](./database.md)

---

## 1. Job registration and REST contract

The API accepts one source per job. Job creation stores a durable `PENDING` job and returns its ID; actual media processing is asynchronous and belongs to the worker/orchestration tasks.

| Method | Endpoint | Request | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/jobs` | JSON `source_url`, optional `target_instrument` | Register a YouTube source. The API sets `source_type=YOUTUBE`. |
| `POST` | `/api/v1/jobs/upload` | Multipart `file`, optional `target_instrument` | Store an uploaded audio source. The API sets `source_type=UPLOAD` and creates a `SOURCE_ORIGINAL` artifact. |
| `GET` | `/api/v1/jobs/{job_id}` | — | Return current job state and progress from PostgreSQL. |
| `DELETE` | `/api/v1/jobs/{job_id}` | — | Request cancellation by setting `CANCEL_REQUESTED` where allowed. |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | — | Return artifact metadata and API-relative download URLs. |
| `GET` | `/api/v1/jobs/{job_id}/artifacts/{artifact_id}/content` | — | Stream the artifact bytes after verifying job/artifact association. |
| `GET` | `/api/v1/jobs/{job_id}/events` | `Last-Event-ID` optional | Future W02: SSE stream with replay from Redis Streams. |
| `GET` | `/health/live` | — | Process liveness. |
| `GET` | `/health/ready` | — | PostgreSQL, Redis, and storage availability. |
| `GET` | `/health/detail` | — | Best-effort API host GPU, FFmpeg, and MuseScore diagnostics. |

### YouTube input

- The JSON body contains `source_url: str` and optional `target_instrument: "piano"` (defaults to `piano`). The client does not set `source_type` or `user_id`.
- Supported URL forms are HTTPS `youtu.be/{video_id}` and HTTPS `youtube.com/watch?v={video_id}` on the exact hosts `youtu.be`, `youtube.com`, `www.youtube.com`, `m.youtube.com`, and `music.youtube.com`.
- URLs must use HTTPS, contain no userinfo or non-default port, and use an exact allowlisted host. A short URL has exactly one path segment; a watch URL has exactly one `v` parameter. The video ID uses YouTube's 11-character URL-safe alphabet `[A-Za-z0-9_-]`. The service stores the canonical form `https://www.youtube.com/watch?v={video_id}`; unrelated sharing query parameters are dropped.
- Registration performs no network lookup, redirect following, media download, or metadata scraping. A valid URL can still refer to a private, unavailable, or unsupported video; the downloader checks that later.
- `https://youtu.be/A9x7du4921A` is the stable offline test input for parser and API registration. Automated registration tests must not call YouTube.

### Upload input

- Multipart fields: required `file`; optional `target_instrument` defaulting to `piano`.
- Accepted filename extensions: `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg` (case-insensitive). Maximum file size: 100 MiB by default, controlled by `MAX_UPLOAD_BYTES`. The full multipart body is capped at that file limit plus 64 KiB of multipart overhead, including requests without `Content-Length`.
- Client filenames are never used as storage paths. The API stores `source_original{extension}` under the generated job ID and records the LocalStorage `ArtifactRef` as `SOURCE_ORIGINAL`.
- PostgreSQL stores job and artifact metadata in one transaction; audio bytes remain in the configured storage backend. On a caught DB write failure, the API attempts to delete the just-stored file. A process interruption between filesystem write and DB commit may leave an orphan file for later reconciliation.
- File extension is an admission check only. The audio decoder/worker validates the real media format later.

### Responses and failures

- Successful job registration returns `201 Created` and a public job representation with `id`, source type, canonical source URL where applicable, target instrument, status/stage/progress, and timestamps.
- Public artifact representations contain `id`, `job_id`, role, filename, MIME type, size, SHA-256, producer metadata, and a relative `download_url`. They omit internal `uri` and absolute filesystem paths.
- `GET` of a missing job or an artifact not associated with the specified job returns `404`.
- Invalid request/URL/extension returns `422`; a file over the configured limit returns `413`; unavailable DB or storage returns a generic `503`; unexpected failures return a generic error without raw driver text or secrets.
- The API does not implement authentication or user authorization in W01. `user_id` remains null; deployments exposed beyond a trusted local environment require a later authentication boundary.

## 2. Job lookup and cancellation

`GET /api/v1/jobs/{job_id}` reads the latest job snapshot from PostgreSQL. Clients can poll this route in W01; SSE events are a separate W02 task.

`DELETE /api/v1/jobs/{job_id}` requests a cooperative cancellation. An atomic repository operation changes `PENDING`, `RUNNING`, or `RETRYING` to `CANCEL_REQUESTED`, updating `updated_at`. Repeating the request for an already `CANCEL_REQUESTED` job is idempotent. A terminal job (`COMPLETED`, `FAILED`, or `CANCELED`) returns `409`; an unknown ID returns `404`. W01 records the request only; a worker must later observe it and finish in `CANCELED`.

## 3. Artifact listing and download

`GET /api/v1/jobs/{job_id}/artifacts` queries PostgreSQL metadata for that job and returns relative download routes. It returns `404` for an unknown job. `GET /api/v1/jobs/{job_id}/artifacts/{artifact_id}/content` queries by both IDs before opening the stored artifact, so an ID from a different job cannot be used through this route. Bytes stream through `ArtifactStorage.open_read`; the API does not expose the storage URI.

## 4. SSE streaming (future W02)

- Browser clients may use `EventSource('/api/v1/jobs/{job_id}/events')`.
- On reconnect, `Last-Event-ID` replays events retained in Redis Streams.
- This endpoint is not part of the W01 implementation.

## 5. Processing boundary

W01 creates jobs with `status=PENDING`, `current_stage=DOWNLOAD`, and zero progress. It does not contact YouTube or dispatch Celery tasks. Future orchestration downloads and stores the original source, then advances through preprocessing, separation, transcription, postprocessing, and rendering. Until that implementation exists, a successfully registered job remains pending.
