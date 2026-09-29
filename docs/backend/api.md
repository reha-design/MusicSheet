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
| `GET` | `/api/v1/jobs/{job_id}/events` | `Last-Event-ID` optional | Replay retained job progress events and stream updates using SSE. |
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
- PostgreSQL stores job and artifact metadata in one transaction; audio bytes remain in the configured storage backend. The full multipart request is capped at the file limit plus 64 KiB; the file itself is capped at 100 MiB by default. The API limits parsing to one file and one optional text field.
- Synchronous storage writes and cleanup run in worker threads. Cancellation during a write waits for the write to finish, deletes the file, then propagates cancellation. Once metadata registration starts, cancellation waits for a known transaction outcome: a commit preserves both job and artifact even if the canceled caller does not receive its job ID; rollback/failure attempts to delete the stored file. A process interruption between filesystem write and DB commit may still leave an orphan for later reconciliation.
- File extension is an admission check only. The audio decoder/worker validates the real media format later.

### Responses and failures

- Successful job registration returns `201 Created` and a public job representation with `id`, source type, canonical source URL where applicable, target instrument, status/stage/progress, and timestamps.
- Job and upload artifact persistence commits before the API publishes a Celery `start_job` message containing only the job ID. If publishing reports an error, the API changes only a still-`PENDING` job to `FAILED/DISPATCH_FAILED`; if a worker already claimed it, the API returns its current PostgreSQL snapshot.
- If publishing fails and PostgreSQL cannot persist or reload the dispatch outcome, registration returns sanitized `503` JSON shaped as `{"detail":{"message":"Job dispatch status is unavailable","job_id":"<job-id>"}}`. The stable ID lets the caller recover the authoritative snapshot with `GET /api/v1/jobs/{job_id}`; no broker or database exception detail is returned.
- `DELETE /api/v1/jobs/{job_id}` returns `202 Accepted` for an eligible or already-requested job, `409 Conflict` for a terminal job, and `404 Not Found` for an unknown ID. The worker performs the eventual transition from `CANCEL_REQUESTED` to `CANCELED`.
- Public artifact representations contain `id`, `job_id`, role, filename, MIME type, size, SHA-256, producer metadata, and a relative `download_url`. They omit internal `uri` and absolute filesystem paths.
- Artifact listing first verifies that the job exists, so `200 []` means a known job with no artifacts. Content downloads are streamed as attachments and looked up with both the requested job ID and artifact ID. The response includes the recorded `Content-Length`; if storage fails during streaming, the API logs a fixed generic warning, closes the stream, and ends the body so clients can detect a short download without receiving the storage exception or path.
- `GET` of a missing job or an artifact not associated with the specified job returns `404`.
- Invalid request/URL/extension returns `422`; a file over the configured limit returns `413`; unavailable DB or storage returns a generic `503`; unexpected failures return a generic error without raw driver text or secrets.
- The API does not implement authentication or user authorization in W01. `user_id` remains null; deployments exposed beyond a trusted local environment require a later authentication boundary.

## 2. Job lookup and cancellation

`GET /api/v1/jobs/{job_id}` reads the latest job snapshot from PostgreSQL. Clients can poll this route or subscribe to the W02 SSE event stream; PostgreSQL remains authoritative if retained events expire.

`DELETE /api/v1/jobs/{job_id}` requests a cooperative cancellation. An atomic repository operation changes `PENDING`, `RUNNING`, or `RETRYING` to `CANCEL_REQUESTED`, updating `updated_at`. Repeating the request for an already `CANCEL_REQUESTED` job is idempotent. A terminal job (`COMPLETED`, `FAILED`, or `CANCELED`) returns `409`; an unknown ID returns `404`. The W03 worker observes cancellation before a stage and at progress checkpoints, then closes the running attempt and changes the job to `CANCELED`. If the cancellation commits before an orchestration failure, cancellation wins.

## 3. Artifact listing and download

`GET /api/v1/jobs/{job_id}/artifacts` queries PostgreSQL metadata for that job and returns relative download routes. It returns `404` for an unknown job. `GET /api/v1/jobs/{job_id}/artifacts/{artifact_id}/content` queries by both IDs before opening the stored artifact, so an ID from a different job cannot be used through this route. Bytes stream through `ArtifactStorage.open_read`; the API does not expose the storage URI.

## 4. SSE streaming

- Browser clients may use `EventSource('/api/v1/jobs/{job_id}/events')`.
- The API first checks that the job exists in PostgreSQL. PostgreSQL remains the authoritative job snapshot returned by `GET /api/v1/jobs/{job_id}`.
- Each Redis Stream entry stores the common `JobProgressEvent` JSON in its `data` field. SSE frames use the Redis Stream ID as `id` and this JSON as `data`; `job_id`, `status`, `stage`, `stage_progress`, `overall_progress`, `message`, and `timestamp` are preserved.
- A first connection without `Last-Event-ID` reads after `0-0`. Reconnects resume after the supplied ID. Redis retains approximately the most recent 100 events per job (`MAXLEN ~ 100`); if older events were trimmed, clients should fetch the current PostgreSQL snapshot.
- An idle stream sends the `: keep-alive` comment every 15 seconds. Invalid `Last-Event-ID` returns `400`; an unknown job returns `404`; PostgreSQL or Redis unavailable before response start returns a generic `503`. A Redis error after streaming starts is logged without sensitive details and closes the stream.

## 5. Processing boundary

The API creates jobs with `status=PENDING`, `current_stage=DOWNLOAD`, and zero progress, then dispatches the registered job after its persistence transaction commits. W03 runs the six-stage orchestration and updates PostgreSQL attempts/status/progress, but does not fetch YouTube media, transform audio, run inference, quantize notes, or render a score. Since W04–W08 handlers are not registered yet, the first stage fails visibly with `STAGE_NOT_CONFIGURED` instead of falsely completing the workflow. Deployment and maintenance details are in the [Celery orchestration spec](./celery.md).
