# W02 — Redis Streams and SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development`. Implement one task at a time. Each implementation task requires an independent code review of at least 95/100 with no unresolved blocker/important finding before the next task. Steps use checkbox syntax.

**Goal:** Persist typed job progress events in Redis Streams and expose replayable, live SSE updates at `GET /api/v1/jobs/{job_id}/events`.

**Architecture:** Reuse the API's lifespan-managed Redis client and the existing `musicsheet_common.JobProgressEvent` model. `JobEventStore` stores each validated event as JSON in the Redis stream's `data` field; Redis entry IDs become SSE IDs. PostgreSQL remains the authoritative job snapshot and is checked before streaming.

**Tech Stack:** Python 3.13, FastAPI, `redis.asyncio`, Pydantic, pytest, FastAPI TestClient, Redis 7 Compose service.

**Spec:** `docs/backend/redis-streams.md`, `docs/backend/api.md`, `docs/domain/job-state.md`, `docs/adr/002-redis-streams.md`.

## Global Constraints

- Keep `services/api` on Python `>=3.13,<3.14` with its existing `redis>=8.1.0` dependency; do not add a Redis client dependency.
- Use the existing `JobProgressEvent` fields: `job_id`, `status`, `stage`, `stage_progress`, `overall_progress`, `message`, and UTC-defaulted `timestamp`.
- Store events at `job:{job_id}:events` with approximate `MAXLEN ~ 100`; event history is bounded and is not the durable job-state source.
- Use application event Redis DB `/2`; Celery broker and result backend remain separate at `/0` and `/1`.
- Reuse `app.state.redis_client`; do not create or close a Redis connection per SSE request. The FastAPI lifespan owns the shared client.
- Keep startup optional when `REDIS_URL` is unset or Redis is unavailable. Readiness already reports Redis state; the SSE endpoint returns a generic `503` when it cannot start.
- `GET /api/v1/jobs/{job_id}` and PostgreSQL remain authoritative for resynchronizing current status after stream trimming.
- Do not add a database migration, public event-publish route, Celery task integration, authentication, or durable event guarantee in W02.
- Do not expose raw Redis exceptions, payload bytes, or connection details in HTTP responses or logs.

## Review Focus

1. First connection to a known job with no stream entries — remain connected, send a heartbeat after 15 seconds, and deliver a subsequently published event.
2. `Last-Event-ID` older than trimmed history — deliver every retained newer entry in order and leave durable-state resynchronization to the existing GET route.
3. PostgreSQL or Redis unavailable before SSE headers start — return the documented generic `503` response without exposing exception details.
4. Client disconnect while `XREAD` is blocked — stop that response promptly and leave the lifespan-owned Redis client open for other requests.
5. Malformed `Last-Event-ID` or malformed stored event JSON — reject the header with `400`; skip a corrupt stored entry with a generic warning while advancing its cursor so reconnects do not loop on it.

## Interfaces

- `JobEventStore(redis_client: Redis)` in `services/api/src/musicsheet_api/jobs/events.py` reuses an injected async Redis client.
- `JobEventStore.publish(event: JobProgressEvent) -> str` and `JobEventStore.read_after(...)` are async methods and await `redis.asyncio.Redis` operations. `publish` appends `event.model_dump_json()` as the `data` field using approximate max length 100 and returns the normalized Redis Stream ID as text; Redis write errors propagate to the caller.
- `JobEventStore.read_after(job_id: str, last_id: str, *, block_ms: int = 1_000) -> list[StoredJobEvent]` calls `xread(streams={key: last_id}, count=100, block=block_ms)`. Normalize a timed-out `None` result to `[]`; parse redis-py's nested `(stream, [(id, fields)])` response and decode either bytes or text. `StoredJobEvent` contains `stream_id: str` and `event: JobProgressEvent | None`. An invalid JSON/model payload produces `event=None`, logs a generic warning, and still returns its ID for cursor advancement.
- `GET /api/v1/jobs/{job_id}/events` accepts optional `Last-Event-ID`. Missing header starts at `0-0`; valid IDs contain two ASCII decimal components of at most 20 digits, each at most `18446744073709551615`. Each frame ends in a blank line after `id: <stream-id>` and `data: <JobProgressEvent JSON>`; emit the exact heartbeat `: keep-alive\n\n` after 15 seconds without a valid event.
- `stream_job_events(*, request: Request, event_store: JobEventStore, job_id: str, last_id: str) -> AsyncIterator[str]` owns one request's cursor, heartbeat timer, disconnect checks, and mid-stream error handling. It checks `request.is_disconnected()` before and after each bounded 1-second Redis read, so it exits within at most one read interval without canceling an in-flight Redis command. It never closes the shared Redis client.
- The SSE route verifies the job through `JobRepository.get_job` before checking Redis availability. Unknown jobs return `404`; absent/failing PostgreSQL or Redis before response start returns a generic `503`; malformed `Last-Event-ID` returns `400`.
- Redis failures after response start log a fixed generic warning and close the stream. A client disconnect stops its read loop without closing the shared Redis client.

## Plan Review Gate

- An independent reviewer scores this plan revision against `AGENTS.md`: requirements/spec 25, scope/interfaces 20, sequence/dependencies 20, validation/failure cases 25, reproducibility/operations/docs 10.
- Implementation begins only when the current revision scores at least 95/100 and has no unresolved blocker/important finding. Record reviewer, date, revision, category scores, findings, and resolution here.
- After each implementation task, independently score its changed code using `AGENTS.md`: behavior 25, errors/security 25, tests/evidence 25, structure/dependencies 15, docs/reproducibility 10. Advance only at 95/100 or above with no unresolved blocker/important finding.

### Plan Review Record

- **Revision 1 — 93/100, not passed (2026-09-28).** Independent reviewer `/root/w02_plan_review`: requirements/spec 25/25, scope/interfaces 19/20, sequence/dependencies 19/20, verification/failures 21/25, reproducibility/operations/docs 9/10. Important findings: disconnect handling during blocked XREAD and async redis-py interface/timeout parsing needed exact behavior. Minor findings: explicit ID boundary cases, exact SSE delimiters, include the plan file in task file lists, unset inherited PostgreSQL integration URL before full API suite, and finish report score/hash updates after Task 3 review/commit. Revision 2 adds these details. No implementation started.
- **Revision 2 — 98/100, passed (2026-09-28).** Independent reviewer `/root/w02_plan_review`: requirements/spec 25/25, scope/interfaces 19/20, sequence/dependencies 20/20, verification/failures 24/25, reproducibility/operations/docs 10/10. No unresolved blocker or important finding. Minor deferred: the plan prose identifies `Redis` as `redis.asyncio.Redis` and states the methods are async; implementation will use explicit `async def` signatures and the fully qualified annotation.

### Implementation Review Record

- **Task 1 — 98/100, passed (2026-09-28).** Independent reviewer `/root/w02_plan_review`; reviewed the working-tree diff against baseline `781f045`: the plan, Redis/API specs, roadmap/backlog, lazy job-package exports, Redis event store, and store tests. Category scores: behavior 25/25, errors/security 25/25, tests/evidence 23/25, structure/dependencies 15/15, documentation/reproducibility 10/10. Initial minor findings (runtime type-hint resolution and missing lazy `JobRepository` export coverage) were fixed and re-reviewed. Final review found no unresolved findings. API readiness regression selection remains unverified because Windows Application Control blocks `_ssl.pyd` at collection, matching the pre-change baseline limitation.
- **Task 2 — re-review 99/100, passed (2026-09-28).** Independent reviewer `/root/w02_plan_review`; reviewed the working-tree diff against `a06e80f`: plan, `router.py`, and `test_job_routes.py`. Category scores: behavior 25/25, errors/security 25/25, tests/evidence 24/25, structure/dependencies 15/15, documentation/reproducibility 10/10. The initial 96/100 review's two minor findings were addressed: disconnect now exercises a `JobEventStore` over a controlled fake Redis, asserting `block=1000` and that the shared client is not closed; a mid-stream XREAD failure test verifies stream closure and generic logging. One minor remains: the fake read yields with `asyncio.sleep(0)` instead of remaining pending for the whole second. The actual bounded XREAD argument is asserted; this was accepted as non-blocking. No blocker or important finding remains. Route tests remain uncollectable in this environment because importing the existing API app loads `redis.asyncio`, which fails after Windows Application Control blocks `_ssl.pyd`.
- Task 3: pending.

## Tasks

### Task 1: Event contract and Redis event store

**Files:**
- Modify: `docs/plans/redis-streams-sse-implementation-plan.md` (task checklist and review record)
- Modify: `docs/backend/redis-streams.md`
- Modify: `docs/backend/api.md`
- Modify: `docs/roadmap.md` and `docs/backlog.md` to move W02 into progress after the plan gate passes
- Create: `services/api/src/musicsheet_api/jobs/events.py`
- Create: `services/api/tests/test_job_events.py`

**Interfaces:**
- Consumes: existing `JobProgressEvent` and the existing lifespan-managed `Redis` client.
- Produces: `StoredJobEvent`, `JobEventStore.publish`, and `JobEventStore.read_after` exactly as defined in Interfaces above; Task 2 uses both methods.

- [x] **Step 1: After the plan gate passes, move W02 from the backlog to the roadmap's In Progress section.** Do not alter its scope or the W03 candidate.
- [x] **Step 2: Refine canonical Redis and API specs** to document the existing `JobProgressEvent` JSON stored in the `data` field, first-read cursor `0-0`, SSE ID/data mapping, approximate retention, bounded replay, heartbeat, and pre-/mid-stream failure behavior.
- [x] **Step 3: Write failing store tests** named `test_publish_appends_typed_json_to_bounded_job_stream`, `test_read_after_decodes_bytes_and_text_entries_in_order`, `test_read_after_normalizes_timeout_none_to_empty_list`, `test_read_after_skips_corrupt_payload_and_returns_its_cursor`, and `test_publish_propagates_redis_failure`. Assert awaited `xadd`/`xread`, exact key, `maxlen=100` with `approximate=True`, `count=100`, `block=block_ms`, JSON contract, response-shape parsing, and string Stream ID.
- [x] **Step 4: Run the focused tests to verify RED.**

  Result: the focused test initially failed collection because `musicsheet_api.jobs.__init__` eagerly imported `asyncpg`, whose Python 3.13 SSL extension is blocked by Windows Application Control. `jobs.__init__` now preserves its public re-exports via lazy loading; rerunning reached the intended `ModuleNotFoundError` for the missing `events` module (RED).

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_events.py -q`

  Expected: FAIL because `JobEventStore` and `StoredJobEvent` do not exist.
- [x] **Step 5: Implement `JobEventStore` and `StoredJobEvent`** in `services/api/src/musicsheet_api/jobs/events.py`. Use `XADD` with `maxlen=100, approximate=True`; use `XREAD` with `count=100` and the supplied cursor/block duration; normalize Redis byte/text results; validate JSON with `JobProgressEvent`; skip corrupt entries only after preserving their Stream IDs.
- [x] **Step 6: Run focused and API unit tests to verify GREEN.**

  Result: `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_events.py -q` -> 6 passed. The planned selection including `test_readiness.py` is blocked at collection because Windows Application Control denies loading Python 3.13 `_ssl.pyd` through `asyncpg`; this also matches the pre-implementation baseline limitation.

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_events.py services/api/tests/test_config.py services/api/tests/test_readiness.py -q`

  Expected: all selected tests pass; no regression to optional Redis startup/readiness.
- [x] **Step 7: Review Task 1 independently.** Record date, reviewed commit range, all five category scores, total, findings, and resolutions in Implementation Review Record. Do not start Task 2 until score is at least 95 and no blocker/important finding remains.
- [x] **Step 8: Commit Task 1** with `feat(api): add Redis job event store` after its review gate passes. Commit: `a06e80f`.

### Task 2: Replayable SSE endpoint

**Files:**
- Modify: `docs/plans/redis-streams-sse-implementation-plan.md` (task checklist and review record)
- Modify: `services/api/src/musicsheet_api/jobs/router.py`
- Modify: `services/api/tests/test_job_routes.py`

**Interfaces:**
- Consumes: `JobEventStore.publish`, `JobEventStore.read_after`, `StoredJobEvent`, existing `JobRepository.get_job`, and shared `request.app.state.redis_client`.
- Produces: `GET /api/v1/jobs/{job_id}/events` with `text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no` headers.

- [x] **Step 1: Write failing route tests** named `test_job_events_replay_from_start_and_follow_new_entries`, `test_job_events_resume_after_last_event_id`, `test_job_events_validate_last_event_id_boundaries`, `test_job_events_unknown_job_returns_404`, `test_job_events_missing_or_unavailable_dependencies_return_503`, `test_job_events_emit_exact_heartbeat_frame`, `test_job_events_disconnect_during_bounded_read_does_not_close_shared_redis_client`, and `test_job_events_midstream_redis_failure_closes_stream_safely`. Exercise `stream_job_events` directly with a disconnecting request stub while one fake read is pending; assert it exits after that bounded XREAD and leaves the lifespan-owned Redis client open. Test valid IDs `0-0` and `18446744073709551615-18446744073709551615`, reject a component one above the maximum, non-ASCII digits, malformed separators, and overlong values. Assert exact event frame delimiters (`id`, `data`, terminating blank line) and heartbeat bytes. Verify PostgreSQL lookup precedes stream access and errors are sanitized.
- [x] **Step 2: Run the focused route tests to verify RED.**

  Result: attempted before route implementation, but pytest collection stopped while importing `musicsheet_api.app` because Windows Application Control blocked Python 3.13 `_ssl.pyd`, which then caused `redis.asyncio` import failure. The test runner could not reach the expected missing-route failures.

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_routes.py -q`

  Expected: SSE requests fail because the route does not exist.
- [x] **Step 3: Implement the route** in `services/api/src/musicsheet_api/jobs/router.py`. Validate the optional header with ASCII digits and unsigned-64-bit component limits, resolve the job from PostgreSQL, check `redis.ping()` before creating the streaming response, then iterate `read_after(block_ms=1_000)`. Advance the cursor for every Stream entry, emit valid events as exact SSE frames, send `: keep-alive\n\n` when 15 seconds elapse without a valid event, and check client disconnect before and after each bounded Redis read. This caps disconnect detection to one second without canceling an in-flight read. Log and close on Redis failure; never close the shared client in the response generator.
- [x] **Step 4: Attempt focused and API unit tests; record verification state.**

  Result: `test_job_routes.py` cannot collect because the same `_ssl.pyd` Application Control block prevents importing the existing API app before any route test runs. `test_job_events.py` -> 8 passed; root suite -> 59 passed, 4 skipped, 4 deselected; syntax compilation and `git diff --check` pass. Route behavior is therefore reviewed but not runtime-verified in this environment.

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests/test_job_routes.py services/api/tests/test_job_events.py -q`

  Expected: replay, live follow-up, headers, errors, heartbeat, corrupt-entry cursor handling, and disconnect behavior pass.
- [x] **Step 5: Review Task 2 independently.** Record the score and disposition as for Task 1. Do not start Task 3 until score is at least 95 and no blocker/important finding remains.
- [ ] **Step 6: Commit Task 2** with `feat(api): expose replayable job events over SSE` after its review gate passes.

### Task 3: Redis integration proof and completion records

**Files:**
- Modify: `docs/plans/redis-streams-sse-implementation-plan.md` (task checklist and review record)
- Create: `services/api/tests/integration/test_redis_job_events.py`
- Modify: `services/api/pyproject.toml` to declare the `redis_integration` marker
- Modify: `services/api/README.md` to use `REDIS_URL=redis://localhost:6379/2` and document opt-in Redis tests
- Modify: `docs/backend/redis-streams.md`, `docs/backend/api.md`, and `docs/main_spec.md` with final implementation status and report index
- Modify: `docs/roadmap.md`, `docs/backlog.md`, and `docs/completed-work.md` to close W02
- Create: `docs/reports/redis-streams-sse-implementation-report.md`

**Interfaces:**
- Consumes: `JobEventStore` and the stable SSE endpoint from Tasks 1–2.
- Produces: opt-in real-Redis evidence, final specs and README, result report, completed-work entry, and no database migration.

- [ ] **Step 1: Write opt-in Redis integration tests** named `test_real_redis_persists_and_replays_events_after_cursor` and `test_real_redis_stream_retains_approximately_last_100_events`. Read `MUSICSHEET_TEST_REDIS_URL`; skip if absent. Use a unique job ID for each test and delete only that test's stream key in fixture cleanup; never run `FLUSHDB`.
- [ ] **Step 2: Run the focused integration tests without the environment variable to verify they skip cleanly.** Remove only the current PowerShell process value first: `Remove-Item Env:MUSICSHEET_TEST_REDIS_URL -ErrorAction SilentlyContinue`.

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_redis_job_events.py -q`

  Expected: tests report skipped when `MUSICSHEET_TEST_REDIS_URL` is unset.
- [ ] **Step 3: Implement the real Redis integration checks** for ordered JSON events, replay after a supplied ID, post-replay live append, old cursor behavior after trimming, and approximate retention. After 300 appends assert the retained length is between 100 and 200 and that the newest event remains readable. Add the explicit `redis_integration` marker without changing the PostgreSQL marker's meaning.
- [ ] **Step 4: Start local Redis and run the opt-in tests.**

  Run: `docker compose -f docker/docker-compose.yml up -d redis`

  Then in PowerShell: `$env:MUSICSHEET_TEST_REDIS_URL = "redis://localhost:6379/2"`

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_redis_job_events.py -q -m redis_integration`

  Expected: all Redis tests pass and their unique stream keys are deleted afterward.
- [ ] **Step 5: Correct API README Redis DB index** to `/2`. Finalize the two canonical specs and `main_spec.md`; write the report with exact commands/results and plan/code-review scores; remove W02 from roadmap/backlog and add its dated result/report/review/commit record to `completed-work.md`.
- [ ] **Step 6: Run the complete verification set.** First remove inherited `MUSICSHEET_TEST_DATABASE_URL` and `MUSICSHEET_TEST_REDIS_URL` from the current PowerShell process so the default suites do not operate on an unintended external service. Run PostgreSQL integration only as a separate opt-in command after confirming its database name and marker match the guarded disposable database.

  Run: `uv run --project services/api --python 3.13 pytest services/api/tests -q`

  Run: `uv run pytest`

  Run: `git diff --check`

  Expected: API suite and root suite pass (opt-in Redis integration skips when its URL is unset), and `git diff --check` exits 0. Also rerun Task 3 Redis integration with its opt-in URL set.
- [ ] **Step 7: Review Task 3 independently.** Record score, date, range, findings, and resolutions. Do not close W02 below 95 or with unresolved blocker/important findings.
- [ ] **Step 8: Commit Task 3** with `test(api): verify Redis event replay and retention` after the review gate passes.
- [ ] **Step 9: Finalize the Task 3 report and completed-work record after review and commit.** Record the Task 3 review score and implementation commit hash. Commit the score/hash record separately if needed to avoid a self-referential commit hash.

## Acceptance Criteria

- A valid `JobProgressEvent` is stored under `job:{job_id}:events` as JSON in `data`, with approximate max length 100; publisher returns the Redis ID as text.
- The SSE endpoint verifies the PostgreSQL job, uses the supplied `Last-Event-ID` or starts at `0-0`, replays retained records in order, and continues to later events.
- SSE frames preserve Redis IDs and typed event JSON; an idle stream sends a 15-second comment heartbeat.
- Invalid event IDs return `400`; unknown jobs return `404`; missing/unavailable dependencies return sanitized `503`; mid-stream Redis errors close the stream without exposing exception details.
- Trimming bounds event history without changing PostgreSQL status authority. API README points application events at Redis DB `/2`; Celery Redis DBs remain `/0` and `/1`.
- Plan and each of the three implementation units have independent review records at 95/100 or above with no unresolved blocker/important findings.
