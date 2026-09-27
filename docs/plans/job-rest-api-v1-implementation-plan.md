# Job REST API v1 Implementation Plan

> **For agentic workers:** Use TDD for each behavior. Finish one task, record its independent 95/100 code review, and resolve blocker/important findings before the next task. Follow `superpowers:executing-plans` inline. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Expose the first user-facing API flow for registering a YouTube or uploaded audio job, checking its status, requesting cancellation, and listing/downloading its artifacts.

**Architecture:** Add a focused jobs router and request/response schemas to the existing standalone FastAPI project. PostgreSQL remains authoritative for job and artifact metadata; configured `ArtifactStorage` owns file bytes. YouTube registration canonicalizes known URL forms without network access. Upload metadata is committed in one database transaction after LocalStorage writes the file in a worker thread, with cancellation-safe best-effort cleanup on a caught DB failure.

**Tech Stack:** Python 3.13, FastAPI, `python-multipart` (API-only request parsing), asyncpg, Pydantic, existing `musicsheet-common`, `musicsheet-storage`, pytest, TestClient, PostgreSQL 16 opt-in integration DB.

**Spec:** [Job REST API v1 design](../superpowers/specs/2026-09-27-job-rest-api-v1-design.md), [API Gateway](../backend/api.md), [Job State](../domain/job-state.md), [Artifacts](../domain/artifacts.md), [Storage](../architecture/storage.md), [Database](../backend/database.md)

## Global Constraints

- Keep `services/api` an independent Python `>=3.13,<3.14` uv project. Add `python-multipart` only to this API project because FastAPI multipart parsing requires it; update `services/api/uv.lock` and leave root lockfiles unchanged.
- Preserve canonical `jobs` and `artifacts` PostgreSQL columns, defaults, indexes, and foreign keys.
- Use the existing `JobStatus`, `PipelineStage`, and `ArtifactRole` enums. Align `ArtifactRef.producer` and `producer_version` to the canonical nullable PostgreSQL columns without renaming its fields.
- Never return or log DB URLs, raw driver errors, absolute storage paths, or internal artifact URIs.
- Do not contact YouTube during URL registration; the supplied URL is a deterministic fixture, not an external-network unit test.
- Do not dispatch Celery work, implement SSE, download media, run AI models, or render scores in W01.
- Upload limit defaults to 104,857,600 file bytes (100 MiB), configurable with `MAX_UPLOAD_BYTES`; accepted suffixes are `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`. Bound the complete upload request body to the file limit plus a documented 64 KiB envelope allowance; count bytes even when the route rejects without consuming the body.
- Execute synchronous storage writes and compensation deletes in worker threads. If cancellation occurs during a write, wait for that write to finish, complete file cleanup despite repeated cancellation, and then re-raise the cancellation.
- Run the job-plus-artifact metadata transaction in a shielded task. If caller cancellation occurs during commit, wait until the transaction outcome is known; preserve the file after a confirmed commit and delete it after rollback/failure.

## Review Focus

1. Lookalike hostnames, malformed URL forms, tracking query parameters, and user-supplied test URL — reject unsafe forms and canonicalize valid IDs without making network requests.
2. Upload body larger than the limit (including an unread body with an unsupported content type), misleading filename/content type, and path-like filenames — reject unsupported/oversize inputs and never use a client path for storage.
3. DB failure after file storage or request cancellation at any transaction boundary — wait for a known commit/rollback outcome, retain the artifact only after confirmed commit, and otherwise attempt bounded safe cleanup without leaking errors.
4. An artifact ID from another job, missing on-disk bytes, or DB rows with nullable producer metadata — do not disclose another artifact or local path; return stable API errors.
5. Repeated/concurrent cancellation, terminal jobs, and unknown jobs — preserve atomic, idempotent state semantics and progress fields.

## Plan Review Gate

- An independent reviewer scores the current plan revision with the five criteria in `AGENTS.md`. Implementation starts only at 95/100 or above and with no unresolved blocker/important finding.
- An independent code review scores each implementation task separately; 95/100 and no unresolved blocker/important finding are required before advancing.

### Plan Review Record

- **Revision 4: 97/100 — passed on 2026-09-27.** Independent review against `AGENTS.md`: requirements/spec 25/25, scope/interfaces 20/20, sequence/deliverables/dependencies 19/20, validation/failure coverage 23/25, reproducibility/operations/docs 10/10. No unresolved blocker or important finding. Minor review suggestions (duplicate/wrong-type multipart tests, cleanup failure preserving the primary exception, and clearing the disposable DB URL before final suites) were added to revision 4.
- **Revision 5: 98/100 — passed on 2026-09-28.** Independent review: requirements/spec 25/25, scope/interfaces 20/20, sequence/dependencies 20/20, validation/failure coverage 23/25, reproducibility/ops/docs 10/10. Added operational requirements from Task 2 review: storage I/O runs in worker threads with cancellation-safe cleanup, and the body limit is enforced even when the route does not consume the request body. Minor suggestion: name repeated cancellation during cleanup in the test list.
- **Revision 6: 99/100 — passed on 2026-09-28.** Independent review: requirements/spec 25/25, scope/interfaces 20/20, sequence/dependencies 20/20, validation/failure coverage 24/25, reproducibility/operations/docs 10/10. Clarifies cancellation during metadata registration: await a known transaction outcome, keep the artifact only after commit, and delete it after rollback/failure. Adds a repeated-cancellation regression test. No unresolved blocker or important finding.

## Interfaces

- `normalize_youtube_url(source_url: str) -> str` in `jobs/youtube.py` accepts HTTPS `youtu.be/{id}` and watch URLs on the exact hosts `youtube.com`, `www.youtube.com`, `m.youtube.com`, and `music.youtube.com`; rejects userinfo and non-default ports; requires exactly one valid `v` parameter for watch URLs and exactly one path segment for short URLs; validates an 11-character URL-safe video ID; and returns `https://www.youtube.com/watch?v={id}`. Invalid input raises `ValueError` without network access.
- `YouTubeJobCreateRequest` contains `source_url: str` and `target_instrument: Literal["piano"] = "piano"`; the server chooses `source_type="YOUTUBE"` and does not accept `user_id`.
- `JobResponse` exposes id, source_type, source_url, target_instrument, status, current_stage, stage/overall progress, error_code, and timestamps. It omits user_id and error_message.
- `ArtifactResponse` exposes id, job_id, role, filename, mime_type, size_bytes, sha256, nullable producer/producer_version, created_at, and a relative `download_url`; it omits `uri`.
- `JobRepository.create_job(*, source_type: str, source_url: str | None, user_id: str | None = None, target_instrument: str | None = "piano", job_id: str | None = None, connection: asyncpg.Connection | None = None) -> JobRecord` remains backward-compatible. A supplied UUID and connection let upload registration insert job and artifact metadata in one DB transaction. `request_cancel(job_id: str) -> JobRecord | None` atomically requests cancellation for eligible statuses and returns the current record for an already-requested/terminal status.
- `ArtifactRecord` is a frozen API value with `id: str`, `job_id: str`, `role: ArtifactRole`, `filename: str`, `uri: str`, `mime_type: str`, `size_bytes: int`, `sha256: str`, `producer: str | None`, `producer_version: str | None`, and `created_at: datetime | None`. `ArtifactRepository.add(artifact: ArtifactRef, *, connection: asyncpg.Connection | None = None) -> ArtifactRecord`, `list_for_job(job_id: str) -> list[ArtifactRecord]`, and `get_for_job(job_id: str, artifact_id: str) -> ArtifactRecord | None` use bound SQL values.
- `ArtifactStorage.delete(artifact: ArtifactRef) -> bool` safely removes the matching artifact and is idempotent for a missing file; `LocalStorage` implements it under the existing path safety rules.
- Once the upload metadata transaction has started, request cancellation waits for a known transaction outcome. If it commits, the job and artifact remain stored even though the canceled client may not receive the job ID; if it rolls back/fails, the stored file is removed best-effort.
- `POST /api/v1/jobs` accepts YouTube JSON and returns `201 JobResponse`.
- `POST /api/v1/jobs/upload` accepts multipart `file` and optional `target_instrument`, returns `201 JobResponse`, and stores `SOURCE_ORIGINAL` metadata.
- `GET /api/v1/jobs/{job_id}` returns `200 JobResponse` or `404`.
- `DELETE /api/v1/jobs/{job_id}` returns `202 JobResponse` for an eligible/already-requested job, `409` for terminal jobs, or `404` for an unknown job.
- Artifact list first verifies the job exists, then returns `200 list[ArtifactResponse]` (empty when none) or `404` if the job is missing. Download returns streamed bytes or `404`; the artifact lookup is scoped by both job and artifact IDs.
- DB/storage unavailability is mapped to generic `503` responses; invalid request data is `422`; over-limit upload is `413`. No raw dependency exception reaches clients/logs.

## Tasks

### Task 1: YouTube job registration and job snapshot API

**Files:**
- Modify: `docs/plans/job-rest-api-v1-implementation-plan.md` (task checklist and independent review record)
- Create: `services/api/src/musicsheet_api/jobs/youtube.py`
- Create: `services/api/src/musicsheet_api/jobs/schemas.py`
- Create: `services/api/src/musicsheet_api/jobs/router.py`
- Modify: `services/api/src/musicsheet_api/jobs/repository.py`
- Modify: `services/api/src/musicsheet_api/app.py`
- Modify: `docs/backend/api.md`
- Test: `services/api/tests/test_youtube.py`
- Test: `services/api/tests/test_job_routes.py`
- Create: `docs/reports/job-api-youtube-registration-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:** consumes `JobRepository.create_job/get_job`; produces the YouTube create route, `GET job`, URL normalizer, and public `JobResponse` for Tasks 2–3.

- [x] **Step 1: Write URL parser tests** named `test_normalizes_supplied_short_url`, `test_normalizes_watch_url_and_drops_tracking_parameters`, `test_rejects_unapproved_hosts_and_http`, `test_rejects_malformed_or_missing_video_ids`, `test_rejects_userinfo_duplicate_v_and_nondefault_port`, and `test_parser_never_performs_network_io`. Use `https://youtu.be/A9x7du4921A` as the exact accepted fixture; assert the normalized URL is `https://www.youtube.com/watch?v=A9x7du4921A`.
- [x] **Step 2: Run parser tests from the repository root** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_youtube.py -q`; confirmed RED because the module/function did not exist.
- [x] **Step 3: Implement the URL normalizer and typed request/response schemas** with exact-host matching, HTTPS-only validation, path/query parsing, and no outbound client.
- [x] **Step 4: Write route tests** named `test_youtube_registration_passes_canonical_test_url_to_repository`, `test_registration_returns_pending_download_job`, `test_get_job_returns_snapshot_or_404`, `test_job_routes_return_503_when_database_pool_is_absent`, and `test_job_route_errors_are_sanitized` using an injected fake pool/repository.
- [x] **Step 5: Implement and mount the jobs router**. `POST` inserts a YOUTUBE row with PENDING/DOWNLOAD/zero progress; `GET` reads by ID. Keep health endpoint responses unchanged. Route errors must not include raw URLs for invalid input, DSNs, or driver messages.
- [x] **Step 6: Run `uv run --project services/api --python 3.13 pytest services/api/tests/test_youtube.py services/api/tests/test_job_routes.py -q`, then the full API suite `uv run --project services/api --python 3.13 pytest services/api/tests -q`.** Expected: all focused tests and all existing API tests pass.
- [x] **Step 7: Write the focused task report, update the main-spec Reports index, run `git diff --check`, and complete an independent code review. Record the review in this plan; fix/review again until at least 95/100 with no blocker/important finding. Commit only Task 1 files.** Final review: 99/100, no blocker/important findings; included in the Task 1 commit.

**Task 1 independent code review record:**

- Review 1 (2026-09-27): 95/100 for Task 1 implementation, tests, and report. Minor findings were embedded control characters being normalized by `urlsplit`, ambient `DATABASE_URL` affecting TestClient startup, and an unclear plan/review status line.
- Review 2 (2026-09-27): 98/100 after rejecting controls/backslashes, using explicit test settings, and distinguishing the plan score from the code review. Minor requests were a backslash regression case and GET/no-pool coverage.
- Final review (2026-09-27): **99/100**. Behavior 25/25, errors/security 25/25, tests/evidence 24/25, structure/dependencies 15/15, documentation/reproducibility 10/10. Scope: commit `5f79b12` through the Task 1 working diff. No unresolved blocker or important finding.

### Task 2: Bounded audio upload and artifact metadata transaction

**Files:**
- Modify: `docs/plans/job-rest-api-v1-implementation-plan.md` (task checklist and independent review record)
- Modify: `packages/common/musicsheet_common/schemas/artifacts.py`
- Modify: `docs/domain/artifacts.md`
- Modify: `packages/storage/musicsheet_storage/base.py`
- Modify: `packages/storage/musicsheet_storage/local.py`
- Modify: `docs/architecture/storage.md`
- Modify: `services/api/src/musicsheet_api/config.py`
- Modify: `services/api/pyproject.toml`
- Modify: `services/api/uv.lock`
- Create: `services/api/src/musicsheet_api/jobs/upload_body_limit.py`
- Modify: `services/api/src/musicsheet_api/app.py`
- Modify: `services/api/src/musicsheet_api/jobs/repository.py`
- Modify: `services/api/tests/test_job_repository.py`
- Create: `services/api/src/musicsheet_api/jobs/artifacts.py`
- Create: `services/api/src/musicsheet_api/jobs/uploads.py`
- Modify: `services/api/src/musicsheet_api/jobs/router.py`
- Modify: `services/api/tests/test_config.py`
- Modify: `tests/unit/test_storage.py`
- Modify: `tests/unit/test_schemas.py`
- Create: `services/api/tests/test_job_uploads.py`
- Create: `services/api/tests/test_artifact_repository.py`
- Create: `docs/reports/job-api-upload-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:** consumes Task 1 router/schemas and existing `ArtifactStorage.put`; produces `ArtifactStorage.delete`, `ArtifactRepository`, configured upload limit, and `POST /api/v1/jobs/upload`.

- [x] **Step 1: Write LocalStorage delete tests** named `test_delete_removes_matching_artifact`, `test_delete_missing_artifact_is_idempotent`, `test_delete_rejects_forged_uri_outside_storage_root`, and `test_delete_rejects_uri_for_different_job_or_filename`, `test_delete_unlinks_in_job_symlink_without_deleting_target`; expected behavior is scoped deletion only.
- [x] **Step 2: Run those tests** with `uv run --project . --python 3.13 pytest tests/unit/test_storage.py -q`; confirm RED on the missing interface.
- [x] **Step 3: Add the abstract `delete(artifact) -> bool` contract and LocalStorage implementation**, validating that the URI names exactly the lexical `job_dir/filename` entry, resolving and checking the job directory but never resolving the final filename symlink, then unlinking that directory entry (so it cannot delete its target). Missing files return false; unsafe URIs raise `ValueError`. Update the abstract-method contract test and `docs/architecture/storage.md` to include deletion.
- [x] **Step 4: Write repository, artifact repository, and upload route tests** named `test_create_job_accepts_preallocated_id_and_connection`, `test_artifact_insert_binds_all_metadata`, `test_upload_registers_job_and_source_artifact`, `test_upload_uses_generated_filename_not_client_path`, `test_upload_ignores_client_content_type`, `test_upload_rejects_unsupported_extension`, `test_upload_rejects_unexpected_multipart_field`, `test_upload_rejects_duplicate_multipart_fields`, `test_upload_rejects_file_field_as_text`, `test_upload_rejects_invalid_target_instrument`, `test_upload_rejects_more_than_configured_limit`, `test_upload_rejects_declared_length_over_limit_before_reading`, `test_upload_rejects_body_larger_than_declared_content_length`, `test_upload_rejects_chunked_body_over_limit_before_form_spooling`, `test_upload_rejects_oversized_body_for_unsupported_content_type`, `test_upload_rolls_back_metadata_and_deletes_file_on_db_failure`, `test_upload_cancellation_attempts_file_cleanup`, `test_upload_cancellation_during_storage_write_cleans_file`, `test_upload_cancellation_during_commit_preserves_committed_artifact` (including repeated cancellation while awaiting transaction outcome), `test_upload_storage_cleanup_failure_preserves_primary_error`, `test_upload_storage_failure_creates_no_database_rows`, `test_upload_response_never_exposes_storage_uri`, and `test_upload_limit_setting_must_be_a_positive_integer`.
- [x] **Step 5: Run focused API tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_artifact_repository.py services/api/tests/test_job_uploads.py -q`; confirm RED because the repository and route do not exist.
- [x] **Step 6: Align nullable artifact producer fields with the PostgreSQL schema in `ArtifactRef` and `docs/domain/artifacts.md`. Add `python-multipart` to the API project and lockfile. Implement an ASGI body limiter for only the upload route: reject declared `Content-Length` above `MAX_UPLOAD_BYTES + 64 KiB` before parsing, count received bytes regardless of that header, and drain any unread body before returning the captured route response so unsupported content types cannot bypass the cap. Restrict multipart parser limits to one file and one text field; reject duplicates, unknown fields, or wrong field types. Cap the request at `MAX_UPLOAD_BYTES + 64 KiB`, and enforce the file limit again while copying to LocalStorage. Add config default `104857600`, allowed suffix validation, server-generated `source_original{suffix}`, source `ArtifactRef`, and job+artifact inserts within one PostgreSQL transaction.** Check the pool before writing bytes. Run synchronous storage writes and compensation deletes in worker threads. If request cancellation occurs during a write, wait for the write to finish, complete file cleanup despite cancellation, and re-raise cancellation. Run the metadata transaction in a shielded task; after caller cancellation, await its known outcome, preserve the file only after commit, and otherwise attempt cleanup. If any exception occurs after the file is stored but before metadata commit, let the DB transaction roll back, complete best-effort deletion before propagating the original exception, and log only one fixed generic warning if cleanup fails. Do not trust client path or MIME claims.
- [x] **Step 7: Run focused API/storage tests plus the full API suite and root storage/schema suite:** `uv run --project services/api --python 3.13 pytest services/api/tests -q`; `uv run --project . --python 3.13 pytest tests/unit/test_storage.py tests/unit/test_schemas.py -q`. Expected: all pass; `python-multipart` is the only new runtime dependency and is confined to the API project.
- [x] **Step 8: Write the task report, update main-spec Reports index, run `git diff --check`, and complete an independent code review. Require 95/100 and no blocker/important finding before Task 3. Commit only Task 2 files.** Independent review: **97/100**, no unresolved blocker/important finding; recorded below. Task 2 committed separately.

**Task 2 independent code review record:**

- Review 1 (2026-09-28): 87/100. Important findings: synchronous storage I/O blocked the event loop, and oversized unread bodies with unsupported content types bypassed byte counting. Minor finding: parser limits were wider than the route contract. All three were fixed with worker-thread I/O, response-held body draining, and one-file/one-field parser limits.
- Review 2 (2026-09-28): 96/100, held at the gate for a plan/report mismatch: cancellation during metadata commit could preserve a committed job even though the client received cancellation. Added the outcome contract to Plan Revision 6 and the report, then added a repeated-cancellation commit regression test.
- Final review (2026-09-28): **97/100**. Behavior 25/25, errors/security 25/25, tests/evidence 24/25, structure/dependencies 15/15, documentation/reproducibility 8/10. No unresolved blocker or important finding. The reviewer independently confirmed Revision 6 at 99/100. Evidence: API 129 passed/9 skipped; root storage/schema 53 passed/4 skipped; API lock check and diff check passed.

### Task 3: Cancellation, artifact listing/download, integration proof, and completion docs

**Files:**
- Modify: `docs/plans/job-rest-api-v1-implementation-plan.md` (task checklist and independent review record)
- Modify: `services/api/src/musicsheet_api/jobs/repository.py`
- Modify: `services/api/tests/test_job_repository.py`
- Modify: `services/api/src/musicsheet_api/jobs/artifacts.py`
- Modify: `services/api/src/musicsheet_api/jobs/schemas.py`
- Modify: `services/api/src/musicsheet_api/jobs/router.py`
- Modify: `services/api/src/musicsheet_api/app.py`
- Modify: `services/api/tests/test_job_routes.py`
- Modify: `services/api/tests/test_job_uploads.py`
- Modify: `services/api/tests/integration/test_postgres_persistence.py`
- Modify: `services/api/README.md`
- Modify: `docs/backend/database.md`
- Modify: `docs/backend/api.md`
- Modify: `docs/main_spec.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/backlog.md`
- Modify: `docs/completed-work.md`
- Create: `docs/reports/job-rest-api-v1-implementation-report.md`

**Interfaces:** consumes Tasks 1–2; produces `request_cancel`, artifact list/download routes, finalized API docs, and the W01 result report.

- [x] **Step 1: Write cancellation tests** named `test_cancel_pending_job_sets_cancel_requested`, `test_cancel_running_and_retrying_jobs_is_allowed`, `test_cancel_request_is_idempotent`, `test_cancel_terminal_job_returns_conflict`, `test_cancel_unknown_job_returns_404`, and `test_concurrent_cancel_does_not_overwrite_terminal_state`; add focused repository tests in `services/api/tests/test_job_repository.py` and route tests in `test_job_routes.py`.
- [x] **Step 2: Run the focused cancellation tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_routes.py -q`; confirmed RED because DELETE returned 405 and the repository method did not exist.
- [x] **Step 3: Implement an atomic cancel request** that changes only PENDING/RUNNING/RETRYING, preserves progress, updates `updated_at`, returns current `CANCEL_REQUESTED` idempotently, maps terminal state to 409, and missing state to 404.
- [x] **Step 4: Write artifact tests** named `test_artifact_list_is_scoped_to_job_and_omits_uri`, `test_known_job_without_artifacts_returns_empty_list`, `test_unknown_job_artifact_list_returns_404`, `test_download_streams_bytes_and_safe_filename`, `test_download_rejects_artifact_from_another_job`, `test_download_of_missing_storage_file_returns_404`, and `test_download_closes_stream_when_read_fails`; assert the response never contains an absolute path or `file://` URI and that streams close on completion/error.
- [x] **Step 5: Implement the public artifact response, list route, and streaming download route.** Verified the job exists before listing so an empty list means a known job with no artifacts. The download query is scoped by both IDs, uses `ArtifactStorage.open_read`, closes the stream on completion/error, sanitizes `Content-Disposition`, and reports the recorded `Content-Length`. A mid-stream storage read failure logs only a fixed generic warning and ends the response so clients can detect a truncated body without exposing storage exceptions or paths.
- [x] **Step 6: Add opt-in PostgreSQL API integration coverage** named `test_job_rest_api_persists_youtube_upload_artifact_and_cancellation` in the existing `services/api/tests/integration/test_postgres_persistence.py`, using its `musicsheet_test` database name/comment guard and migration fixtures. Passed the guarded URL as the test app's `DATABASE_URL` setting to `TestClient`. Submitted the exact supplied YouTube URL, read the resulting row back, asserted the canonical URL/default status, and exercised uploaded artifact metadata/download and repeated cancellation. The test does not contact YouTube. The suite passed with the marked disposable PostgreSQL database (10 passed) and safely skipped when the variable was unset (10 skipped).
- [x] **Step 7: Finalize `docs/backend/api.md`, `docs/backend/database.md`, API README, main spec status/report indexes, and move W01 from roadmap In Progress to completed-work; keep W02 as the next candidate.** Updated the repository capability summary and API contract. Jobs remain PENDING until Celery dispatch is implemented; W01 does not fetch media. W02 is now the next candidate.
- [x] **Step 8: Run final checks:** API `uv lock --check` and API full suite with `MUSICSHEET_TEST_DATABASE_URL` unset; root `uv lock --check`, root full suite, and `git diff --check`; then run the opt-in PostgreSQL API integration suite only against the guarded database. Confirmed root `pyproject.toml`/`uv.lock` are unchanged. Results: API 151 passed/10 skipped, root 59 passed/4 skipped/4 deselected, guarded PostgreSQL 10 passed, both lock checks and diff check passed.
- [ ] **Step 9: Complete an independent code review of Task 3, resolve/review until 95/100 with no blocker/important finding, stage only W01 files, and commit with a Conventional Commit message.** Final independent review: **96/100**, no unresolved blocker/important finding. Minor cancellation/read-close race recorded as deferred in the report. Commit after final staging.

**Task 3 independent code review record:**

- Final review (2026-09-28): **96/100**. Behavior 25/25, errors/security 24/25, tests/evidence 24/25, structure/dependencies 14/15, docs/reproducibility 9/10. No unresolved blocker or important finding. The initial important finding about raw mid-stream storage exceptions was fixed by logging only a generic warning, terminating the stream with the persisted `Content-Length`, and verifying stream closure plus no backend exception/path leakage. Deferred minor: a response cancellation can race a worker-thread read against stream close; assessed low risk for the current local-file backend.

## Acceptance Criteria

- The supplied short URL registers as a YOUTUBE job and is stored as `https://www.youtube.com/watch?v=A9x7du4921A`; registration tests perform no network access.
- YouTube jobs have PENDING/DOWNLOAD/zero-progress defaults and can be read by ID; unknown IDs return 404.
- Upload accepts only the documented extensions and configured byte limit, stores bytes under a generated safe name, and persists the job and `SOURCE_ORIGINAL` artifact metadata together.
- Caught DB failure after file storage rolls back both metadata rows and attempts to delete the stored file; no local path is returned to clients.
- Cancellation semantics match the Interfaces section and use an atomic update.
- Artifact list/download is scoped to the requested job and streams bytes without exposing local URIs.
- Existing health and PostgreSQL migration/repository behavior remains unchanged; all API/root suites and guarded PostgreSQL integration checks pass, or any unavailable live check is reported as unverified.
- No Celery task dispatch, SSE route, YouTube fetch, model execution, or render is added. The only new runtime dependency is API-local `python-multipart`; root dependencies and lockfile remain unchanged.
- Independent plan score and every task review score are at least 95/100, with no unresolved blocker/important findings.




