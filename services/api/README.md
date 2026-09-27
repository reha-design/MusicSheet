# MusicSheet API

`services/api` is the FastAPI service project inside the MusicSheet Git monorepo. It uses its own Python 3.13 uv environment, lockfile, and virtual environment; it consumes `packages/common` and `packages/storage` as editable local dependencies.

## Run locally

From the repository root in PowerShell:

```powershell
Set-Location services/api
uv sync --locked --python 3.13

$env:DATABASE_URL = "postgresql://musicsheet:password@localhost:5432/musicsheet"
$env:REDIS_URL = "redis://localhost:6379/0"
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

The command applies migration version 1 (`jobs`, `stage_attempts`, and `artifacts`) and records it in `schema_migrations`. Repeating the command skips recorded versions. Migration DDL and its ledger entry commit together, and concurrent commands serialize through a PostgreSQL advisory lock. The CLI prints applied/current versions on success and a generic failure message on error; it does not print the connection URL, host, credentials, or raw driver exception. Replace `<password>` with the local Compose password from your configuration.

The API opens an optional database pool at startup when `DATABASE_URL` is set. If the URL is missing or PostgreSQL is unavailable, startup and `/health/live` still work; `app.state.db_pool` is `None`. An opened pool closes on shutdown. Schema migrations are never run during API startup.

The W01 REST API registers YouTube jobs without contacting YouTube, accepts bounded multipart audio uploads, returns job snapshots, records cooperative cancellation requests, lists job-scoped artifacts, and streams artifact downloads. `JobRepository` supports job creation, lookup, progress updates, and conditional cancellation; `ArtifactRepository` supports transactional insert and job-scoped list/lookup. Upload defaults to 100 MiB per file and accepts WAV, MP3, M4A, FLAC, and OGG. Downloads include the recorded content length; a mid-stream storage error ends the response with a short body and logs only a generic warning. Jobs remain `PENDING` until Celery dispatch is implemented; cancellation remains `CANCEL_REQUESTED` until a worker processes it. W01 does not fetch media or run models. See the [API contract](../../docs/backend/api.md) for response and failure details. `stage_attempts` persistence, SSE, and pipeline dispatch are not implemented.

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
