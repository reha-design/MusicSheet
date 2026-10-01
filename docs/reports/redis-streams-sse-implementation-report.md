# W02 — Redis Streams and SSE Implementation Report

> **Date:** 2026-10-01<br>
> **Scope:** W02 — typed job progress event storage, replayable SSE, opt-in Redis integration coverage<br>
> **Plan review:** Revision 2, 98/100 (passed)<br>
> **Task 1 code review:** 98/100 (passed)<br>
> **Task 2 code review:** 99/100 (passed)<br>
> **Task 3 code review:** 100/100 passed (independent re-review, 2026-10-01)
> **Task 3 implementation commit:** pending; review gate passed

## Delivered

- Added `JobEventStore` around the existing lifespan-owned Redis client. It writes the complete common `JobProgressEvent` JSON under the stream field `data`, uses approximate `MAXLEN ~ 100`, and returns the Stream ID as text.
- Added `GET /api/v1/jobs/{job_id}/events`. It checks the PostgreSQL job snapshot before Redis, starts at `0-0` when `Last-Event-ID` is absent, validates unsigned 64-bit Stream ID components, and sends the Stream ID and event JSON as SSE `id` and `data` fields.
- The stream replays retained entries and continues reading with bounded one-second XREAD calls. It sends `: keep-alive` after 15 idle seconds, advances past malformed stored payloads, observes client disconnects between reads, and logs generic errors without closing the shared Redis client.
- PostgreSQL remains the job-state authority. No database migration, Celery integration, or public event-publish API was added; W03 can publish through the internal store.
- Added opt-in Redis integration tests for cursor replay, a live append, old-cursor behavior after trimming, and approximate retention. Each test creates a unique job stream and deletes only its own key.

## Verification

| Check | Result |
| :--- | :--- |
| Task 1 focused event-store tests | 8 passed. |
| Task 1 config/readiness tests | Included in the full API suite on 2026-10-01; the suite passed (176 passed, 12 skipped). |
| Task 2 SSE route tests | `test_job_routes.py` was collected by the full API suite on 2026-10-01; the suite passed (176 passed, 12 skipped). |
| Redis integration tests with `MUSICSHEET_TEST_REDIS_URL` unset | 2 skipped as intended in the earlier opt-in check. |
| Redis integration tests against local Compose Redis DB `/2` | `test_redis_job_events.py -q -m redis_integration` -> 2 passed; verified persisted cursor replay, live append, trimming, and approximate retention. |
| Redis test-key cleanup | `redis-cli -n 2 PING` -> `PONG`; scan for `job:redis-test-*` returned no keys after the run. |
| Root tests | `uv run pytest` -> 59 passed, 4 skipped, 4 deselected. |
| API suite | `uv run --project services/api --python 3.13 pytest services/api/tests -q` -> 176 passed, 12 skipped, 1 existing Starlette deprecation warning. |
| `git diff --check` | Passed after the documentation updates (exit code 0). |

No inherited `MUSICSHEET_TEST_DATABASE_URL` or `MUSICSHEET_TEST_REDIS_URL` was used for default test runs.

## Independent Review

Plan Revision 2 passed at 98/100. Task 1 passed at 98/100 after re-review; its initial minor findings about type-hint resolution and lazy export coverage were addressed. Task 2 passed at 99/100 after re-review; the remaining minor observation is that the fake XREAD yields with `asyncio.sleep(0)` rather than waiting a full second, while asserting the production call uses `block=1000`. The initial Task 3 review on 2026-09-28 scored 95/100 but held the gate because live Redis behavior had not been exercised. The independent re-review on 2026-10-01 scored **100/100** (behavior 25/25, errors/security 25/25, tests/evidence 25/25, structure/dependencies 15/15, documentation/reproducibility 10/10). It confirmed the previous important finding resolved by the passing DB `/2` integration tests, `PONG`, and cleanup evidence, and confirmed the corrected API test records. No blocker, important, or minor findings remain.

## Limitations

The real-Redis integration checks passed against the local Compose service. PostgreSQL integration remained skipped because no opt-in disposable PostgreSQL test URL was configured. The API suite completed with one existing Starlette/httpx deprecation warning. W02 review gates have passed; the task commit and completion index are being recorded.
