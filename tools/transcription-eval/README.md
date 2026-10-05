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

The W05 R3 plan defines dataset, worker and runner steps that follow the metric
implementation. Real model comparison and model selection are still pending.
