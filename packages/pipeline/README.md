# MusicSheet pipeline

Python 3.13 orchestration is separate from the API and model environments. Runtime providers default to an empty registry: registered work fails with `PROVIDER_NOT_CONFIGURED` until later provider implementation. W03 test providers remain in tests. No actual YouTube download, inference or score rendering is implemented here.

The API atomically inserts its DOWNLOAD outbox reservation with the new job (and upload metadata). It requires migration v2, applied explicitly with the API environment's `musicsheet-migrate`. The dispatcher publishes a row and only then commits `published_at`. Broker outage leaves registration available and reservations pending. Publish-before-commit failure can deliver duplicates; advisory ownership and completed attempt fingerprints fence duplicate computation. Infrastructure delivery retries are unlimited; provider attempts are capped at three per stage with durable 5/10 second reservations.

Set `DATABASE_URL`, `CELERY_BROKER_URL`, `REDIS_URL` and `LOCAL_STORAGE_DIR`. `CELERY_RESULT_BACKEND` is optional; PostgreSQL owns job state. URLs must use PostgreSQL and Redis schemes. Relative storage paths resolve from the process working directory. Provider identities are limited to 64 character names, 32 character versions and 64KiB normalized JSON configuration. Only a hash of source/configuration/input identity is stored as the fingerprint. New outputs use `attempt_{attempt_id}_` filenames; exact registered input reuse preserves original metadata.

From repository root after syncing the root and API uv environments:

```sh
uv run --project services/api --locked --python 3.13 musicsheet-migrate
uv run --project . --locked --python 3.13 musicsheet-dispatch --once
uv run --project . --locked --python 3.13 musicsheet-dispatch --poll-interval 1
```

Worker commands run on Linux/WSL2. Use CPU I/O concurrency4–8, GPU concurrency1 and rendering concurrency2–4 according to available resources:

```sh
uv run --project . --locked --python 3.13 celery -A musicsheet_pipeline.celery_app:app worker -Q cpu_io_queue --concurrency 4
uv run --project . --locked --python 3.13 celery -A musicsheet_pipeline.celery_app:app worker -Q gpu_ai_queue --concurrency 1
uv run --project . --locked --python 3.13 celery -A musicsheet_pipeline.celery_app:app worker -Q cpu_render_queue --concurrency 2
```

Past PENDING rows without attempts or reservations stay dormant until an explicit finite recovery run:

```sh
uv run --project . --locked --python 3.13 musicsheet-dispatch --recover-pending
```

JSON serialization only, late ACK, reject-on-worker-loss and prefetch1 are configured. Broker visibility is3600 seconds, so recovery of lost deliveries can wait that long. Database connect/command timeouts are2/5 seconds; broker socket/connect timeouts2 seconds. A failed infrastructure retry publish waits5 seconds before requeueing the current delivery. Event publication uses the shared W02 bounded stream after DB commit; event loss logs a fixed warning and never rolls back committed work. SSE replay cannot restore an event that was never published.

Artifact validation runs owned worker threads and reads64KiB chunks. Cancellation stops new reads and drains the current read before closing; it cannot forcibly interrupt stalled OS file I/O. Providers must cooperate with cancellation; adapters own termination of subprocesses/threads. Files written before a failed transaction can remain orphaned for later cleanup.

Windows unit/eager checks are distinct from actual Linux process recovery. Live opt-in harness and evidence are recorded in the Task4 implementation report.
