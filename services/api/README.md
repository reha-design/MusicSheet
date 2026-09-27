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
