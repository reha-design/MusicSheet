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

The W05 R5 plan defines dataset, worker and runner steps. Real model comparison
and model selection are still pending.

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
