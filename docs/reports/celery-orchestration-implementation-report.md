# W03 Celery Orchestration — Implementation Report

> **Date:** 2026-09-29
> **Scope:** W03 — Celery runtime, PostgreSQL stage attempts, six-stage orchestration, API dispatch, stalled-job operator recovery, and canonical documentation
> **Plan gate:** Revision 8, 98/100, passed; no blocker/important finding (independent reviewer result recorded by the parent task)
> **Implementation review:** Independent score and disposition are recorded in the W03 implementation plan after the Task 5 review gate
> **Review target:** Task 5 staged diff from base 2c75518, reviewed before its implementation commit

## Delivered

- The API persists jobs and upload artifacts before dispatching a Celery start task containing only the job ID. A broker failure changes only a still-`PENDING` job to `FAILED/DISPATCH_FAILED`; a sanitized `503` includes `detail.job_id` if the dispatch outcome cannot be saved.
- The API project under `services/api` now contains a Python 3.13 Celery app, queue routing, an immutable six-stage chain, task/handler contracts, guarded PostgreSQL job and attempt transitions, cooperative cancellation, persisted retry limits, and progress/terminal event publication through the existing Redis Streams interface.
- Added `musicsheet-orchestration-maintenance scan` and `fail-stalled`. The read-only scan reports only job ID, status, current stage, `updated_at`, start dispatch count, and the latest attempt summary. Recovery requires the operator's observed timestamp and status, obtains the start/current-stage session advisory locks nonblocking, compares the exact row under a PostgreSQL lock, and rechecks the `2 × visibility_timeout` stale threshold. It closes open attempts and changes the job in one transaction; `CANCEL_REQUESTED` becomes `CANCELED`, otherwise the job becomes `FAILED/WORKER_PRECLAIM_STALLED`. A terminal event is published after commit on a best-effort basis.
- Added rollback handling for an unexpected job compare-and-set miss after closing an attempt: both updates now roll back together.
- Updated the Celery, job-pipeline, API, database, and runtime specs; API README; `.env.example`; main spec; roadmap/backlog; and completed-work index. The docs record Redis DBs `/0` (broker), `/1` (result backend), and `/2` (events), visibility/retry/concurrency defaults, the v2 migration prerequisite, worker commands, `detail.job_id`, operator recovery, and W04–W08 output-effect-before-completion re-entrancy tests.
- Actual audio download, transformation, inference, quantization, and score rendering remain outside W03. Unregistered stage handlers fail with `STAGE_NOT_CONFIGURED`.

## TDD and verification

| Check | Result |
| :--- | :--- |
| Initial maintenance tests, RED | 10 failed and 1 passed because the maintenance module/entry point did not exist; the terminal-delivery path test already passed. |
| Recovery compare-and-set atomicity, RED | New regression test failed because the attempt was closed when the guarded job update returned no row. |
| Recovery compare-and-set atomicity, GREEN | The recovery now raises inside the transaction to roll back both updates; focused maintenance suite: 12 passed. |
| Focused maintenance, route, repository, and guarded PostgreSQL test | 148 passed, 1 skipped; the opt-in PostgreSQL case skipped because `MUSICSHEET_TEST_DATABASE_URL` was unset. One existing Starlette/httpx deprecation warning. |
| Full API suite: `uv run --project services/api --python 3.13 pytest services/api/tests -q` | 323 passed, 13 skipped; one existing Starlette/httpx deprecation warning. PostgreSQL integration skips are expected with the test URL unset. |
| Root suite: `uv run pytest` | 59 passed, 4 skipped, 4 deselected. |
| `uv lock --check` | Passed; resolved 14 packages. |
| API `compileall` | Passed for `services/api/src/musicsheet_api` and `services/api/tests`. |
| Console entry point | `musicsheet-orchestration-maintenance --help` lists `scan` and `fail-stalled` without connecting to a service. |
| Task 5 scoped `git diff --check` | Passed when excluding the parent-owned plan file. The full workspace check also reported one trailing blank line at the end of the parent-owned `docs/plans/w03-celery-orchestration-implementation-plan.md`; the implementer left that file untouched. |

## Environment and remaining verification limits

- `DATABASE_URL`, `MUSICSHEET_TEST_DATABASE_URL`, `CELERY_BROKER_URL`, and `REDIS_URL` environment variables were unset. Code defaults point to local Redis DB `/0`, `/1`, and `/2`, but no live PostgreSQL, Celery broker, or Redis event publication check ran. The guarded PostgreSQL test is present and will run only after its disposable database name and marker guards pass.
- The known Windows `_ssl.pyd` collection limitation did not occur in these runs; the full API suite collected and passed. The only warning was the existing Starlette/httpx deprecation warning.
- The Task 5 review record in the implementation plan includes the independent reviewer, date, reviewed range, score, findings, and disposition.
