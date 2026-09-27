# Job REST API v1 Implementation Plan

> **For agentic workers:** Use TDD for each behavior. Finish one task, record its independent 95/100 code review, and resolve blocker/important findings before the next task. Follow `superpowers:executing-plans` inline. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Expose the first user-facing API flow for registering a YouTube or uploaded audio job, checking its status, requesting cancellation, and listing/downloading its artifacts.

**Architecture:** Add a focused jobs router and request/response schemas to the existing standalone FastAPI project. PostgreSQL remains authoritative for job and artifact metadata; configured `ArtifactStorage` owns file bytes. YouTube registration canonicalizes known URL forms without network access. Upload metadata is committed in one database transaction after LocalStorage writes the file, with best-effort cleanup on a caught DB failure.

**Tech Stack:** Python 3.13, FastAPI, `python-multipart` (API-only request parsing), asyncpg, Pydantic, existing `musicsheet-common`, `musicsheet-storage`, pytest, TestClient, PostgreSQL 16 opt-in integration DB.

**Spec:** [Job REST API v1 design](../superpowers/specs/2026-09-27-job-rest-api-v1-design.md), [API Gateway](../backend/api.md), [Job State](../domain/job-state.md), [Artifacts](../domain/artifacts.md), [Storage](../architecture/storage.md), [Database](../backend/database.md)

## Global Constraints

- Keep `services/api` an independent Python `>=3.13,<3.14` uv project. Add `python-multipart` only to this API project because FastAPI multipart parsing requires it; update `services/api/uv.lock` and leave root lockfiles unchanged.
- Preserve canonical `jobs` and `artifacts` PostgreSQL columns, defaults, indexes, and foreign keys.
- Use the existing `JobStatus`, `PipelineStage`, and `ArtifactRole` enums. Align `ArtifactRef.producer` and `producer_version` to the canonical nullable PostgreSQL columns without renaming its fields.
- Never return or log DB URLs, raw driver errors, absolute storage paths, or internal artifact URIs.
- Do not contact YouTube during URL registration; the supplied URL is a deterministic fixture, not an external-network unit test.
- Do not dispatch Celery work, implement SSE, download media, run AI models, or render scores in W01.
- Upload limit defaults to 104,857,600 file bytes (100 MiB), configurable with `MAX_UPLOAD_BYTES`; accepted suffixes are `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`. Bound the complete multipart body to the file limit plus a documented 64 KiB envelope allowance so chunked requests cannot bypass the cap before file processing.

## Review Focus

1. Lookalike hostnames, malformed URL forms, tracking query parameters, and user-supplied test URL — reject unsafe forms and canonicalize valid IDs without making network requests.
2. Upload body larger than the limit, misleading filename/content type, and path-like filenames — reject unsupported/oversize inputs and never use a client path for storage.
3. DB failure after file storage or request cancellation before metadata commit — roll back job/artifact rows and attempt bounded safe file cleanup without leaking errors.
4. An artifact ID from another job, missing on-disk bytes, or DB rows with nullable producer metadata — do not disclose another artifact or local path; return stable API errors.
5. Repeated/concurrent cancellation, terminal jobs, and unknown jobs — preserve atomic, idempotent state semantics and progress fields.

## Plan Review Gate

- An independent reviewer scores the current plan revision with the five criteria in `AGENTS.md`. Implementation starts only at 95/100 or above and with no unresolved blocker/important finding.
- An independent code review scores each implementation task separately; 95/100 and no unresolved blocker/important finding are required before advancing.

### Plan Review Record

- **Revision 4: 97/100 — passed on 2026-09-27.** Independent review against `AGENTS.md`: requirements/spec 25/25, scope/interfaces 20/20, sequence/deliverables/dependencies 19/20, validation/failure coverage 23/25, reproducibility/operations/docs 10/10. No unresolved blocker or important finding. Minor review suggestions (duplicate/wrong-type multipart tests, cleanup failure preserving the primary exception, and clearing the disposable DB URL before final suites) were added to revision 4.

## Interfaces

- `normalize_youtube_url(source_url: str) -> str` in `jobs/youtube.py` accepts HTTPS `youtu.be/{id}` and watch URLs on the exact hosts `youtube.com`, `www.youtube.com`, `m.youtube.com`, and `music.youtube.com`; rejects userinfo and non-default ports; requires exactly one valid `v` parameter for watch URLs and exactly one path segment for short URLs; validates an 11-character URL-safe video ID; and returns `https://www.youtube.com/watch?v={id}`. Invalid input raises `ValueError` without network access.
- `YouTubeJobCreateRequest` contains `source_url: str` and `target_instrument: Literal["piano"] = "piano"`; the server chooses `source_type="YOUTUBE"` and does not accept `user_id`.
- `JobResponse` exposes id, source_type, source_url, target_instrument, status, current_stage, stage/overall progress, error_code, and timestamps. It omits user_id and error_message.
- `ArtifactResponse` exposes id, job_id, role, filename, mime_type, size_bytes, sha256, nullable producer/producer_version, created_at, and a relative `download_url`; it omits `uri`.
- `JobRepository.create_job(*, source_type: str, source_url: str | None, user_id: str | None = None, target_instrument: str | None = "piano", job_id: str | None = None, connection: asyncpg.Connection | None = None) -> JobRecord` remains backward-compatible. A supplied UUID and connection let upload registration insert job and artifact metadata in one DB transaction. `request_cancel(job_id: str) -> JobRecord | None` atomically requests cancellation for eligible statuses and returns the current record for an already-requested/terminal status.
- `ArtifactRecord` is a frozen API value with `id: str`, `job_id: str`, `role: ArtifactRole`, `filename: str`, `uri: str`, `mime_type: str`, `size_bytes: int`, `sha256: str`, `producer: str | None`, `producer_version: str | None`, and `created_at: datetime | None`. `ArtifactRepository.add(artifact: ArtifactRef, *, connection: asyncpg.Connection | None = None) -> ArtifactRecord`, `list_for_job(job_id: str) -> list[ArtifactRecord]`, and `get_for_job(job_id: str, artifact_id: str) -> ArtifactRecord | None` use bound SQL values.
- `ArtifactStorage.delete(artifact: ArtifactRef) -> bool` safely removes the matching artifact and is idempotent for a missing file; `LocalStorage` implements it under the existing path safety rules.
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

- [ ] **Step 1: Write LocalStorage delete tests** named `test_delete_removes_matching_artifact`, `test_delete_missing_artifact_is_idempotent`, `test_delete_rejects_forged_uri_outside_storage_root`, and `test_delete_rejects_uri_for_different_job_or_filename`, `test_delete_unlinks_in_job_symlink_without_deleting_target`; expected behavior is scoped deletion only.
- [ ] **Step 2: Run those tests** with `uv run --project . --python 3.13 pytest tests/unit/test_storage.py -q`; confirm RED on the missing interface.
- [ ] **Step 3: Add the abstract `delete(artifact) -> bool` contract and LocalStorage implementation**, validating that the URI names exactly the lexical `job_dir/filename` entry, resolving and checking the job directory but never resolving the final filename symlink, then unlinking that directory entry (so it cannot delete its target). Missing files return false; unsafe URIs raise `ValueError`. Update the abstract-method contract test and `docs/architecture/storage.md` to include deletion.
- [ ] **Step 4: Write repository, artifact repository, and upload route tests** named `test_create_job_accepts_preallocated_id_and_connection`, `test_artifact_insert_binds_all_metadata`, `test_upload_registers_job_and_source_artifact`, `test_upload_uses_generated_filename_not_client_path`, `test_upload_ignores_client_content_type`, `test_upload_rejects_unsupported_extension`, `test_upload_rejects_unexpected_multipart_field`, `test_upload_rejects_duplicate_multipart_fields`, `test_upload_rejects_file_field_as_text`, `test_upload_rejects_invalid_target_instrument`, `test_upload_rejects_more_than_configured_limit`, `test_upload_rejects_declared_length_over_limit_before_reading`, `test_upload_rejects_body_larger_than_declared_content_length`, `test_upload_rejects_chunked_body_over_limit_before_form_spooling`, `test_upload_rolls_back_metadata_and_deletes_file_on_db_failure`, `test_upload_cancellation_attempts_file_cleanup`, `test_upload_storage_cleanup_failure_preserves_primary_error`, `test_upload_storage_failure_creates_no_database_rows`, `test_upload_response_never_exposes_storage_uri`, and `test_upload_limit_setting_must_be_a_positive_integer`.
- [ ] **Step 5: Run focused API tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_artifact_repository.py services/api/tests/test_job_uploads.py -q`; confirm RED because the repository and route do not exist.
- [ ] **Step 6: Align nullable artifact producer fields with the PostgreSQL schema in `ArtifactRef` and `docs/domain/artifacts.md`. Add `python-multipart` to the API project and lockfile. Implement an ASGI body limiter for only the upload route: reject declared `Content-Length` above `MAX_UPLOAD_BYTES + 64 KiB` before parsing, then count actual received body bytes regardless of that header and reject at the same limit (cover both chunked input and a header smaller than the received body). Restrict multipart parsing to exactly one `file` and an optional `target_instrument` field; reject duplicates, unknown fields, or wrong field types. Cap the request at `MAX_UPLOAD_BYTES + 64 KiB`, and enforce the file limit again while copying to LocalStorage. Add config default `104857600`, allowed suffix validation, server-generated `source_original{suffix}`, source `ArtifactRef`, and job+artifact inserts within one PostgreSQL transaction.** Check the pool before writing bytes. If any exception, including request cancellation, occurs after the file is stored but before metadata commit, let the DB transaction roll back, then run the synchronous idempotent `ArtifactStorage.delete` compensation before the next await and re-raise the original exception. Cleanup failure is best-effort: log one fixed generic warning without paths or exception text and preserve the primary error. Do not trust client path or MIME claims.
- [ ] **Step 7: Run focused API/storage tests plus the full API suite and root storage/schema suite:** `uv run --project services/api --python 3.13 pytest services/api/tests -q`; `uv run --project . --python 3.13 pytest tests/unit/test_storage.py tests/unit/test_schemas.py -q`. Expected: all pass; `python-multipart` is the only new runtime dependency and is confined to the API project.
- [ ] **Step 8: Write the task report, update main-spec Reports index, run `git diff --check`, and complete an independent code review. Require 95/100 and no blocker/important finding before Task 3. Commit only Task 2 files.**

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

- [ ] **Step 1: Write cancellation tests** named `test_cancel_pending_job_sets_cancel_requested`, `test_cancel_running_and_retrying_jobs_is_allowed`, `test_cancel_request_is_idempotent`, `test_cancel_terminal_job_returns_conflict`, `test_cancel_unknown_job_returns_404`, and `test_concurrent_cancel_does_not_overwrite_terminal_state`; add focused repository tests in `services/api/tests/test_job_repository.py` and route tests in `test_job_routes.py`.
- [ ] **Step 2: Run the focused cancellation tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_routes.py -q`; confirm RED for missing behavior.
- [ ] **Step 3: Implement an atomic cancel request** that changes only PENDING/RUNNING/RETRYING, preserves progress, updates `updated_at`, returns current `CANCEL_REQUESTED` idempotently, maps terminal state to 409, and missing state to 404.
- [ ] **Step 4: Write artifact tests** named `test_artifact_list_is_scoped_to_job_and_omits_uri`, `test_unknown_job_artifact_list_returns_404`, `test_download_streams_bytes_and_safe_filename`, `test_download_rejects_artifact_from_another_job`, and `test_download_of_missing_storage_file_returns_404`; assert the response never contains an absolute path or `file://` URI.
- [ ] **Step 5: Implement the public artifact response, list route, and streaming download route.** Verify the job exists before listing so an empty list means a known job with no artifacts. Query by both job and artifact IDs, use `ArtifactStorage.open_read`, close the stream on completion/error, and sanitize `Content-Disposition`.
- [ ] **Step 6: Add opt-in PostgreSQL API integration coverage** in the existing `services/api/tests/integration/test_postgres_persistence.py`, using its `musicsheet_test` database name/comment guard and migration fixtures. Pass the guarded URL as the test app's `DATABASE_URL` setting to `TestClient`. Submit the exact supplied YouTube URL, read the resulting row back, and assert the canonical URL/default status; also exercise uploaded artifact metadata and cancellation. The test must not contact YouTube. First clear `MUSICSHEET_TEST_DATABASE_URL` and run the normal API suite with `uv run --project services/api --python 3.13 pytest services/api/tests -q`; then run `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_postgres_persistence.py -q` with the variable unset to verify safe skips. Run the same integration command against the marked disposable DB when available, following the exact guard/setup procedure in the [API README](../../services/api/README.md#opt-in-live-integration-tests).
- [ ] **Step 7: Finalize `docs/backend/api.md`, `docs/backend/database.md`, API README, main spec status/report indexes, and move W01 from roadmap In Progress to completed-work; keep W02 as the next candidate.** Update the database status paragraph to say `JobRepository` supports create/get/progress/cancel and `ArtifactRepository` supports transactional add plus list/get, while HTTP endpoint details stay in `docs/backend/api.md`. State explicitly that jobs remain PENDING until Celery dispatch is implemented and that no media is fetched in W01.
- [ ] **Step 8: Run final checks:** API `uv lock --check` and `uv run --project . --python 3.13 pytest -q` from `services/api`; before the final API/root suite explicitly clear `MUSICSHEET_TEST_DATABASE_URL` so the disposable-database reset fixtures cannot run accidentally. From the root run `uv lock --check`, `uv run --project . pytest -q`, and `git diff --check`; then run the opt-in PostgreSQL API integration test only against the guarded DB per the API README. Confirm root `pyproject.toml`/`uv.lock` are unchanged.
- [ ] **Step 9: Complete an independent code review of Task 3, resolve/review until 95/100 with no blocker/important finding, stage only W01 files, and commit with a Conventional Commit message.**

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




