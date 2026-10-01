# MusicSheet API

`services/api` is the FastAPI service project inside the MusicSheet Git monorepo. It uses its own Python 3.13 uv environment, lockfile, and virtual environment; it consumes `packages/common` and `packages/storage` as editable local dependencies.

## Run locally

From the repository root in PowerShell:

```powershell
Set-Location services/api
uv sync --locked --python 3.13

$env:DATABASE_URL = "postgresql://musicsheet:password@localhost:5432/musicsheet"
$env:REDIS_URL = "redis://localhost:6379/2"
$env:CELERY_BROKER_URL = "redis://localhost:6379/0"
$env:CELERY_RESULT_BACKEND = "redis://localhost:6379/1"
$env:CELERY_VISIBILITY_TIMEOUT = "3600"
$env:LOCAL_STORAGE_DIR = "../../outputs"

uv run --locked --python 3.13 musicsheet-api
```

The server listens on `127.0.0.1:8000`. `DATABASE_URL` and `REDIS_URL` may be omitted while developing; the API still starts, liveness remains healthy, and readiness reports unavailable dependencies. `LOCAL_STORAGE_DIR` defaults to `outputs`, resolved from the API process working directory. Relative values are resolved from that same directory.

## PostgreSQL job persistence

Start the Compose PostgreSQL service and set `DATABASE_URL` to the target database. From `services/api`, apply the versioned schema explicitly before using the repository:

```powershell
docker compose -f ../../docker/docker-compose.yml up -d postgres
$env:DATABASE_URL = "postgresql://musicsheet_user:<password>@localhost:5432/musicsheet"
uv run --locked --python 3.13 musicsheet-migrate
```

The command applies migration versions 1 (`jobs`, `stage_attempts`, and `artifacts`) and 2 (internal `start_job_attempts` and `workflow_dispatched_at` fields) and records them in `schema_migrations`. Repeating the command skips recorded versions. Migration DDL and its ledger entry commit together, and concurrent commands serialize through a PostgreSQL advisory lock. Apply v2 before starting any Celery worker or the maintenance command. The CLI prints applied/current versions on success and a generic failure message on error; it does not print the connection URL, host, credentials, or raw driver exception. Replace `<password>` with the local Compose password from your configuration.

The API opens an optional database pool at startup when `DATABASE_URL` is set. If the URL is missing or PostgreSQL is unavailable, startup and `/health/live` still work; `app.state.db_pool` is `None`. An opened pool closes on shutdown. Schema migrations are never run during API startup.

The API registers YouTube jobs and bounded multipart audio uploads, returns PostgreSQL snapshots, records cancellation, and lists/downloads job artifacts. Job and artifact persistence commits before the API dispatches a Celery `start_job` message containing only the job ID; a broker submission failure conditionally marks a still-`PENDING` job as `FAILED/DISPATCH_FAILED`, and a sanitized `503` includes the stable job ID if the outcome cannot be persisted or reloaded. The API also stores typed progress events in Redis Streams and serves replayable updates from `GET /api/v1/jobs/{job_id}/events`; PostgreSQL remains the authoritative job snapshot. Application event Redis uses DB `/2`, while Celery broker and result backend use `/0` and `/1`. W03 runs six-stage orchestration and records attempts/status/progress, but real download, audio/model processing, quantization, and rendering are deferred to W04–W08; an unregistered stage fails as `STAGE_NOT_CONFIGURED`. Uploads default to 100 MiB and accept WAV, MP3, M4A, FLAC, and OGG. See the [API contract](../../docs/backend/api.md), [Redis Streams contract](../../docs/backend/redis-streams.md), and [Celery spec](../../docs/backend/celery.md).

## Celery workers and stalled-job recovery

Run workers from `services/api` after applying migrations. Start one process per queue; recommended concurrency is 4–8 for I/O, 1 for GPU/AI, and 2–4 for rendering. These example commands use 4, 1, and 2:

```powershell
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q cpu_io_queue -c 4 -l info
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q gpu_ai_queue -c 1 -l info
uv run --locked --python 3.13 celery -A musicsheet_api.pipeline.celery_app:celery_app worker -Q cpu_render_queue -c 2 -l info
```

Redis defaults are split by database: broker `/0`, result backend `/1`, application event streams `/2`. `CELERY_VISIBILITY_TIMEOUT` defaults to `3600` seconds. A process repeatedly lost before its PostgreSQL claim commits can be redelivered without incrementing a durable attempt counter. The operator recovery CLI is internal and must be used only after confirming the worker is inactive:

```powershell
uv run --locked --python 3.13 musicsheet-orchestration-maintenance scan
```

Select the exact stale row and pass its values unchanged. For example, for a scan row with job ID `550e8400-e29b-41d4-a716-446655440000`, updated timestamp `2026-09-29T08:00:00+00:00`, and status `RUNNING`:

```powershell
uv run --locked --python 3.13 musicsheet-orchestration-maintenance fail-stalled --job-id "550e8400-e29b-41d4-a716-446655440000" --observed-updated-at "2026-09-29T08:00:00+00:00" --observed-status "RUNNING"
```

Recovery takes the start/current-stage advisory locks nonblocking and compares the selected timestamp and status under a PostgreSQL row lock. If the row changes, the command refuses to write; wait until the refreshed row is stale, rescan, and retry with both new values. A cancellation that won first becomes `CANCELED`; otherwise recovery sets `FAILED/WORKER_PRECLAIM_STALLED`. Later deliveries acknowledge the terminal state. W04–W08 handlers must be re-entrant if an output effect was written before completion state committed: use `(job_id, stage)` and artifact SHA-256 to recognize and reuse valid prior outputs.

### Opt-in live integration tests

The integration suite resets `public` before each database behavior test. It runs only when `MUSICSHEET_TEST_DATABASE_URL` is set, and checks on PostgreSQL that the connected database is exactly `musicsheet_test` with database comment `MUSICSHEET_DISPOSABLE_TEST_DB_V1` before any reset. Never point this variable at an application database. From the repository root, create and mark the disposable database once, then run:

```powershell
docker compose -f docker/docker-compose.yml up -d postgres
docker exec musicsheet_postgres psql -U musicsheet_user -d postgres -c "CREATE DATABASE musicsheet_test"
docker exec musicsheet_postgres psql -U musicsheet_user -d postgres -c "COMMENT ON DATABASE musicsheet_test IS 'MUSICSHEET_DISPOSABLE_TEST_DB_V1'"
$env:MUSICSHEET_TEST_DATABASE_URL = "postgresql://musicsheet_user:<password>@localhost:5432/musicsheet_test"
uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_postgres_persistence.py -q
```

The `CREATE DATABASE` command is needed only if the database does not already exist. An unset test URL skips these tests. A wrong database name or missing/wrong marker fails the guard without a schema reset.

### Opt-in Redis Streams tests

Redis integration tests run only when `MUSICSHEET_TEST_REDIS_URL` is set. They use unique job stream keys and delete only those keys after each test; they never run `FLUSHDB`. For a local Compose Redis instance, use the application event database `/2`:

```powershell
docker compose -f docker/docker-compose.yml up -d redis
$env:MUSICSHEET_TEST_REDIS_URL = "redis://localhost:6379/2"
uv run --project services/api --python 3.13 pytest services/api/tests/integration/test_redis_job_events.py -q -m redis_integration
Remove-Item Env:MUSICSHEET_TEST_REDIS_URL
```

When the variable is unset, the Redis integration tests skip without importing or connecting a Redis client. Keep the test URL pointed at a test instance; the tests remove only their generated stream keys.

## Health endpoints

### `GET /health/live`

Confirms that the API process can handle a request. It does not contact PostgreSQL, Redis, storage, GPU tools, FFmpeg, or MuseScore.

```powershell
curl.exe -i http://127.0.0.1:8000/health/live
```

```json
{"status":"ok"}
```

### `GET /health/ready`

Runs PostgreSQL `SELECT 1`, Redis `PING`, and a temporary write/delete check under `LOCAL_STORAGE_DIR` concurrently. Each check has a one-second limit. The response is HTTP `200` when all checks are `ok`, otherwise HTTP `503`; it contains only check names and `ok`/`unavailable` states. A timed-out filesystem call continues in its worker thread and removes its temporary file when the call finishes; a permanently blocked filesystem call can leave that worker and file pending.

```powershell
curl.exe -i http://127.0.0.1:8000/health/ready
```

```json
{"status":"ready","checks":{"postgres":"ok","redis":"ok","storage":"ok"}}
```

### `GET /health/detail`

Returns best-effort host diagnostics with HTTP `200`, even when one or more tools are missing or fail. It reports the first GPU listed by `nvidia-smi` (name, driver version, total/free memory in MB), plus the first version line from FFmpeg and MuseScore. Each command is limited to two seconds.

```powershell
curl.exe -i http://127.0.0.1:8000/health/detail
```

```json
{
  "gpu": {"status":"ok","name":"NVIDIA GeForce RTX 4060","driver_version":"555.42","memory_total_mb":8192,"memory_free_mb":4096},
  "ffmpeg": {"status":"ok","version":"ffmpeg version 7.1.1"},
  "musescore": {"status":"unavailable"}
}
```

The diagnostic executables are found on `PATH` by default. `NVIDIA_SMI_BIN`, `FFMPEG_BIN`, and `MUSESCORE_BIN` can each select an executable explicitly. Diagnostic results never change readiness. GPU presence from `nvidia-smi` does not prove that a PyTorch/CUDA model can run. These are diagnostics for the API host; a separately deployed worker will need its own health reporting to expose remote worker hardware or tools.

Responses omit connection strings, local paths, raw command output, standard error, and exception messages.
