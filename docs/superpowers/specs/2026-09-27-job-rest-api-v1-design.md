# Job REST API v1 Design

- Date: 2026-09-27
- Status: Approved for implementation by the user's request to implement and test W01.
- Scope: API job registration, lookup, cancellation requests, source upload, artifact listing, and artifact download.

## Goal

Let a user register a YouTube piano source or upload an audio file, obtain a stable job ID, inspect job state, request cancellation, and retrieve stored artifacts through FastAPI.

The supplied YouTube URL `https://youtu.be/A9x7du4921A` is the representative registration fixture. Public page metadata identifies it as a piano cover. W01 tests use the URL as input data and do not fetch media from YouTube.

## Decisions

- `POST /api/v1/jobs` accepts JSON containing `source_url` and optional `target_instrument` for YouTube jobs. The API fixes `source_type` to `YOUTUBE`.
- `POST /api/v1/jobs/upload` accepts multipart `file` and optional `target_instrument` for uploaded audio. The API fixes `source_type` to `UPLOAD`.
- The YouTube parser accepts HTTPS `youtube.com` watch URLs and `youtu.be` short URLs, extracts a video ID, and stores `https://www.youtube.com/watch?v={id}`. It does no network request or redirect following.
- W01 upload policy allows `.wav`, `.mp3`, `.m4a`, `.flac`, and `.ogg`, with a configurable 100 MiB default. The API-only `python-multipart` dependency parses multipart requests; the upload route caps total request bytes at the configured file limit plus 64 KiB, including chunked requests without `Content-Length`, and also checks bytes while copying the file. The server-generated stored filename never includes a client path. Extension admission does not validate codecs; worker decoding owns that check.
- Uploaded bytes go to LocalStorage. PostgreSQL stores `jobs` and `artifacts` metadata only. The two rows are inserted in one DB transaction. A storage file created before DB commit is deleted if a caught DB write fails. A process crash in the cross-system gap can still leave an orphan file; a general reconciliation job is out of scope.
- Public artifact responses omit the internal storage URI. They contain a relative API download URL. Download verifies that the artifact belongs to the requested job and streams through `ArtifactStorage.open_read`.
- `GET /api/v1/jobs/{job_id}` returns the current snapshot from PostgreSQL. SSE is deferred to W02.
- `DELETE /api/v1/jobs/{job_id}` atomically changes `PENDING`, `RUNNING`, or `RETRYING` to `CANCEL_REQUESTED`; repeated cancel requests are idempotent. A terminal job returns `409`; a missing job returns `404`. W01 records a request and does not stop a worker.
- W01 creates jobs as `PENDING` at `DOWNLOAD`, but does not download YouTube content, dispatch Celery tasks, run AI models, or render scores. Those actions require later W03/W04/W08 work.
- No user authentication exists. API request schemas do not accept `user_id`; new jobs keep the database default `NULL`. Authentication and per-user authorization are deployment prerequisites outside W01.
- Invalid input returns `422`, unknown resources `404`, terminal cancellation `409`, oversized upload `413`, unavailable database/storage `503`, and unexpected failures use generic sanitized messages. Internal URIs, DSNs, and raw driver errors are not returned or logged.

## Main flow

```mermaid
sequenceDiagram
    actor Client as User app
    participant API as FastAPI
    participant Storage as LocalStorage
    participant DB as PostgreSQL

    Client->>API: POST /api/v1/jobs/upload (multipart)
    API->>API: Validate file name extension and byte limit
    API->>API: Allocate job_id
    API->>Storage: Store SOURCE_ORIGINAL file
    Storage-->>API: ArtifactRef (id, size, SHA-256, URI)
    API->>DB: BEGIN; INSERT jobs and artifacts
    DB-->>API: COMMIT
    API-->>Client: 201 JobResponse

    alt DB write fails
        API->>Storage: Delete saved file (compensation)
        API-->>Client: Generic sanitized error
    end
```

## Data ownership

- PostgreSQL owns job state and artifact metadata.
- LocalStorage owns source/output file bytes.
- Client receives job fields and artifact metadata, never the local filesystem URI.
- Job polling is available in W01. Event streaming is a later optimization.

## Test strategy for the supplied URL

- Offline parser test: extract `A9x7du4921A` from the exact short URL and assert the canonical stored URL.
- API test: submit the exact URL, assert one YOUTUBE job is persisted with `PENDING`/`DOWNLOAD` defaults, and verify no HTTP client or downloader is called.
- Optional PostgreSQL integration test: use the disposable test database for the same registration and read-back path, still without contacting YouTube.
- Actual download/transcription smoke test: defer until a downloader and worker are part of the executable pipeline; run as an explicit opt-in network test, not as a default unit test.

## Alternatives considered

- One POST path with JSON and multipart content-type dispatch: preserves a single path but requires manual body parsing and less direct OpenAPI request schemas. Separate typed paths were selected.
- Fetch YouTube metadata during registration: makes job creation depend on external latency and availability. Registration stores a validated canonical URL; the worker checks availability later.
- Return `file://` URIs to clients: rejected because it exposes server paths and does not work for remote clients. Use an API streaming route.

