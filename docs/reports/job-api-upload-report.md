# Job REST API v1 — Bounded Upload and Artifact Metadata Report

> **Date:** 2026-09-28
> **Scope:** W01 Task 2 — bounded audio upload and transactional metadata
> **Plan review:** revision 6, 99/100 (passed, 2026-09-28)
> **Independent code review:** 97/100 (passed, 2026-09-28)

## Implemented

- Added `POST /api/v1/jobs/upload` for one multipart `file` and optional `target_instrument=piano`. It rejects duplicate or unknown fields, text in the file field, unsupported suffixes, and invalid instruments. Supported `.wav`, `.mp3`, `.m4a`, `.flac`, and `.ogg` uploads receive generated `source_original{suffix}` names; the client filename path and MIME claim are not used.
- Added a route-specific ASGI body limit of the configured file limit plus 64 KiB. It checks declared `Content-Length` before reading and counts actual request bytes for understated or missing lengths. The storage copy independently stops files over `MAX_UPLOAD_BYTES` (default 100 MiB).
- Added `ArtifactStorage.delete` and a LocalStorage implementation that validates the exact job-directory entry and unlinks only that entry. Missing files are idempotent; a final filename symlink is unlinked without following its target.
- Added `ArtifactRepository` for bound-parameter insert, list, and job-scoped lookup. Job creation can use a preallocated ID and the existing transaction connection. The upload path inserts the job and `SOURCE_ORIGINAL` artifact in one PostgreSQL transaction after storage succeeds.
- Synchronous storage writes and compensation deletes run in worker threads so large files do not block the API event loop. If request cancellation arrives during a write, the service waits for that write to finish, removes the resulting file while shielding cleanup from cancellation, then re-raises cancellation. If metadata insertion fails, the transaction rolls back and cleanup preserves the original failure.
- The job-plus-artifact transaction runs in its own shielded task. If the client cancels while metadata is being written or committed, the request waits until the transaction outcome is known. A confirmed commit keeps both DB rows and the file, although the canceled client may not receive the generated job ID; a rollback/failure triggers file cleanup. This avoids a committed artifact row pointing to a file deleted by cancellation cleanup.
- The upload body limiter buffers the small endpoint response until it has counted the complete request body. If route parsing skips an unread body (for example, because its content type is not multipart), the middleware drains and enforces the same cap before returning that response. Multipart parser limits are one file and one text field.
- Aligned artifact provenance fields with nullable PostgreSQL columns and added API-local `python-multipart`; root project dependencies and lockfile are unchanged.

## Decisions and boundaries

- PostgreSQL owns job and artifact metadata; LocalStorage owns file bytes. The API returns a job response only and does not expose an internal storage URI.
- Extension controls admission and the recorded MIME type; the audio worker remains responsible for decoding and validating actual media content.
- A process interruption between a successful file write and database commit can still leave an orphan file. Cross-system recovery/reconciliation is outside this task.
- YouTube handling remains offline URL registration only. This task adds no download, Celery dispatch, SSE, model inference, or score rendering.

## Verification

| Check | Result |
| :--- | :--- |
| Storage delete RED → GREEN | Missing-interface run: 5 failed, 27 passed, 4 skipped; after implementation: 32 passed, 4 skipped. |
| Upload/repository/config/schema RED | New imports initially failed as expected; missing setting, transaction connection, and nullable fields were separately observed by failing tests. |
| Focused upload, artifact repository, config, and job repository tests | 59 passed before the final five-suffix parameterization; all five supported-suffix cases then passed. |
| Review-finding regression tests | Before fixes, the new cases failed: cancellation during storage write completed instead of cancelling, and oversized non-multipart bodies returned 422. After fixes, all targeted cases passed. |
| Commit cancellation regression | Before the fix, cancellation during the simulated commit rolled back the fake transaction and deleted the stored file. After shielding the metadata transaction and waiting through repeated cancellation: commit completed, file remained, and the caller still received `CancelledError`. |
| API suite (`MUSICSHEET_TEST_DATABASE_URL` unset) | 129 passed, 9 skipped; skipped tests require the opt-in PostgreSQL integration database. |
| Root storage/schema suite | 53 passed, 4 skipped. All skips are symlink cases unavailable under this Windows user's current privilege (WinError 1314). |
| API lock consistency | `uv lock --project services/api --check` passed. |
| `git diff --check` | Passed (Git also printed expected LF-to-CRLF working-copy notices). |

The only remaining warning is the existing Starlette/httpx `TestClient` deprecation warning. No live PostgreSQL test was needed for this task; upload transaction behavior is covered with transaction-boundary tests, and the opt-in database proof is part of Task 3.

## Review

The first independent Task 2 review scored 87/100 and found two important issues (synchronous file copying blocked the event loop; unread bodies with unsupported content types bypassed actual-byte counting) plus one minor parser-bound suggestion. The follow-up review identified commit ambiguity on cancellation; a regression test reproduced the unsafe boundary and the transaction now runs in a shielded task until its outcome is known. Worker-thread storage I/O with cancellation-safe cleanup, response-held body draining, and one-file/one-field parser limits address the review findings. Plan Revision 6 scored 99/100, and the final Task 2 code review scored 97/100. Both gates passed with no unresolved blocker or important finding.
