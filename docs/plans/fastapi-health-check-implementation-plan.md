# FastAPI Health Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three documented health endpoints in a standalone Python 3.13 FastAPI project, with database/Redis/storage readiness checks and best-effort host diagnostics.

**Architecture:** `services/api` is an independent uv project inside the existing Git monorepo. Its app factory exposes liveness, readiness and diagnostic routes; dependency probes are behind an injectable interface so route and failure behavior can be tested without live services. The API consumes the existing common and storage packages through editable local sources.

**Tech Stack:** Python 3.13, uv, FastAPI, asyncpg, redis-py asyncio, existing `musicsheet-common` and `musicsheet-storage`, pytest, FastAPI TestClient.

**Spec:** [Health Check & Model Prefetch](../infrastructure/health-check.md), [FastAPI Gateway](../backend/api.md), [Repository and uv Environment Structure](repository-and-uv-environment-structure-plan.md)

## Plan Review Gate

- Plan revision: 4 — independently reviewed 97/100 and passed; no unresolved blocker/important findings.
- Review criteria and required recording follow [AGENTS.md](../../AGENTS.md). Plan score and implementation code review score are separate gates.
- Each implementation task ends with an independent code review. Do not start the next task until that review scores at least 95/100; fix and re-review below threshold.

### Plan Review Record

- Revision 1: 95/100 on 2026-09-27. Review findings: include GPU driver version in the diagnostic contract; exercise temporary-file cleanup after a timed-out storage probe; add a code-review scoring rubric; keep roadmap Planned until this gate passes. Addressed in revision 2. This passing score does not transfer to revision 2.
- Revision 2: 94/100 on 2026-09-27. The reviewer found the plan omitted resolution and test coverage for arbitrary relative `LOCAL_STORAGE_DIR` values and did not name a nonzero diagnostic-command exit test. Addressed in revision 3. This score does not transfer to revision 3.
- Revision 3: 93/100 on 2026-09-27. The reviewer found the plan omitted the `LOCAL_STORAGE_DIR=outputs` default and did not distinguish missing DB/Redis settings from the storage default. Addressed in revision 4. This score does not transfer to revision 4.
- Revision 4: 97/100 on 2026-09-27 by an independent reviewer. Breakdown: spec coverage 25/25; scope/interfaces 19/20; sequencing 20/20; verification/failure cases 24/25; operations/docs 9/10. No unresolved blocker or important finding; implementation gate passed.

## Global Constraints

- Keep the root Python 3.13 uv workspace and lockfile unchanged for API-only dependencies.
- `services/api` uses Python `>=3.13,<3.14`, its own `pyproject.toml`, `uv.lock`, and `.venv`, and must not become a root workspace member.
- API imports `musicsheet-common` and `musicsheet-storage` from editable monorepo path sources; no API code is added to either package.
- `/health/live` never contacts a dependency. GPU, FFmpeg, and MuseScore diagnostics never affect `/health/ready`.
- Readiness response must not expose credentials, DSNs, file paths, or raw exception text.
- External checks have bounded timeouts; a failed dependency check returns a result instead of preventing API startup.
- Read `DATABASE_URL` and `REDIS_URL` from process environment; if either is absent or invalid, mark only that dependency unavailable. Read `LOCAL_STORAGE_DIR` from process environment with default `outputs`; resolve every relative value against the API working directory (`Path.cwd()`) when settings are built and leave absolute paths unchanged. Optional `NVIDIA_SMI_BIN`, `FFMPEG_BIN`, and `MUSESCORE_BIN` override diagnostic executable discovery.

## File Map

- `services/api/pyproject.toml`, `.python-version`, `uv.lock`: standalone Python 3.13 API project and locked dependencies.
- `services/api/src/musicsheet_api/config.py`: environment-backed API settings and diagnostic executable overrides.
- `services/api/src/musicsheet_api/app.py`: app factory, lifespan cleanup and the three route registrations.
- `services/api/src/musicsheet_api/health.py`: readiness result contract and injectable health-check interface.
- `services/api/src/musicsheet_api/probes.py`: PostgreSQL, Redis and LocalStorage readiness probes.
- `services/api/src/musicsheet_api/diagnostics.py`: bounded host tool discovery and version/GPU information parsing.
- `services/api/tests/`: route status, probe failures, timeouts, non-disclosure and diagnostic edge cases.
- `services/api/README.md`: environment sync, server launch and endpoint behavior.
- `docs/infrastructure/health-check.md`: canonical response and check contract.
- `docs/roadmap.md`, `docs/main_spec.md`, `docs/reports/fastapi-health-check-implementation-report.md`: status, index and completion evidence.

## Tasks

### Task 1: Standalone API project and liveness

- [x] From the repository root run `uv init --package --no-workspace --python 3.13 services/api`; confirm the new project has `requires-python = ">=3.13,<3.14"` and a `.python-version` selecting 3.13.
- [x] From `services/api`, add runtime dependencies `fastapi`, `uvicorn`, `asyncpg`, and `redis`; add dev dependencies `pytest` and `httpx`; add `../../packages/common` and `../../packages/storage` as editable `--no-workspace` path dependencies.
- [x] Add `tests/test_app.py` for `GET /health/live`, including an injected health-check fake that raises if called; run `uv run --project . --python 3.13 pytest tests/test_app.py -q` and confirm it fails because the app/route is absent.
- [x] Add `tests/test_config.py::test_relative_storage_dir_resolves_from_working_directory` and `test_storage_dir_defaults_to_outputs`; use an injected working directory and verify a relative `LOCAL_STORAGE_DIR` becomes an absolute child path, an absolute path stays unchanged, and an unset variable resolves to `<working-directory>/outputs`. Confirm the tests fail before config path resolution/defaulting exists.
- [x] Implement `musicsheet_api.app.create_app()` and export `app` for uvicorn. Make `/health/live` return HTTP 200 and `{"status":"ok"}` without creating dependency clients or running diagnostic commands.
- [x] Implement settings for `DATABASE_URL`, `REDIS_URL`, and `LOCAL_STORAGE_DIR`; resolve relative storage values against `Path.cwd()` at settings construction. Add optional diagnostic command overrides from the process environment.
- [x] Run `uv lock --check`, `uv sync --locked --python 3.13`, and `uv run --project . --python 3.13 pytest -q` from `services/api`. Confirm root `pyproject.toml` and `uv.lock` are unchanged and root `testpaths = ["tests"]` does not collect `services/api/tests`.
- **Completion evidence:** RED confirmed missing API and config modules. The first GREEN run passed 6 tests; after review feedback, an empty-storage regression test first failed as expected and then the API suite passed 8 tests. Root suite passed 54, skipped 3, deselected 4. Standalone lock tree includes editable common/storage packages; root lockfiles remain unchanged. Independent review 1 scored 95/100 and review 2 after the settings fixes scored 98/100; neither found blocker/important issues. Task 1 passed its review gate. TestClient currently emits one Starlette deprecation warning because the plan's `httpx` dev dependency is used instead of `httpx2`; this remains a low-priority minor. The README remains scheduled for Task 4.

#### Task 1 code review record

- Review 1: 95/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 24/25; tests/evidence 24/25; structure/dependencies 15/15; docs/reproducibility 7/10. No blocker/important findings. Minor findings: blank `LOCAL_STORAGE_DIR` selected the working directory instead of `outputs`; direct non-empty DB/Redis URL tests were missing; README is deferred to Task 4; Starlette warns about the planned `httpx` test dependency. The first two findings were fixed and tested; requested re-review before advancing.
- Review 2: 98/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 25/25; tests/evidence 24/25; structure/dependencies 15/15; docs/reproducibility 9/10. The two settings findings were confirmed fixed; no blocker/important findings remain. The `httpx` deprecation warning remains low priority. Gate passed.

### Task 2: Readiness checks

- [x] Add tests `test_ready_all_dependencies_healthy`, `test_ready_reports_each_dependency_failure`, `test_ready_bounds_slow_dependency`, `test_storage_probe_removes_temporary_file_on_failure`, `test_storage_probe_cleans_temporary_file_after_timeout_worker_finishes`, and `test_ready_does_not_expose_secrets_or_paths`; confirm the focused tests fail before readiness implementation.
- [x] Implement async PostgreSQL `SELECT 1` and Redis `PING` probes with a one-second end-to-end timeout. Ensure network outages and invalid/missing DB or Redis settings become per-check `unavailable` results instead of app startup failures. An unset `LOCAL_STORAGE_DIR` uses the `outputs` default; a configured but unusable storage path becomes `unavailable`.
- [x] Reuse one `redis.asyncio.Redis` client for app lifetime and close it at shutdown. Open and close the PostgreSQL connection within its bounded readiness probe.
- [x] Implement the LocalStorage write probe using the resolved storage path: create the configured root if needed; create, write, and remove a uniquely named temporary file in that root; run filesystem operations outside the event loop and bound the probe to one second.
- [x] Execute all three probes concurrently. Return HTTP 200 only when every check is `ok`, otherwise 503. Serialize only the check names/statuses and never connection strings, paths, or exception text.
- [x] Run focused readiness tests followed by `uv run --project . --python 3.13 pytest -q` from `services/api`.
- **Completion evidence:** focused readiness tests passed; after review follow-up coverage, the full API suite passed 22 tests and the root suite passed 54 (3 skipped, 4 deselected). The API lock check and `git diff --check` passed; root lockfiles remain unchanged. Missing and invalid DB/Redis config do not prevent liveness startup. Independent review 1 scored 97/100; review 2 after its test-coverage suggestions scored 99/100. Neither found blocker/important issues; Task 2 passed its review gate.

#### Task 2 code review record

- Review 1: 97/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 25/25; tests/evidence 23/25; structure/dependencies 15/15; docs/reproducibility 9/10. No blocker/important findings. Minor test-coverage suggestions: directly verify slow Redis `PING` isolation and Redis client-construction exceptions. Added both tests; full API suite now passes 22 tests. Re-review pending before Task 3.
- Review 2: 99/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 25/25; tests/evidence 25/25; structure/dependencies 15/15; docs/reproducibility 9/10. Both suggested Redis edge tests were confirmed. No blocker/important/minor findings; gate passed.

### Task 3: Host diagnostics

- [x] Add tests `test_detail_reports_gpu_driver_and_tool_versions`, `test_detail_returns_unavailable_for_missing_tools`, `test_detail_reports_nonzero_command_exit_as_unavailable`, `test_detail_bounds_hung_command`, `test_detail_handles_bad_gpu_output`, and `test_detail_failure_does_not_change_readiness`; confirm they fail before the diagnostic adapter exists.
- [x] Implement `nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader,nounits`, `ffmpeg -version`, and MuseScore `--version` probes. Use optional `NVIDIA_SMI_BIN`, `FFMPEG_BIN`, `MUSESCORE_BIN` overrides; search `PATH` when unset.
- [x] Run blocking commands off the event loop and enforce a two-second timeout per command. Parse only GPU summary fields and first version line; omit command paths and raw stderr/stdout from JSON.
- [x] Return partial diagnostic results with per-tool `unavailable` status for missing command, nonzero exit, malformed output, or timeout; keep `/health/detail` HTTP 200 and do not import torch/CUDA/model packages into the API project.
- [x] Run focused diagnostic tests followed by the full API project suite.
- **Completion evidence:** focused diagnostic tests passed; after reviewer-suggested executable override coverage, the full API suite passed 29 tests and the root suite passed 54 (3 skipped, 4 deselected). The API lock check and `git diff --check` passed; root lockfiles remain unchanged. Diagnostics failures return partial unavailable statuses and do not affect readiness. Independent review 1 scored 98/100 and review 2 after added override coverage scored 99/100; neither found unresolved blocker/important issues. Task 3 passed its review gate.

#### Task 3 code review record

- Review 1: 98/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 25/25; tests/evidence 24/25; structure/dependencies 15/15; docs/reproducibility 9/10. No blocker/important findings. Minor test-coverage suggestion: verify the three executable override values reach PATH lookup and the command runner. Added `test_detail_uses_configured_executable_overrides`; API suite now passes 29 tests. Re-review pending before Task 4.
- Review 2: 99/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 25/25; tests/evidence 25/25; structure/dependencies 15/15; docs/reproducibility 9/10. Executable override coverage was confirmed; no blocker/important/minor findings remain. Gate passed.

### Task 4: End-to-end validation and operating docs

- [x] Add `services/api/README.md` with locked install, loopback server command, endpoint request/response examples and readiness/detail semantics.
- [x] Through FastAPI TestClient, verify the three real route paths, payloads and status codes with injected checks; verify diagnostic failure does not change readiness. The configured Compose file was found, but the Docker Desktop Linux Engine pipe was unavailable, so a manual request could not run; record this limitation.
- [x] Update canonical health-check implementation status, the `docs/roadmap.md` row and the `docs/main_spec.md` Reports index. Write `docs/reports/fastapi-health-check-implementation-report.md` with Python/uv/package versions, exact commands/results, endpoint contract and limitations.
- [x] Run `uv run --project . pytest -q` from repository root; run `uv run --project . --python 3.13 pytest -q` from `services/api`; run `git diff --check`.
- **Completion evidence:** root and API suites passed (54 passed/3 skipped/4 deselected; 30 passed), API lock check and diff check passed, root lockfiles remain unchanged, canonical docs match behavior, and the report is indexed. Compose-based manual readiness was unavailable because the Docker engine named pipe was absent. Whole-change review 1 scored 96/100; review 2 after doc corrections scored 98/100. Both found no unresolved blocker/important issue, and review 2 found no unresolved minor. The non-cancellable filesystem worker timeout remains a documented operational limitation. Task 4 passed its final review gate and the roadmap may be marked Done.

#### Task 4 whole-change code review record

- Review 1: 96/100, independent reviewer, 2026-09-27. Breakdown: external behavior 24/25; errors/security 24/25; tests/evidence 24/25; structure/dependencies 15/15; docs/reproducibility 9/10. No blocker/important findings. Minor findings: the endpoint table overstated remote worker/CUDA scope, and a permanently blocked filesystem operation can leave a `to_thread` worker and temporary file after the 1-second response. Corrected the table and documented the accepted timeout limitation in the canonical spec, README, and report. Re-review pending.
- Review 2: 98/100, independent reviewer, 2026-09-27. Breakdown: external behavior 25/25; errors/security 24/25; tests/evidence 24/25; structure/dependencies 15/15; docs/reproducibility 10/10. The API-host diagnostic scope and filesystem timeout limitation match the implementation. No blocker/important/minor findings remain; final gate passed.

## Review Focus

- PostgreSQL or Redis is unavailable during app startup: liveness remains available and readiness reports only that dependency as unavailable.
- A readiness probe times out or storage write fails: the response is bounded and status is 503; after a delayed filesystem worker exits, its temporary file is removed.
- `nvidia-smi`, FFmpeg or MuseScore is absent or hangs: detail returns partial results within the command timeout and readiness remains unchanged.
- Error objects contain secret connection strings or host paths: none appear in public JSON.
- API uv project resolution attempts to join the root workspace or modifies root `uv.lock`: reject and correct the setup before proceeding.
