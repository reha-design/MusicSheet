# Job REST API v1 — Implementation Report

> **Date:** 2026-09-28
> **Scope:** W01 — YouTube/audio job registration, job lookup/cancellation, and artifact list/download
> **Plan review:** Revision 6, 99/100 (passed)
> **Task 1 code review:** 99/100 (passed)
> **Task 2 code review:** 97/100 (passed)
> **Task 3 code review:** 96/100 (passed, 2026-09-28)

## Delivered

- `POST /api/v1/jobs` validates and canonicalizes approved YouTube URL forms, including the supplied offline fixture `https://youtu.be/A9x7du4921A`. Registration does not make network requests.
- `POST /api/v1/jobs/upload` accepts one WAV, MP3, M4A, FLAC, or OGG file. The file limit defaults to 100 MiB; the complete request is limited to the file cap plus 64 KiB. Generated filenames are stored with transactional job and artifact metadata.
- `GET /api/v1/jobs/{job_id}` returns the current database snapshot. `DELETE /api/v1/jobs/{job_id}` conditionally changes `PENDING`, `RUNNING`, or `RETRYING` to `CANCEL_REQUESTED`, preserves progress, and is idempotent. Terminal jobs return 409 and unknown jobs return 404.
- `GET /api/v1/jobs/{job_id}/artifacts` lists safe public metadata and relative download links. `GET /api/v1/jobs/{job_id}/artifacts/{artifact_id}/content` verifies the job/artifact pair and streams the bytes as a safe attachment while closing the file on completion or error. Downloads include the persisted `Content-Length`; if a storage read fails after headers are sent, the API records only a fixed generic warning and ends the body. Clients can detect truncation from the short body without receiving the storage exception or filesystem path.
- The API remains a registration and persistence boundary. Jobs stay `PENDING` until Celery dispatch is implemented; cancellation stays `CANCEL_REQUESTED` until a worker observes it. W01 does not fetch YouTube media, run models, render scores, implement SSE, or add authentication.

## Cancellation and failure behavior

- Cancellation during a storage write waits for the worker-thread operation, removes the completed file, and re-raises cancellation.
- After metadata registration begins, cancellation waits for a known transaction outcome. A committed transaction preserves both database rows and the file even if the canceled client does not receive the generated job ID. Rollback or failure triggers best-effort file cleanup.
- Storage failures and database errors return generic API responses. Artifact responses omit internal storage URIs and filesystem paths.
- A process interruption between a successful filesystem write and database commit can still leave an orphan file; cross-system reconciliation is outside W01.

## Verification

| Check | Result |
| :--- | :--- |
| Cancellation tests-first RED | 15 new route/repository cases failed as expected before `request_cancel` and DELETE behavior existed. |
| Artifact route tests-first RED | Missing list/download routes failed before implementation; unknown route happened to return 404, while the later implemented lookup tests verify the database scope. |
| Focused cancellation/repository/artifact tests | 81 passed, one existing Starlette/httpx deprecation warning. |
| Full API suite, `MUSICSHEET_TEST_DATABASE_URL` unset | 151 passed, 10 skipped, one existing Starlette/httpx deprecation warning. |
| Guarded PostgreSQL integration suite, final run | 10 passed in 3.80 seconds against PostgreSQL 16. The suite exercised the exact YouTube fixture, upload metadata, artifact download, and repeated cancellation without contacting YouTube. |
| Integration tests, `MUSICSHEET_TEST_DATABASE_URL` unset | The full API suite safely skipped all 10 opt-in PostgreSQL tests. |
| Root suite | 59 passed, 4 skipped, 4 deselected. The skips are Windows symlink tests unavailable with the current privilege (WinError 1314); deselected tests require the ML runtime. |
| API/root `uv lock --check` | Passed; root `pyproject.toml` and `uv.lock` are unchanged. |
| `git diff --check` | Passed after implementation and documentation updates. |

## Review

Plan Revision 6 passed at 99/100. Task 1 passed at 99/100 and Task 2 passed at 97/100, each with no unresolved blocker or important finding. Task 3 passed at 96/100: behavior 25/25, errors/security 24/25, tests/evidence 24/25, structure/dependencies 14/15, and docs/reproducibility 9/10. No blocker or important finding remains. Deferred minor: a response cancellation can race a worker-thread read against stream close; the reviewer assessed the risk as low for the current local-file backend.
