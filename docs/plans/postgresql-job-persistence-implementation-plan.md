# PostgreSQL Job Persistence Implementation Plan

> **For agentic workers:** Execute one task at a time. After each task, request an independent code review and do not continue until it scores at least 95/100 with no unresolved blocker or important finding. Record the review in this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned PostgreSQL schema and a tested API-side persistence layer for MusicSheet jobs, so later job endpoints and workers can share durable job state.

**Architecture:** Keep database access in the standalone `services/api` uv project and use its existing `asyncpg` dependency. Apply versioned migrations through an explicit CLI command rather than during API startup; expose a small typed job repository over an API-lifespan pool while keeping liveness available when PostgreSQL is absent.

**Tech Stack:** Python 3.13, uv, FastAPI lifespan, asyncpg, existing `musicsheet-common` enums, pytest, PostgreSQL 16 from the existing Compose file.

**Spec:** [Database & PostgreSQL Schema](../backend/database.md), [Job State Machine](../domain/job-state.md), [FastAPI Gateway](../backend/api.md)

## Plan Review Gate

- A separate independent reviewer must score the current plan revision using the five criteria in [AGENTS.md](../../AGENTS.md); only 95/100 or higher with no unresolved blocker/important finding passes.
- Plan review and implementation code review are separate gates. Review every implementation task before starting the next one, using the code-review criteria in `AGENTS.md`.
- The user requested a plan for the next project task. This plan selects PostgreSQL persistence as the prerequisite for the still-unimplemented job REST API and orchestration.

### Plan Review Record

- Revision 1: 88/100 on 2026-09-27. The independent reviewer found that PostgreSQL concurrency/rollback verification, exact nullable field types and `source_type` validation, CLI/lifecycle error redaction, and a guarded disposable test database were not sufficiently specified. Revision 2 addresses these findings; the revision 1 score does not transfer.
- Revision 2: 91/100 on 2026-09-27. The independent reviewer found that the test database guard checked only its name, CLI redaction had no direct test, and two command/interface descriptions were inconsistent. Revision 3 adds a database-level disposable-test marker, explicit CLI redaction tests, and aligned interfaces/commands; earlier scores do not transfer.
- Revision 3: 94/100 on 2026-09-27. The independent reviewer found an inconsistent migration-runner signature/source for `DATABASE_URL`, plus minor ambiguity about the migration ledger and schema-catalog verification. Revision 4 aligns the function/CLI contracts and requires full schema metadata assertions; earlier scores do not transfer.
- Revision 4: 97/100 on 2026-09-27. Independent score passed with no blocker/important findings. Minor suggestions: name the synchronous CLI entry point and explicitly include `schema_migrations` in the asserted table inventory. Revision 5 clarifies both; score is rechecked because the plan version changed.
- Revision 5: 97/100 on 2026-09-27. Independent score passed with no blocker/important findings. Minor suggestion: distinguish fake-runner unit assertions from live schema idempotence verification. Revision 6 assigns the live schema assertion to the PostgreSQL integration task; prior scores do not transfer.
- Revision 6: 97/100 on 2026-09-27. Independent score passed with no blocker/important findings. Minor suggestions: explicitly test PostgreSQL index/FK catalog state, align nullable `target_instrument` parameter typing, and identify each uv lockfile check's working directory. Revision 7 clarifies these items and is independently re-evaluated; prior scores do not transfer.
- Revision 7: 98/100 on 2026-09-27. Independent score passed with no blocker/important findings. Minor suggestion: explicitly bind the session advisory lock and all ledger/migration work to the same physical PostgreSQL connection, then release and close it. Revision 8 clarifies and tests that connection lifecycle; prior scores do not transfer.
- Revision 8: 99/100 on 2026-09-27 by an independent reviewer. Breakdown: spec coverage 25/25; scope/interfaces 20/20; sequencing/dependencies 20/20; verification/failure cases 24/25; reproducibility/operations/docs 10/10. Gate passed; no blocker or important findings. Remaining minor suggestion: add a test for advisory-lock acquisition failure ensuring the connection closes and migration stops. This does not block planning or implementation.

## Global Constraints

- Keep the root Python 3.13 uv workspace and root lockfile unchanged; `services/api` remains an independent project with `requires-python = ">=3.13,<3.14"` and its own `uv.lock`/`.venv`.
- Reuse `asyncpg>=0.31.0` already declared by `services/api`; do not add an ORM or migration dependency.
- Preserve the canonical `jobs`, `stage_attempts`, and `artifacts` column names, types, defaults, indexes, and foreign-key cascade behavior in `docs/backend/database.md`.
- Preserve `JobStatus` and `PipelineStage` definitions from `packages/common`; do not redefine them in the API.
- Do not run schema migrations automatically during app startup.
- PostgreSQL outages or missing `DATABASE_URL` must not prevent `/health/live` from serving; health endpoint response contracts remain unchanged.
- This task does not implement job HTTP endpoints, uploads/downloads, Celery dispatch, SSE, state-transition policy, or artifact file I/O.
- Never include database URLs, credentials, or raw driver exception details in API responses or logs.

## File Map

- `services/api/src/musicsheet_api/migrations/`: versioned, importable migration modules and a transaction-safe runner with a migration ledger and PostgreSQL advisory lock.
- `services/api/src/musicsheet_api/migrations/cli.py`: environment-driven migration command with sanitized output.
- `services/api/src/musicsheet_api/database.py`: optional API-lifespan pool setup and cleanup, kept separate from readiness probes.
- `services/api/src/musicsheet_api/jobs/repository.py`: typed create/read/progress-update operations for `jobs` rows.
- `services/api/src/musicsheet_api/jobs/models.py`: immutable `JobRecord` returned by repository operations.
- `services/api/src/musicsheet_api/app.py`: expose the available pool on `app.state` without changing health route behavior.
- `services/api/tests/`: migration runner, repository, lifecycle, and opt-in live PostgreSQL integration coverage.
- `services/api/pyproject.toml`, `services/api/uv.lock`: API CLI entry point only; dependency graph must not gain runtime packages.
- `services/api/README.md`: migration command, database setup, and persistence limitations.
- `docs/backend/database.md`: canonical migration and persistence behavior/status.
- `docs/roadmap.md`, `docs/main_spec.md`: mark this task Planned and link its plan; completion report is added only after implementation.

## Interfaces

- `JobRecord` is a frozen typed value with the fields represented by the canonical `jobs` table: `id: str`, `user_id: str | None`, `source_type: str`, `source_url: str | None`, `target_instrument: str | None`, `status: JobStatus`, `current_stage: PipelineStage`, `stage_progress: int | None`, `overall_progress: int | None`, `error_code: str | None`, `error_message: str | None`, `created_at: datetime | None`, `updated_at: datetime | None`, and `completed_at: datetime | None`. The `| None` fields match columns that the canonical DDL leaves nullable, even when a default is declared.
- `JobRepository(pool).create_job(*, source_type: str, source_url: str | None, user_id: str | None = None, target_instrument: str | None = "piano") -> JobRecord` generates a UUID, applies the spec defaults when the argument is omitted, preserves explicit `None` for the nullable column, and returns the inserted row.
- `create_job` accepts only `source_type` values `YOUTUBE` and `UPLOAD`; all values are passed as bound SQL parameters.
- `JobRepository(pool).get_job(job_id: str) -> JobRecord | None` returns `None` when no row exists.
- `JobRepository(pool).update_progress(*, job_id: str, status: JobStatus, current_stage: PipelineStage, stage_progress: int, overall_progress: int, error_code: str | None = None, error_message: str | None = None) -> JobRecord | None` validates both progress values as integers in `0..100`, updates `updated_at`, and sets `completed_at` to the update time for `COMPLETED`, `FAILED`, or `CANCELED`, otherwise clears it.
- Repository methods propagate database operation failures to their caller; HTTP error mapping belongs to the later API endpoint task.
- The explicit `musicsheet-migrate` CLI targets synchronous `musicsheet_api.migrations.cli:main()`, which runs the async migration function through `asyncio.run`. `apply_migrations` opens one `asyncpg.Connection`; that same physical connection acquires the session-level advisory lock, reads/creates the ledger, and applies each migration. It releases the lock in `finally` and then closes the connection. Each migration's DDL and ledger insert share one transaction.
- `Migration` is a frozen value with `version: int` and `upgrade_sql: str`. The library function `apply_migrations(database_url: str, *, migrations: Sequence[Migration] | None = None) -> list[int]` accepts an injected migration sequence for deterministic failure tests; `None` selects the packaged migrations. The `musicsheet-migrate` console command has no injection arguments; it reads only process `DATABASE_URL` and runs packaged migrations.

## Tasks

### Task 1: Versioned PostgreSQL migrations

**Files:**
- Create: `services/api/src/musicsheet_api/migrations/__init__.py`
- Create: `services/api/src/musicsheet_api/migrations/runner.py`
- Create: `services/api/src/musicsheet_api/migrations/v0001_initial.py`
- Modify: `services/api/pyproject.toml` (register the `musicsheet-migrate` console script)
- Test: `services/api/tests/test_migrations.py`

**Interfaces:**
- Consumes: a `database_url: str` argument to the migration library function; the CLI reads `DATABASE_URL` directly from `os.environ`; existing `asyncpg` dependency. The migration CLI does not construct or consume API `Settings`.
- Produces: `async def apply_migrations(database_url: str, *, migrations: Sequence[Migration] | None = None) -> list[int]`, returning versions newly applied during this invocation; `musicsheet-migrate` has no arguments, loads the process `DATABASE_URL`, and exits nonzero on failure without printing the DSN.

- [x] **Step 1: Write migration-runner and CLI tests** named `test_applies_migrations_in_version_order`, `test_skips_already_applied_migration`, `test_uses_one_connection_for_lock_ledger_and_migrations`, `test_acquires_lock_before_ledger_access`, `test_failed_migration_rolls_back_version_record`, `test_releases_lock_and_closes_connection_after_failure`, `test_cli_missing_database_url_uses_sanitized_error`, and `test_cli_migration_failure_omits_dsn_and_driver_details`; use fake connections to assert connection identity, call order, transaction boundaries, lock release, close, and CLI redaction.
- [x] **Step 2: From the repository root, run focused migration tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_migrations.py -q`; confirm the tests fail because the runner does not exist.
- [x] **Step 3: Implement the ledger and runner** using a `schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)` table, one transaction per migration, and one fixed application advisory-lock key. Release the advisory lock in `finally`.
- [x] **Step 4: Define migration v1** to create `jobs`, `stage_attempts`, and `artifacts`, including all columns, defaults, indexes, foreign keys, and `ON DELETE CASCADE` behavior in `docs/backend/database.md`.
- [x] **Step 5: Add the synchronous `main() -> int` CLI wrapper** at `musicsheet_api.migrations.cli:main`; register `musicsheet-migrate = "musicsheet_api.migrations.cli:main"` in `services/api/pyproject.toml`. `main()` reads `os.environ["DATABASE_URL"]` and uses `asyncio.run` to call `apply_migrations(database_url)` with packaged migrations, reports applied/current versions without showing the URL, and returns a nonzero exit status for unset URL or database/migration failure. The CLI takes no args and does not accept the test-only migration sequence. Emit only a generic sanitized failure message; do not log the URL, host, credentials, or raw driver exception.
- [x] **Step 6: From the repository root, run migration unit/CLI tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_migrations.py -q`; use fake connections to verify runner ordering, ledger decisions, and error output. Verify live schema idempotence only in Task 3's PostgreSQL integration test.
- [x] **Step 7: Complete an independent code review**; record score/findings and resolve any blocker or important finding before Task 2.

### Task 2: Optional API pool and job repository

**Files:**
- Create: `services/api/src/musicsheet_api/database.py`
- Create: `services/api/src/musicsheet_api/jobs/__init__.py`
- Create: `services/api/src/musicsheet_api/jobs/models.py`
- Create: `services/api/src/musicsheet_api/jobs/repository.py`
- Modify: `services/api/src/musicsheet_api/app.py`
- Test: `services/api/tests/test_database.py`
- Test: `services/api/tests/test_job_repository.py`
- Test: `services/api/tests/test_app.py`

**Interfaces:**
- Consumes: `apply_migrations` is an operator CLI only; app runtime receives the pool separately and does not migrate.
- Produces: the `JobRecord` and `JobRepository` interfaces in the plan's Interfaces section; `app.state.db_pool` is either a live asyncpg pool or `None`.

- [x] **Step 1: Write repository tests** named `test_create_job_uses_schema_defaults`, `test_create_job_preserves_null_target_instrument`, `test_create_job_rejects_unknown_source_type`, `test_repository_passes_user_values_as_bound_parameters`, `test_get_job_returns_record_or_none`, `test_update_progress_updates_timestamps_and_terminal_time`, `test_update_progress_rejects_out_of_range_and_boolean_values`, `test_update_progress_returns_none_for_missing_job`, `test_records_map_status_and_stage_enums`, and `test_repository_rejects_unknown_database_enum_values`; use a controllable pool/connection fake and assert bound SQL parameters.
- [x] **Step 2: From the repository root, run focused repository tests** with `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_repository.py -q`; confirm they fail before implementation.
- [x] **Step 3: Add `JobRecord` and `JobRepository`** with the exact signatures in the Interfaces section. Generate IDs with `uuid.uuid4()`, use parameterized asyncpg queries, map enum strings to common enums, and never interpolate user values into SQL.
- [x] **Step 4: Write pool lifecycle tests** named `test_missing_database_url_keeps_pool_none`, `test_database_unavailable_does_not_break_app_startup`, `test_pool_failure_log_omits_connection_details`, and `test_created_pool_is_closed_on_shutdown`; mock connection refusal deterministically, preserve the existing health tests, and ensure readiness continues using its current bounded probe.
- [x] **Step 5: Implement optional pool lifecycle** for the API lifespan, handling pool creation failures without failing startup, storing `None` on failure, closing a created pool at shutdown, and making no automatic migration call. Use a bounded one-second pool connection timeout. Log only a generic sanitized message for pool startup failure.
- [x] **Step 6: From the repository root, run focused repository/lifecycle tests and the full API suite** with `uv run --project services/api --python 3.13 pytest -q`; confirm all existing health endpoint behavior remains unchanged.
- [x] **Step 7: Complete an independent code review**; record score/findings and resolve any blocker or important finding before Task 3.

### Task 3: PostgreSQL integration, operating docs, and project indexes

**Files:**
- Modify: `services/api/pyproject.toml` (register an `integration` pytest marker if needed)
- Create: `services/api/tests/integration/test_postgres_persistence.py`
- Modify: `services/api/README.md`
- Modify: `docs/backend/database.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/main_spec.md`
- Create after implementation: `docs/reports/postgresql-job-persistence-implementation-report.md`

**Interfaces:**
- Consumes: migration CLI, API pool lifecycle, and job repository from Tasks 1-2.
- Produces: documented repeatable local setup/migrate/test instructions and verified live PostgreSQL behavior for the repository contract.

- [x] **Step 1: Add opt-in PostgreSQL integration tests** named `test_guard_rejects_wrong_database_name`, `test_guard_rejects_missing_or_wrong_database_marker`, `test_initial_migration_creates_all_canonical_tables_indexes_foreign_keys_and_column_metadata`, `test_migration_is_repeatable`, `test_concurrent_migration_runners_apply_once`, `test_failed_migration_rolls_back_ddl_and_ledger_entry`, `test_job_crud_round_trip`, `test_progress_boundary_values`, and `test_job_delete_cascades_to_stage_attempts_and_artifacts`. Before any reset, require `MUSICSHEET_TEST_DATABASE_URL`, verify server-side that `current_database()` is exactly `musicsheet_test` and the database comment is exactly `MUSICSHEET_DISPOSABLE_TEST_DB_V1`, then reset only that database's `public` schema. Guard tests must not reset any schema; never drop schema objects on import. Assert that the complete public table inventory is exactly `{jobs, stage_attempts, artifacts, schema_migrations}`; assert canonical column data types, varchar lengths, nullability, and defaults for all columns in the three application tables using `information_schema.columns`; assert every canonical index and foreign key, including both `ON DELETE CASCADE` constraints, using PostgreSQL catalog queries.
- [x] **Step 2: Run live integration tests** after `docker compose -f docker/docker-compose.yml up -d postgres`. From the repository root, create the dedicated database once with `docker exec musicsheet_postgres psql -U musicsheet_user -d postgres -c "CREATE DATABASE musicsheet_test"`, mark it with `docker exec musicsheet_postgres psql -U musicsheet_user -d postgres -c "COMMENT ON DATABASE musicsheet_test IS 'MUSICSHEET_DISPOSABLE_TEST_DB_V1'"`, set `$env:MUSICSHEET_TEST_DATABASE_URL` to the corresponding `musicsheet_test` DSN, then run `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_postgres_persistence.py -q`. Confirm all schema objects, ledger concurrency/rollback, enum round-trips, timestamps, bounds, and cascades against PostgreSQL 16.
- [x] **Step 3: Update canonical docs and API README** with the migration ledger, explicit migration command, pool outage behavior, repository scope, exact integration-test database name/comment guard/setup/invocation, and sanitized CLI failure output; state that no job REST endpoint is implemented by this task.
- [x] **Step 4: Update the roadmap and main spec** to mark the persistence task Done and record its report link only after all completion evidence exists.
- [x] **Step 5: Write the implementation report** with package/runtime versions, commands/results, migration versions, integration-test evidence, any skipped verification and reason, review scores, and known limits.
- [x] **Step 6: Run final verification** from `services/api`: `uv lock --check` and `uv run --project . --python 3.13 pytest -q`; then from the repository root: `uv lock --check`, `uv run --project . pytest -q`, and `git diff --check`. Confirm the root `pyproject.toml` and `uv.lock` are unchanged.
- [x] **Step 7: Complete an independent code review** of Task 3's docs/integration changes; require at least 95/100 with no unresolved blocker/important finding, then explicitly stage only task files and create one Conventional Commit for this implementation task.

## Review Focus

- A missing or unreachable database must not stop API startup or alter `/health/live`; cover missing URL, refused connection, and pool cleanup.
- A migration interrupted after SQL execution must roll back both schema changes and its ledger row; verify this in both runner unit tests and a live PostgreSQL integration test.
- Two migration commands started concurrently must not apply the same migration twice; verify lock-before-ledger ordering and exactly-once ledger/schema effects in live PostgreSQL integration.
- Unknown job IDs must return `None` from repository operations without creating rows or changing other jobs.
- Out-of-range progress, invalid enum strings from the database, and values containing SQL syntax must be rejected or safely handled without SQL interpolation or disclosure.
- The CLI and API lifecycle must not print or log a PostgreSQL URL, hostname, credentials, or raw driver exception when startup or migration fails.

## Acceptance Criteria

- A fresh PostgreSQL 16 database receives the three canonical application tables and indexes from `docs/backend/database.md`, plus the `schema_migrations` ledger; catalog assertions confirm canonical types, lengths, nullability, defaults, indexes, and foreign keys. A second migration run is a no-op.
- The integration fixture refuses any database other than `musicsheet_test` carrying the exact database comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1`; it verifies both values from PostgreSQL before resetting schema objects.
- Create/read/progress repository operations round-trip the canonical job fields and common enums; progress accepts only integer values from 0 through 100.
- Missing/unavailable PostgreSQL leaves app startup and liveness available; an opened pool is closed once on shutdown; health response shapes and time limits do not change.
- API project tests pass; root tests pass; opt-in PostgreSQL integration tests pass against the configured disposable DB. If the local Docker engine is unavailable, report live DB behavior as unverified rather than claiming that integration acceptance passed.
- API dependencies use the existing `asyncpg`; root lockfiles remain untouched; migration and test commands are documented and reproducible.
- Code-review score is at least 95/100 for every implementation task, with no unresolved blocker/important finding; all scores and dispositions are recorded in this plan and the completion report.

## Implementation Review Log

- **Task 1 — 98/100** (2026-09-27), independent review of `d0597b5..3d0caf0`; gate passed, no blocker/important findings. Minor suggestions deferred: the CLI's “current version” label reflects the highest packaged migration rather than necessarily the database ledger; an advisory-unlock failure could mask an earlier migration error. These do not change the accepted task contract and remain follow-up polish.
- **Task 2 — 97/100** (2026-09-27), independent review of `20602dd..74ee298`; gate passed, no blocker/important findings. The reviewer requested live confirmation of PostgreSQL defaults and timestamp behavior; Task 3's integration tests verified them.
- **Task 3 — 98/100** (2026-09-27), independent review of Task 3's integration and documentation changes (`74ee298..f3342e1`); gate passed, no blocker/important findings. Breakdown: external behavior 25/25; errors/boundaries/security 25/25; tests/evidence 24/25; structure/dependencies 15/15; docs/reproducibility 9/10. The report distinguishes the implementer's 2.19-second run from the controller's fresh 2.34-second rerun.
- **Execution ruling:** root `pyproject.toml` sets `testpaths = ["tests"]`, so a bare `pytest -q` from the repository root omits `services/api/tests`. The full API suite was therefore verified with the explicit `services/api/tests` path; the independent API project and root suites were also run separately.
- **Gate result:** all three implementation units passed independent reviews of at least 95/100 before the next unit began. No blocker/important findings remain. The two Task 1 minor suggestions remain documented follow-up items; Task 2's database verification suggestion is resolved by Task 3 evidence.
- **Final whole-branch review:** pending review of the consolidated branch and final documentation state.
