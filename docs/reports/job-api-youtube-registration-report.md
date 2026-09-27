# Job REST API v1 — YouTube Registration and Job Snapshot Report

> **Date:** 2026-09-27  
> **Scope:** W01 Task 1 — YouTube URL registration and job lookup  
> **Plan review:** revision 4, 97/100 (passed)  
> **Independent code review:** 99/100 passed (2026-09-27; earlier review iterations 95/100 and 98/100)

## Implemented

- Added an offline URL normalizer for HTTPS `youtu.be` and approved YouTube watch hosts. It rejects lookalike hosts, userinfo, invalid ports, malformed paths, missing/duplicate video IDs, and malformed percent escapes, then stores the canonical watch URL.
- Added `POST /api/v1/jobs` and `GET /api/v1/jobs/{job_id}`. The create route fixes the source type to `YOUTUBE`; PostgreSQL supplies the `PENDING`, `DOWNLOAD`, and zero-progress defaults. The existing `JobRepository` create/read methods are reused.
- Added public Pydantic response models that omit `user_id` and `error_message`. Request validation errors and database failures return generic messages rather than echoing user input or driver details.
- Kept the supplied URL `https://youtu.be/A9x7du4921A` as an offline fixture. Registration never contacts YouTube; media availability and download are deferred to worker work.
- Mounted the jobs router without changing the documented health route behavior.

## Decisions

- Registration validates only URL syntax and the 11-character video ID; it does not prove that a video exists or can be downloaded.
- Invalid URL syntax returns a sanitized `422`; missing jobs return `404`; missing database pool or repository failure returns a generic `503`.
- The job remains `PENDING` because Celery dispatch and the downloader are outside this task.

## Verification

| Check | Result |
| :--- | :--- |
| Test-first RED | Parser test collection failed before implementation because `musicsheet_api.jobs.youtube` did not exist. |
| Focused URL and route tests | `26 passed`; one existing Starlette/httpx TestClient deprecation warning. |
| Full API suite | `94 passed, 9 skipped`; skips are the opt-in PostgreSQL integration tests because `MUSICSHEET_TEST_DATABASE_URL` was unset. |
| Environment isolation | With a dummy ambient `DATABASE_URL`, the no-pool POST/GET test still passed (`1 passed`), confirming the test app uses explicit settings. |
| `git diff --check` | Passed. |

## Review

Independent reviews scored Task 1 at 95/100, 98/100, and finally 99/100, with no blocker or important finding. Suggestions for control-character handling, deterministic test settings, a backslash URL regression case, and the database-unavailable GET case were addressed and verified. Task 1 passed its 95-point review gate.

Final score breakdown: behavior 25/25, errors/security 25/25, tests/evidence 24/25, structure/dependencies 15/15, documentation/reproducibility 10/10. Review scope was the Task 1 diff from `5f79b12` through the final working tree on 2026-09-27.
