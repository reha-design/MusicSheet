# W04 Basic Pitch `TRANSCRIBE` Pipeline Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Tasks use checkbox (`- [ ]`) syntax. Stop after each task for independent code review; continue only at 95/100 or higher with no unresolved blocker/important findings.

**Goal:** Connect the existing isolated Basic Pitch worker to W03's `TRANSCRIBE` stage and register validated JSON and MIDI outputs as job artifacts.

**Architecture:** Keep API/Celery orchestration in Python 3.13 and invoke the installed Python 3.12 Basic Pitch CLI as a bounded subprocess. Give the synchronous handler a narrow artifact-publisher port that bridges filesystem writes to one PostgreSQL metadata transaction; validate and reuse a complete existing output pair on redelivery.

**Tech Stack:** Python 3.13, uv, FastAPI/Celery API package, Python 3.12 Basic Pitch ONNX worker, Pydantic `TranscriptionResult`, `ArtifactStorage`/`LocalStorage`, asyncpg, pytest.

**Spec:** [W04 Basic Pitch TRANSCRIBE integration design](../superpowers/specs/2026-10-01-basic-pitch-pipeline-integration-design.md)

**Execution method:** Native/current session, as previously requested. No subagents.

**Plan review:** Version 1, written 2026-10-01. Independent reviewer score and findings are pending; no implementation may start until the current version scores at least 95/100 with no unresolved blocker/important findings.

## Global Constraints

- API and Celery remain Python `>=3.13,<3.14`; the Basic Pitch worker remains its isolated Python `>=3.12,<3.13` project.
- Implement only `PipelineStage.TRANSCRIBE`; require exactly one `MODEL_INPUT` artifact named `amt_22k_mono.wav`.
- Invoke the configured worker executable with an argument list and `shell=False`; default timeout is 300 seconds and process polling is once per second.
- Require schema version 1 `spotify-basic-pitch` JSON and a nonempty Standard MIDI file; register `RAW_TRANSCRIPTION/raw_transcription.json` and `MIDI/transcription.mid`.
- Never expose worker stderr, absolute paths, user input, or raw exception strings in job errors or progress events.
- Reuse prior outputs only when both metadata rows, files, SHA-256 values, producer, names, and contracts validate; otherwise fail closed on conflicts.
- Do not add a database migration, public API, upstream-stage handler, daemon/RPC service, provider-selection behavior, or Linux/macOS support claim.
- Preserve W03's task lifecycle, stable stage error codes, cancellation behavior, and stage lock.
- After every implementation task, obtain an independent code review of that task's exact diff. Record reviewer, date, score, scope, findings, and dispositions before starting the next task. A score below 95 or unresolved blocker/important finding requires fixes and re-review.

## Review Focus

1. **MODEL_INPUT ambiguity:** missing, duplicate, wrong-role, or wrong-name `amt_22k_mono.wav` artifacts must fail with `BASIC_PITCH_INPUT_INVALID`; pin this in Task 3.
2. **Untrusted stored paths:** an artifact URI or filename resolving outside LocalStorage must be rejected without reading/writing outside the job root; pin this in Task 3.
3. **Executable path injection:** executable paths containing spaces or shell metacharacters must remain a single argv item and never use a shell; pin this in Task 1.
4. **Child survival on cancellation/timeout:** a worker that ignores terminate must be killed after the grace period, and output publication must not start; pin this in Task 1 and Task 3.
5. **Corrupt or conflicting outputs:** unsupported provider/schema, missing MIDI, invalid MIDI header, partial metadata, or a hash mismatch must not be accepted or overwritten; pin this in Task 3.

## File Map

- `services/api/src/musicsheet_api/config.py` — worker executable and timeout settings.
- `services/api/src/musicsheet_api/pipeline/basic_pitch_worker.py` — bounded subprocess runner and safe process cleanup.
- `services/api/src/musicsheet_api/pipeline/workflow.py` — immutable output descriptor, publisher protocol, and optional publisher field on `StageContext`.
- `services/api/src/musicsheet_api/pipeline/artifacts.py` — synchronous stage artifact publisher; storage writes and loop-safe atomic metadata registration.
- `services/api/src/musicsheet_api/pipeline/basic_pitch.py` — Basic Pitch input selection, output validation, idempotency, and handler implementation.
- `services/api/src/musicsheet_api/pipeline/tasks.py` — create runtime storage/publisher, pass publisher into `StageContext`, and supply the default W04 handler while retaining explicit test/extension overrides.
- `services/api/tests/test_config.py` — configuration defaults and invalid-value coverage.
- `services/api/tests/test_pipeline_worker_process.py` — subprocess argv, exit, timeout, cancellation, and cleanup behavior.
- `services/api/tests/test_pipeline_artifacts.py` — storage/metadata transaction and compensation behavior.
- `services/api/tests/test_pipeline_basic_pitch.py` — stage handler contract, error mapping, idempotency, and boundary inputs.
- `services/api/tests/test_pipeline_tasks.py` and `services/api/tests/test_pipeline_workflow.py` — runtime construction and task-context regression coverage.
- `services/api/tests/integration/test_basic_pitch_artifact_publication.py` — opt-in PostgreSQL atomic registration/rollback proof.
- `services/api/tests/integration/test_basic_pitch_pipeline.py` — opt-in real Python 3.12 worker through the API handler using the CC0 fixture and temporary LocalStorage.
- `services/api/pyproject.toml` — register the `ml_integration` marker and exclude it from the default API test run.
- `docs/ai/transcription.md`, `docs/ai/model-adapters.md`, `docs/architecture/job-pipeline.md`, `docs/infrastructure/runtime.md` — update the canonical integration state and worker settings.
- `docs/backlog.md`, `docs/roadmap.md`, `docs/completed-work.md`, `docs/reports/basic-pitch-pipeline-integration-report.md`, `docs/main_spec.md` — close out W04 only after code review and verification pass.

---

### Task 1: Worker configuration and bounded subprocess runner

**Files:**
- Modify: `services/api/src/musicsheet_api/config.py`
- Create: `services/api/src/musicsheet_api/pipeline/basic_pitch_worker.py`
- Test: `services/api/tests/test_config.py`
- Test: `services/api/tests/test_pipeline_worker_process.py`

**Interfaces:**
- Produces settings fields `basic_pitch_worker_executable: Path` and `basic_pitch_worker_timeout_seconds: int`.
- Produces `BasicPitchWorkerRunner(executable: Path, timeout_seconds: int, *, popen_factory: Callable[..., Popen])` with `run(input_audio: Path, output_dir: Path, report_progress: Callable[[int], None]) -> int`.
- Produces `WorkerExecutableError(RuntimeError)` and `WorkerTimeoutError(TimeoutError)`; `run` returns the worker exit code and raises these typed errors without exposing process output. The callback is polled every second; cancellation exceptions propagate only after the child is stopped.

- [ ] **Step 1: Add failing configuration tests**
  - In `test_config.py`, assert the default executable resolves under the configured working directory to `services/ml/basic-pitch-worker/.venv/Scripts/basic-pitch-worker.exe` and timeout defaults to `300`.
  - Assert `BASIC_PITCH_WORKER_EXECUTABLE` overrides the default and `BASIC_PITCH_WORKER_TIMEOUT_SECONDS` parses a positive integer.
  - Parameterize `0`, `-1`, and nonnumeric timeout values; require `ValueError` naming `BASIC_PITCH_WORKER_TIMEOUT_SECONDS`.

- [ ] **Step 2: Run the configuration tests and confirm the new-field failures**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_config.py -q`

Expected: FAIL because the two settings fields and parsing are not implemented.

- [ ] **Step 3: Implement configuration parsing**
  - Add the two immutable `Settings` fields and the environment parsing/defaults above.
  - Resolve relative executable paths from `working_directory`, as `local_storage_dir` does; do not check for executable existence while constructing general API settings.

- [ ] **Step 4: Add failing subprocess-runner tests**
  - Test exact argv order: executable, `--input-audio`, input path, `--output-dir`, output path; assert `shell=False`, stdout/stderr are not captured into job-visible output, and a path containing spaces/metacharacters remains one argv value.
  - Test return-code propagation for `0`, `2`, `3`, and `4`.
  - Test spawn `OSError` maps to `WorkerExecutableError`, timeout raises `WorkerTimeoutError` after terminating then killing an unresponsive process, and a cancellation/error from `report_progress` also stops the child before propagating.
  - Test progress stays within 10–90 and polling uses the one-second interval.

- [ ] **Step 5: Run runner tests and confirm expected failures**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_worker_process.py -q`

Expected: FAIL because `basic_pitch_worker.py` does not exist.

- [ ] **Step 6: Implement `BasicPitchWorkerRunner`**
  - Use `subprocess.Popen` with an argv list and `shell=False`; poll with a monotonic clock; on timeout/callback failure terminate, wait a bounded grace interval, then kill and reap the process.
  - Use no shell wrapper such as `uv run`, so process cancellation targets the actual worker executable. Do not include stdout/stderr text in raised exceptions.

- [ ] **Step 7: Run Task 1 tests and commit**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_config.py services/api/tests/test_pipeline_worker_process.py -q`

Expected: PASS.

Commit after the independent Task 1 review passes: `feat(api): add bounded Basic Pitch worker runner`.

**Review gate:** Record the independent Task 1 code-review score/date/scope/findings in the review table below. Do not start Task 2 until score >=95 and no blocker/important findings remain.

---

### Task 2: Stage artifact publication port and transaction adapter

**Files:**
- Modify: `services/api/src/musicsheet_api/pipeline/workflow.py`
- Create: `services/api/src/musicsheet_api/pipeline/artifacts.py`
- Test: `services/api/tests/test_pipeline_workflow.py`
- Test: `services/api/tests/test_pipeline_artifacts.py`

**Interfaces:**
- Add immutable `StageArtifactOutput(path: Path, role: ArtifactRole, filename: str, producer: str, producer_version: str)`.
- Add `StageArtifactPublisher.publish(job_id: str, outputs: Sequence[StageArtifactOutput]) -> tuple[ArtifactRecord, ...]` protocol.
- Add `artifact_publisher: StageArtifactPublisher | None = None` to `StageContext` so existing non-W04 handlers and constructors remain compatible.
- Produce `LocalStageArtifactPublisher(storage: ArtifactStorage, repository: ArtifactRepository, pool: asyncpg.Pool, loop: AbstractEventLoop)` with synchronous `publish(...)` usable from the handler thread.

- [ ] **Step 1: Add failing `StageContext` compatibility tests**
  - Assert existing three-argument `StageContext(job, stage, artifacts)` construction still works with `artifact_publisher is None`.
  - Assert the publisher protocol accepts a tuple of two typed outputs and keeps paths/roles unchanged.

- [ ] **Step 2: Run workflow tests and confirm failures**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_workflow.py -q`

Expected: FAIL because output/publisher types are absent.

- [ ] **Step 3: Add failing publisher tests**
  - With a fake LocalStorage and repository/connection, assert both files are stored and both metadata inserts occur inside one transaction using `ArtifactRepository.add(..., connection=connection)`.
  - Inject a failure on the second insert; assert the transaction rolls back and every file written by this call is deleted best-effort.
  - Inject a failure while storing the second output; assert the first output file is cleaned and no DB transaction is opened.
  - Inject a transient DB/storage failure; assert a stable `RetryableStageError` code and no raw exception text.
  - Call publisher from a worker thread while the asyncio loop is running; assert the async transaction completes through `run_coroutine_threadsafe` without blocking the loop thread.

- [ ] **Step 4: Run publisher tests and confirm expected failures**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_artifacts.py -q`

Expected: FAIL because the publisher module and contract are absent.

- [ ] **Step 5: Implement the output port and concrete publisher**
  - Copy each temporary output through `ArtifactStorage.put` to the job's fixed artifact filename.
  - Register all returned `ArtifactRef` values in one acquired-connection transaction; use no schema migration or uniqueness assumption.
  - If metadata registration fails, remove only files written in this call and map transient persistence failures to a stable retryable stage code.

- [ ] **Step 6: Run Task 2 tests and commit**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_workflow.py services/api/tests/test_pipeline_artifacts.py -q`

Expected: PASS.

Commit after the independent Task 2 review passes: `feat(api): add transactional stage artifact publisher`.

**Review gate:** Record the independent Task 2 review before Task 3; score >=95 and no unresolved blocker/important finding required.

---

### Task 3: Basic Pitch handler, validation, and reentrant output behavior

**Files:**
- Create: `services/api/src/musicsheet_api/pipeline/basic_pitch.py`
- Create: `services/api/tests/test_pipeline_basic_pitch.py`

**Interfaces:**
- Produce `BasicPitchTranscriptionHandler(storage: ArtifactStorage, runner: BasicPitchWorkerRunner)` implementing `StageHandler.run(context: StageContext, report_progress: Callable[[int], None]) -> None`.
- Require `context.stage is PipelineStage.TRANSCRIBE` and a non-`None` `context.artifact_publisher` before doing work.
- Consume exactly one `MODEL_INPUT/amt_22k_mono.wav`; publish the JSON and MIDI through `context.artifact_publisher.publish(context.job.id, outputs)`.

- [ ] **Step 1: Add failing tests for input selection and materialization**
  - `test_rejects_missing_duplicate_wrong_role_and_wrong_name_model_input` expects `PermanentStageError("BASIC_PITCH_INPUT_INVALID")`.
  - `test_materializes_model_input_and_passes_private_output_directory_to_runner` verifies exact CLI input/output paths, stage, job ID, and no use of artifact URI as a command fragment.
  - `test_rejects_artifact_uri_outside_storage_root` constructs an invalid stored artifact and asserts rejection without creating/reading outside the temporary storage root.

- [ ] **Step 2: Run input tests and confirm failure**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_basic_pitch.py -q`

Expected: FAIL because the handler module does not exist.

- [ ] **Step 3: Add failing output/error tests**
  - `test_validates_json_and_midi_then_publishes_two_fixed_artifacts` asserts schema version 1, provider `spotify-basic-pitch`, no pedal support/events, MIDI `MThd`, both fixed role/name pairs, producer and package version.
  - `test_rejects_invalid_json_provider_or_midi_without_publishing` covers unsupported schema, wrong provider, `supports_pedal=True`, nonempty pedal events, missing/empty MIDI, and bad MIDI header.
  - `test_maps_worker_exit_codes_and_timeout_to_stable_stage_errors` covers exit 2 as permanent input error, exit 3/timeout as retryable inference error, exit 4 as permanent output error, and executable failure as `BASIC_PITCH_WORKER_UNAVAILABLE`.

- [ ] **Step 4: Add failing idempotency/progress tests**
  - `test_reuses_complete_hash_verified_existing_pair_without_running_worker` supplies both valid metadata rows and matching LocalStorage bytes; assert runner and publisher are not called.
  - `test_rejects_partial_corrupt_or_conflicting_existing_pair` covers a single row, wrong producer/name, missing stored file, SHA mismatch, and invalid stored JSON/MIDI; assert no overwrite/publication.
  - `test_propagates_cancellation_after_runner_stops_child_and_never_publishes` makes the progress callback raise `JobCancellationRequested`; assert no publisher call and temporary directory cleanup.

- [ ] **Step 5: Run focused tests and confirm failures**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_basic_pitch.py -q`

Expected: FAIL until handler behavior is implemented.

- [ ] **Step 6: Implement `BasicPitchTranscriptionHandler`**
  - Materialize only the validated input into a `TemporaryDirectory`; use a new child output directory; always clean up temporary files.
  - Validate JSON with `TranscriptionResult.model_validate_json`; validate the Basic Pitch-specific metadata and MIDI header; publish only after both outputs pass.
  - Verify stored hashes while checking old output pairs; skip inference only when both are complete and valid; fail closed for partial or conflicting records.
  - Map `WorkerExecutableError` to `BASIC_PITCH_WORKER_UNAVAILABLE`, `WorkerTimeoutError` and exit 3 to retryable `BASIC_PITCH_INFERENCE_FAILED`, exit 2 to permanent `BASIC_PITCH_INPUT_INVALID`, and exit 4/invalid outputs to permanent `BASIC_PITCH_OUTPUT_INVALID`; do not copy stderr or exception messages into job state.

- [ ] **Step 7: Run Task 3 tests and commit**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_basic_pitch.py -q`

Expected: PASS.

Commit after the independent Task 3 review passes: `feat(api): implement Basic Pitch transcribe handler`.

**Review gate:** Record Task 3's independent score and findings before Task 4; require >=95 and no unresolved blocker/important finding.

---

### Task 4: Celery runtime wiring and handler registration

**Files:**
- Modify: `services/api/src/musicsheet_api/pipeline/tasks.py`
- Modify: `services/api/tests/test_pipeline_tasks.py`
- Modify: `services/api/tests/test_pipeline_workflow.py` (only if context assertions need updating)

**Interfaces:**
- Extend `WorkerRuntime` with `settings: Settings`, `storage: ArtifactStorage`, and `artifact_publisher: StageArtifactPublisher`.
- Add `_handlers_for_runtime(runtime: WorkerRuntime) -> dict[PipelineStage, StageHandler]`; copy `REGISTERED_HANDLERS`, preserve any explicit `TRANSCRIBE` override, otherwise add the default `BasicPitchTranscriptionHandler(runtime.storage, BasicPitchWorkerRunner(runtime.settings.basic_pitch_worker_executable, runtime.settings.basic_pitch_worker_timeout_seconds))`.
- Build `StageContext(..., artifact_publisher=runtime.artifact_publisher)` in `_execute_stage`.

- [ ] **Step 1: Add failing runtime/task tests**
  - Assert `_worker_runtime` creates LocalStorage from `LOCAL_STORAGE_DIR` and a publisher bound to that task's pool/event loop.
  - Assert the default handler map registers `TRANSCRIBE` but leaves other unimplemented stages absent.
  - Assert an explicitly registered test/extension `TRANSCRIBE` handler is preserved and receives the publisher in its context.
  - Assert no-handler behavior for DOWNLOAD/PREPROCESS/SEPARATE/POSTPROCESS/RENDER remains `STAGE_NOT_CONFIGURED`.

- [ ] **Step 2: Run task tests and confirm failures**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_tasks.py services/api/tests/test_pipeline_workflow.py -q`

Expected: FAIL because runtime lacks storage/publisher and default W04 handler wiring.

- [ ] **Step 3: Wire only the TRANSCRIBE default**
  - Create storage and publisher inside the worker runtime lifetime so the publisher uses the same PostgreSQL pool and asyncio loop as its task.
  - Copy the override registry and set the Basic Pitch handler only when no explicit TRANSCRIBE handler is supplied.
  - Attach the publisher to each `StageContext`; do not change chain order, queue, retry policy, state transitions, or progress event schema.

- [ ] **Step 4: Run Task 4 and regression tests, then commit**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_pipeline_tasks.py services/api/tests/test_pipeline_workflow.py services/api/tests/test_pipeline_basic_pitch.py -q`

Expected: PASS; the pre-existing orchestration tests continue to pass and only TRANSCRIBE gains a default handler.

Commit after independent Task 4 review passes: `feat(api): wire Basic Pitch into transcribe stage`.

**Review gate:** Record Task 4 independent review before Task 5; require >=95 and no unresolved blocker/important finding.

---

### Task 5: Opt-in integration evidence and W04 documentation closeout

**Files:**
- Create: `services/api/tests/integration/test_basic_pitch_artifact_publication.py`
- Create: `services/api/tests/integration/test_basic_pitch_pipeline.py`
- Modify: `services/api/pyproject.toml`
- Modify: `docs/ai/transcription.md`
- Modify: `docs/ai/model-adapters.md`
- Modify: `docs/architecture/job-pipeline.md`
- Modify: `docs/infrastructure/runtime.md`
- Modify: `docs/backlog.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/completed-work.md`
- Create: `docs/reports/basic-pitch-pipeline-integration-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:**
- PostgreSQL test consumes `MUSICSHEET_TEST_DATABASE_URL`; it skips when the opt-in URL is absent and uses an isolated job ID.
- ML integration test consumes `BASIC_PITCH_WORKER_EXECUTABLE` or the configured worker default and the existing CC0 fixture; it runs only under marker `ml_integration`.
- API pytest default run excludes `ml_integration`; explicit ML command includes the marker.

- [ ] **Step 1: Add failing opt-in tests and marker**
  - PostgreSQL test asserts both `RAW_TRANSCRIPTION` and `MIDI` rows commit together, and forced failure during the second insert leaves zero output rows and cleans files.
  - Real-worker test stores the CC0 fixture as `MODEL_INPUT/amt_22k_mono.wav`, invokes the actual handler, validates both outputs and their artifact roles, then reruns with those artifacts and asserts inference is skipped.
  - Add the `ml_integration` pytest marker and default exclusion to the API project.

- [ ] **Step 2: Run the opt-in tests against safe configured environments**

Prepare the isolated worker environment once when absent: `uv sync --locked --project services/ml/basic-pitch-worker --python 3.12`

Run PostgreSQL integration when configured: `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_basic_pitch_artifact_publication.py -m integration -q`

Run real Basic Pitch integration when Python 3.12 worker is installed: `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_basic_pitch_pipeline.py -m ml_integration -q`

Expected: PostgreSQL test skips only when `MUSICSHEET_TEST_DATABASE_URL` is absent; ML test is excluded from normal API suite and runs only when explicitly selected. Any configured test must pass.

- [ ] **Step 3: Run the full required verification set**

Run: `uv run --project services/api --python 3.13 pytest services/api/tests -q`

Expected: PASS with opt-in ML test excluded by default; PostgreSQL tests follow their existing opt-in behavior.

Run: `uv run pytest`

Expected: PASS; the root suite remains independent of Python 3.12 worker dependencies.

Run: `uv lock --check`

Expected: PASS; no backend or root dependency lock change is required.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Update canonical docs and closeout records**
  - Record the handler contract and Basic Pitch integration status in the relevant AI/runtime/pipeline canonical docs; preserve the Windows-only validation boundary and state that Basic Pitch is not the default provider.
  - Mark W04 complete in backlog/roadmap/completed-work only after all available required verification and independent Task 5 review pass. Record skipped opt-in tests and their unset prerequisite honestly.
  - Write the result report with commands, environment, test counts, worker version/commit, artifact validation evidence, failure behavior, and review scores; add the report to the Main Specification index.

- [ ] **Step 5: Review doc links and closeout diff**

Run: `git diff --check`

Expected: clean diff; all new/updated documentation references resolve.

- [ ] **Step 6: Commit Task 5 after review**

Commit after independent Task 5 review passes: `docs: record W04 Basic Pitch pipeline integration`.

**Final gate:** Request an independent whole-branch review after Task 5; record its score and findings. W04 closeout is complete only when each task review and final review is >=95/100 with no unresolved blocker/important finding.

---

## Review Records

### Plan review

| Plan version | Date | Reviewer | Score / 100 | Blocker/important findings | Disposition |
|---|---|---|---:|---|---|
| v1 | 2026-10-01 | Pending independent review | Pending | Pending | Awaiting review; implementation blocked |

Plan scoring rubric required by `AGENTS.md`: requirements/spec 25, scope/interfaces 20, order/deliverables/dependencies 20, verification/failure cases 25, reproducibility/operations/docs 10. The reviewer must score this exact version; no self-estimated score is accepted.

### Implementation task reviews

| Unit | Date | Reviewed scope | Reviewer | Score / 100 | Findings and disposition |
|---|---|---|---:|---:|---|
| Task 1 | Pending | Pending | Pending | Pending | Pending |
| Task 2 | Pending | Pending | Pending | Pending | Pending |
| Task 3 | Pending | Pending | Pending | Pending | Pending |
| Task 4 | Pending | Pending | Pending | Pending | Pending |
| Task 5 | Pending | Pending | Pending | Pending | Pending |
| Whole branch | Pending | Pending | Pending | Pending | Pending |

Implementation scoring rubric required by `AGENTS.md`: external behavior 25, errors/boundaries/security 25, tests/evidence 25, structure/dependency boundaries 15, docs/reproducibility 10. A high score does not waive unresolved blocker/important findings.

## Plan Self-Review

- **Spec coverage:** Tasks 1–4 cover the worker boundary, config, stage context/publisher port, atomic metadata persistence, handler validation/idempotency/cancellation/error mapping, and default TRANSCRIBE registration. Task 5 covers opt-in PostgreSQL/real-worker evidence and all specified closeout documentation. Excluded stages and model/provider expansion stay out of scope.
- **Step scan:** Each step asks for one failing test, implementation, verification, review gate, or commit. Commands have an explicit expected outcome. Test and implementation names use the interfaces listed in the owning task.
- **Type consistency:** `StageArtifactOutput`, `StageArtifactPublisher`, `StageContext.artifact_publisher`, `LocalStageArtifactPublisher`, `BasicPitchWorkerRunner`, `BasicPitchTranscriptionHandler`, and `_handlers_for_runtime` are used consistently across tasks.
- **Review Focus coverage:** All five review-focus risks have named tests in their owning tasks: Task 1 executable/child lifecycle; Task 3 input boundaries, unsafe URI, output integrity and conflict. The publisher transaction failure is also tested in Task 2 and with opt-in PostgreSQL in Task 5.
- **Proportion:** The plan maps each of five reviewable implementation units to exact files, interfaces, tests, commands, acceptance evidence, and records. It does not include code bodies or introduce a new service/schema.
