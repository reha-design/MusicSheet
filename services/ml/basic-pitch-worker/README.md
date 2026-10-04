# Basic Pitch isolated worker

This is a standalone uv project for the Basic Pitch proof of concept. The root backend stays on Python 3.13; this worker uses its own Python 3.12 environment, `uv.lock`, and `.venv`. Running `uv sync` at the repository root does not install the worker or its model dependencies.

## Install and run

From the repository root:

```powershell
uv sync --locked --project services/ml/basic-pitch-worker --python 3.12
uv run --project services/ml/basic-pitch-worker --python 3.12 basic-pitch-worker `
  --input-audio tests/fixtures/audio/basic_pitch_smoke.wav `
  --output-dir temp/basic-pitch-result
```

The output directory must not already exist. Input must be a readable WAV with one channel at 22,050 Hz. The worker does not resample or change channel count.

## Runtime pinned for this proof of concept

- Python: `>=3.12,<3.13` (`.python-version` selects 3.12).
- Basic Pitch: `0.4.0`, Git commit `049dc8a01a170c2370d7b246ec1c2067e060c3bf`.
- ONNX Runtime: CPU package, `1.30.0` in the validated lock environment.
- `pretty-midi`: `0.2.11.post0` in the lockfile.
- TensorFlow and `musicsheet_common` are not installed in this project.

## Platform validation

The product `BasicPitchProvider` now invokes this preinstalled worker from Python3.13 using a fixed isolated bootstrap. It prepares local WAV input and validates both JSON and MIDI before storage. Set `TRANSCRIPTION_PROVIDER=basic-pitch`, `BASIC_PITCH_PYTHON` and `FFMPEG_EXECUTABLE` to absolute installed executable paths in the orchestration environment; the default remains disabled. Windows actual model and PostgreSQL registration, duplicate delivery, cancellation and connection-loss fencing passed W04 verification. Linux subprocess/root tests passed, while Linux actual model/Celery execution remains unverified. See the [W04 report](../../../docs/reports/basic-pitch-pipeline-implementation-report.md).

This proof of concept was validated on Windows with `CPUExecutionProvider`. macOS and Linux are unverified and are outside the supported scope. Basic Pitch chooses its inference backend using the pinned upstream defaults; before adding another operating system, verify the loaded model and actual ONNX Runtime provider on that platform. The `nmp.onnx` metadata value alone does not establish which backend ran.

## Outputs and exit codes

- `raw_transcription.json`: schema version 1 result with provider provenance and note events.
- `transcription.mid`: written when Basic Pitch returns MIDI data.
- `0`: success; `2`: invalid input audio; `3`: model loading or prediction failure; `4`: result validation or output failure.

JSON and optional MIDI are staged together and published as a new output directory. A failed run does not publish a partial output directory. The model confidence is an uncalibrated mean note activation, and this Basic Pitch provider does not produce pedal events. This PoC does not make Basic Pitch the product's default provider.

See [the environment report](../../../docs/reports/basic-pitch-worker-environment-report.md), [the audio mapping report](../../../docs/reports/basic-pitch-audio-mapping-report.md), [the CLI report](../../../docs/reports/basic-pitch-cli-report.md), and [the smoke report](../../../docs/reports/basic-pitch-worker-smoke-report.md).
