# W03 Celery Orchestration — Implementation Report

> **Date:** 2026-10-01
> **Scope:** W03 — Celery runtime, PostgreSQL stage attempts, six-stage orchestration, API dispatch, stalled-job operator recovery, and canonical documentation
> **Plan gate:** Revision 10, 99/100, passed on 2026-10-01; no blocker/important finding
> **Implementation reviews:** Task 5: 96/100, passed on 2026-09-29. Task 6: 97/100, passed on 2026-10-01.
> **Review target:** Task 5 staged diff from base 2c75518; Task 6 final seven-file remediation diff from integrated tree `509b66911e755cc94235b92482d990f8b73d2818`.

## Delivered

- The API persists jobs and upload artifacts before dispatching a Celery start task containing only the job ID. A broker failure changes only a still-`PENDING` job to `FAILED/DISPATCH_FAILED`; a sanitized `503` includes `detail.job_id` if the dispatch outcome cannot be saved.
- The API project under `services/api` now contains a Python 3.13 Celery app, queue routing, an immutable six-stage chain, task/handler contracts, guarded PostgreSQL job and attempt transitions, cooperative cancellation, persisted retry limits, and progress/terminal event publication through the existing Redis Streams interface.
- Added `musicsheet-orchestration-maintenance scan` and `fail-stalled`. The read-only scan reports only job ID, status, current stage, `updated_at`, start dispatch count, and the latest attempt summary. Recovery requires the operator's observed timestamp and status, obtains the start/current-stage session advisory locks nonblocking, compares the exact row under a PostgreSQL lock, and rechecks the `2 × visibility_timeout` stale threshold. It closes open attempts and changes the job in one transaction; `CANCEL_REQUESTED` becomes `CANCELED`, otherwise the job becomes `FAILED/WORKER_PRECLAIM_STALLED`. A terminal event is published after commit on a best-effort basis.
- Added rollback handling for an unexpected job compare-and-set miss after closing an attempt: both updates now roll back together.
- Updated the Celery, job-pipeline, API, database, and runtime specs; API README; `.env.example`; main spec; roadmap/backlog; and completed-work index. The docs record Redis DBs `/0` (broker), `/1` (result backend), and `/2` (events), visibility/retry/concurrency defaults, the v2 migration prerequisite, worker commands, `detail.job_id`, operator recovery, and W04–W08 output-effect-before-completion re-entrancy tests.
- Actual audio download, transformation, inference, quantization, and score rendering remain outside W03. Unregistered stage handlers fail with `STAGE_NOT_CONFIGURED`.
- Following a final integrated review failure, a completed stage redelivery now returns normally only when PostgreSQL proves that its attempt completed and the active job advanced. This lets Celery publish the remaining immutable-chain callback without re-running the handler. Transient PostgreSQL/pool failures at runtime setup, locks, claims, completion, and workflow bookkeeping become safe typed retries with `max_retries=None`, backoff capped at 60 seconds and jitter. These scheduling retries remain separate from the PostgreSQL four-execution limits.
- Updated the canonical Celery runbook to explain persistent pre-claim database retries and to require database restoration, inactive-worker confirmation, exact scan snapshots, and guarded recovery before writing state.

## Integrated review remediation

- An independent 2026-10-01 integrated review scored the 47-file W02/W03 merge tree **84/100 (gate failed)**. Its two important findings were that Celery `Ignore` could swallow the successor callback after a committed stage advance, and that transient PostgreSQL errors outside handler execution could be acknowledged without retry. Task 6 addresses both with persisted completion proof, normal Celery success-trace continuation, typed task-boundary retry, and separate unlimited scheduling retries versus durable claim counters.
- Minor finding deferred for follow-up: a corrupt Redis stream tail does not send an SSE `id`, so reconnect can reread and log that tail. The existing code remains unchanged in this pass.
- TDD evidence: the new regression tests first ran RED with **20 failed, 2 passed**. After implementation, the focused stage/task modules passed **85 tests**. The focused run includes `request.retries > 3`, both uncertain completion outcomes, real `memory://` Celery immutable-chain continuation, and cancellation before entering the next handler.
- Independent Task 6 implementation review: `/root/integrated_final_review`, **2026-10-01**, final seven-file scope listed in the plan review record. Behavior 25/25, errors/security 25/25, tests/evidence 22/25, structure/maintainability 15/15, docs/reproducibility 10/10; **97/100, passed**. Both P1 findings were resolved. A test-only cancellation synchronization minor was resolved by waiting for the persisted cancellation and asserting the Celery postrun state is `IGNORED`; final re-review confirmed it. The corrupt SSE tail cursor minor remains deferred for follow-up.

## TDD and verification

| Check | Result |
| :--- | :--- |
| Initial maintenance tests, RED | 10 failed and 1 passed because the maintenance module/entry point did not exist; the terminal-delivery path test already passed. |
| Recovery compare-and-set atomicity, RED | New regression test failed because the attempt was closed when the guarded job update returned no row. |
| Recovery compare-and-set atomicity, GREEN | The recovery now raises inside the transaction to roll back both updates; focused maintenance suite: 12 passed. |
| Focused maintenance, route, repository, and guarded PostgreSQL test | 148 passed, 1 skipped; the opt-in PostgreSQL case skipped because `MUSICSHEET_TEST_DATABASE_URL` was unset. One existing Starlette/httpx deprecation warning. |
| Full API suite: `uv run --project services/api --python 3.13 pytest services/api/tests -q` | 323 passed, 13 skipped; one existing Starlette/httpx deprecation warning. PostgreSQL integration skips are expected with the test URL unset. |
| Final API suite after Task 6: `uv run --project services/api --python 3.13 pytest services/api/tests -q` | 342 passed, 15 skipped; one existing Starlette/httpx deprecation warning. PostgreSQL opt-in tests were skipped because `MUSICSHEET_TEST_DATABASE_URL` was unset. |
| Task 6 focused stage/task suite | 85 passed. |
| Redis opt-in integration against local Compose DB `/2` | 2 passed; tests cleaned their unique stream keys. |
| Root suite: `uv run pytest` | 59 passed, 4 skipped, 4 deselected. |
| `uv lock --check` | Passed; resolved 14 packages. |
| API `compileall` | Passed for `services/api/src/musicsheet_api` and `services/api/tests`. |
| Console entry point | `musicsheet-orchestration-maintenance --help` lists `scan` and `fail-stalled` without connecting to a service. |
| `git diff --check HEAD` after Task 6 plan and runbook edits | Passed for the full integrated worktree. |

## Environment and remaining verification limits

- `MUSICSHEET_TEST_DATABASE_URL` was unset, so guarded live PostgreSQL migration/locking behavior was not exercised. Docker Compose Redis was running; the opt-in event tests used `redis://localhost:6379/2` for that test process and passed. Celery callback recovery was exercised with an in-memory worker; a live Celery broker was not used. Production defaults remain Redis DB `/0` (broker), `/1` (result backend), and `/2` (events).
- The known Windows `_ssl.pyd` collection limitation did not occur in these runs; the full API suite collected and passed. The only warning was the existing Starlette/httpx deprecation warning.
- The implementation plan records the Revision 10 plan score, the integrated 84/100 review findings and dispositions, Task 6 TDD/test evidence, and the independent Task 6 code review result.
