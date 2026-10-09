# Transcription evaluator

Independent Python 3.13 uv project. This environment contains evaluation tools
and shared process utilities; model inference stays in separately installed
Python 3.12 workers. No model or dataset is downloaded during imports or tests.

Run from the repository root:

```powershell
uv --cache-dir outputs/.uv-cache sync --locked --project tools/transcription-eval --python 3.13
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests -q
```

`uv --project` selects the environment, without changing the current directory.
Use explicit pytest configuration and test paths. Each verification run uses a
new `--basetemp` under `outputs/.verification-w05`.
Actual audio unit checks use installed FFmpeg and skip if it is absent. The
Windows ACL regression also needs PowerShell 7 (`pwsh`); it skips on other
platforms or when that probe runtime is absent. Preparation itself needs no
PowerShell subprocess.

The W05 plan defines dataset, worker and runner steps. Task4 adds comparative
execution and verified reporting. Task5 records the first actual CPU session;
its observed outcome is documented in the
[evaluation report](../../docs/reports/transcription-model-evaluation-report.md).

Prepare the fixed twelve MAESTRO v3/v2 test recordings (noncommercial research
only, CC-BY-NC-SA-4.0). Supply an installed FFmpeg executable explicitly:

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 transcription-eval prepare --output-root D:/develop/MusicSheet/outputs/w05-evaluation/task2-20261006 --manifest D:/develop/MusicSheet/docs/evaluations/maestro-w05-manifest.json --ffmpeg C:/ffmpeg-6.0-essentials_build/ffmpeg-6.0-essentials_build/bin/ffmpeg.exe
```

The command downloads official metadata, fixes selection before acquisition,
and streams only the selected WAV/MIDI ZIP members. ZIP64 parsing and CRC use
Python's zipfile library. A 200 response is rejected before its body is read.
Limits: 4 MiB metadata, 16 MiB ZIP reads, 1 MiB Range requests, 2 GiB/member,
6 GiB transferred including retries, 8 GiB decoded, 10 GiB minimum free space,
60 seconds/request, 30 minutes/acquisition, at most two retries.

`--local-source` accepts an official SHA256-verified ZIP or an extracted directory
with a validated source receipt. A complete destination receipt enables offline
reuse. Interrupted acquisition preserves verified members and removes owned
partial files; an incomplete run requires a fresh output root rather than
silently replacing recordings. Preparation refuses an existing input directory
or frozen manifest. For offline validation, call `load_manifest(path,
run_root=...)`; it checks original sources, metadata, fixed selection/crop,
derived inputs, references and receipts. It does not import models.
`write_manifest` only serializes the frozen structure and hashes its payload;
it does not replace preparation validation. Always load and verify its pending
file against the run root before publishing it, as the CLI does.

Both candidates use the same 30-second stereo PCM16 crop, float64 `(L+R)/2`,
explicit swr settings and ties-to-even saturated PCM16 quantization. The 22050 Hz
and 16000 Hz mono inputs contain exactly 661500 and 480000 frames. The tracked
manifest contains paths and hashes; audio, MIDI and reference arrays stay under
ignored `outputs/`. Partial Range acquisition verifies CRC and per-member SHA256,
without claiming verification of the full 101 GB archive's published SHA256.

Task3 provides `prepare_checkpoint(destination: Path) -> dict[str, object]` in
`musicsheet_transcription_eval.checkpoint`. It prepares the fixed Zenodo4034264
Note_pedal checkpoint under an absolute directory, checking official metadata,
license, exact bytes/MD5 and the computed SHA256. It rechecks cached files without
network, preserves invalid existing files, and cleans only its own `.part` file.
The 4 MiB metadata/180 MiB transfer/60-second HTTP I/O inactivity/10-minute overall
limits are independent of MAESTRO acquisition. Async streaming interrupts pending
headers/body reads at the overall deadline and closes resources and owned partials.
Call this synchronous function outside an active event loop for uncached downloads;
an active loop is rejected before creating a coroutine or starting network/file work.
A valid cache still returns without network. This preparation module imports no model.
Run the [isolated worker](../../services/ml/piano-amt-worker/README.md) separately
with the returned checkpoint SHA256.

## Comparative CPU execution and verified report

Install both isolated workers and FFmpeg before execution. `run` never installs
packages, downloads assets, or changes the product provider. Use absolute paths:

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 transcription-eval run --manifest D:/develop/MusicSheet/docs/evaluations/maestro-w05-manifest.json --input-root D:/develop/MusicSheet/outputs/w05-evaluation/task2-20261006 --basic-python D:/develop/MusicSheet/services/ml/basic-pitch-worker/.venv/Scripts/python.exe --piano-python D:/develop/MusicSheet/services/ml/piano-amt-worker/.venv/Scripts/python.exe --checkpoint "D:/develop/MusicSheet/models/w05/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth" --checkpoint-sha256 c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141 --output-root D:/develop/MusicSheet/outputs/w05-evaluation/task5 --ffmpeg C:/ffmpeg-6.0-essentials_build/ffmpeg-6.0-essentials_build/bin/ffmpeg.exe
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 transcription-eval report --run-dir D:/develop/MusicSheet/outputs/w05-evaluation/task5/cpu-REPLACE_WITH_PRINTED_RUN_ID --output D:/develop/MusicSheet/docs/evaluations/new-comparison-report.md
```

These are reproduction instructions; use a fresh output root for any new session.
`run` prints its new `cpu-<uuid>` directory name and summary SHA256. An omitted
`--ffmpeg` resolves an installed executable on PATH. Output roots stay under
repository `outputs`; CLI reports stay under `docs`. Existing runs/reports are
never replaced or resumed. Keep all run artifacts to verify a report later.

The captured-session test never launches a model. By default it skips explicitly.
Set `MUSICSHEET_W05_LIVE=1` and `MUSICSHEET_W05_RUN_DIR` to the absolute captured
run directory, then run `tests/test_live_evaluation.py` with this project's explicit
pytest configuration. Missing configuration skips; an invalid configured run fails.
It verifies the frozen inputs, candidates, native output provenance/default options,
both output files, 72 scheduled terminal states and first-run populations. A passing
integrity check can describe a partial or `no_selection` session; it does not mean
that a comparison succeeded or that a product default was selected. Restore the
environment after running it, and do not enable other workers' live tests by accident.

Four fresh non-scoring preflight runs use repeated/cropped CC0 audio. A failed
preflight or excessive CPU estimate leaves all 72 benchmark slots `not_run`.
Each candidate has 36 scheduled slots; only its first 12 measure accuracy.
Repetitions and optional diagnostics preserve the first failure and all raw
denominators. Limits are 300 seconds/slot and 7200 seconds/session, including
preflight execution and diagnostics. Cancellation drains owned processes/I/O
before recording remaining slots as `not_run`.

Reports revalidate summary/artifact hashes and reconstruct the selection from
immutable records. Size-limited raw files remain preserved but explicitly
unverified, forcing `no_selection`. Generic worker exit3/4 remains unresolved;
repetition alone is not proof of a model cause. A Piano choice is
`selected_pending_integration`, without changing Basic Pitch product settings.
Exit status: 0 recorded session/report (including no selection), 4 setup/report
failure, 130 cancellation, and 2 argument parsing failure.

Task4 evidence and limitations are in the [runner report](../../docs/reports/transcription-evaluation-runner-report.md).
