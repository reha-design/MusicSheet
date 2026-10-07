# Piano AMT evaluation worker

W05 uses this independent Python 3.12 environment to evaluate the pinned
[piano-transcription-inference source](https://github.com/qiuqiangkong/piano_transcription_inference/tree/0226e74cbc805660e34bbd6a8fed2083890ebb88),
package 0.0.6, `Note_pedal`, and PyTorch 2.10.0+cpu. The root, API and Basic Pitch
environments remain separate. This CLI is an evaluation candidate; it is not a
registered product provider. Verification results and support limits are recorded
in [the Task3 report](../../../docs/reports/piano-amt-evaluation-worker-report.md).

Run these commands from the repository root. Installation and checkpoint
preparation happen before inference:

```powershell
uv --cache-dir outputs/.uv-cache sync --locked --project services/ml/piano-amt-worker --python 3.12
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 python -c "from pathlib import Path; from musicsheet_transcription_eval.checkpoint import prepare_checkpoint; print(prepare_checkpoint(Path('D:/develop/MusicSheet/models/w05')))"
```

Preparation checks the official [Zenodo record 4034264 metadata](https://zenodo.org/api/records/4034264),
171,966,578 bytes and MD5 `22b961b77c1878239fec963362097045`, then calculates SHA256.
It refuses redirects, encoded HTTP bodies and changed or invalid cached weights.
Limits are 4 MiB metadata, 180 MiB total transfer, 60 seconds of HTTP I/O
inactivity and 10 minutes overall. Async streaming cancels pending headers/body
reads at the overall deadline and closes resources before returning. Call the
synchronous preparation function outside an active event loop for an uncached
download; otherwise it raises `ValueError` before starting work.
Only owned partial files are removed. A verified cached
file is reused without network access. Weights are [CC BY 4.0](https://zenodo.org/records/4034264);
credit Qiuqiang Kong and the linked release when using them. MAESTRO's
noncommercial dataset terms are separate.

Pass an absolute mono PCM16 WAV at exactly 16,000 Hz, with 1–480,000 complete
frames (up to 30 seconds), and a fresh absolute output directory:

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 piano-amt-worker --input-audio D:/path/input-16000.wav --output-dir D:/path/new-output --checkpoint "D:/develop/MusicSheet/models/w05/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth" --checkpoint-sha256 c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141 --device cpu
```

The worker checks regular, unlinked paths and checkpoint integrity before lazy
model import, safely loads weights with `weights_only=True`, and checks the
official nested note/pedal state against the pinned model before construction.
Inference uses float32 audio, one torch intra/inter-op thread, a 160,000-sample
segment, and upstream defaults: onset 0.3, offset 0.3, frame 0.1, pedal offset 0.2.
There is no inference-time installer, download or shell command.

Outputs are `raw_transcription.json` (evaluation wire version 1, <=8 MiB) and
`transcription.mid` (<=16 MiB, <=100,000 events including tempo/end). The JSON
records source/package/model/checkpoint/input/device/dtype/options/runtime,
`duration_sec`, `notes` (`pitch,onset,offset,velocity`) and `pedals`
(`kind,onset,offset,value`). Notes cover piano pitches 21–108; pedals are sustain.
Finite intervals must satisfy `0 <= onset < offset <= duration+1`. Velocity
is an integer 1–127; sustain values are integers 64–127. Empty predictions are valid. Confidence
is not invented. Existing outputs are preserved; publication failures remove
only files created by this invocation.

MIDI uses 384 ticks/beat and 500,000 microseconds/beat. Chronological event order
is preserved before truncating timestamps to ticks; at an identical timestamp,
note-off/pedal-up precedes pedal-down/note-on. JSON retains the original times.
Every interval must remain positive after tick quantization. A complete Mido
semantic roundtrip must reconstruct the expected note/pedal multiset at tick
resolution. Unmatched, overlapping, open or zero-tick intervals are rejected
before publication, without changing values/times or dropping events.
Exit codes: 0 success/help, 2 arguments/input/checkpoint setup, 3 inference,
4 invalid or failed output. Failure diagnostics omit paths and exception text.

Default tests require neither weights nor network and use fake model backends:

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 pytest -c services/ml/piano-amt-worker/pyproject.toml services/ml/piano-amt-worker/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/new-worker-check
```

The actual-model test requires `MUSICSHEET_W05_LIVE=1` and explicit
`MUSICSHEET_PIANO_AMT_AUDIO`, `MUSICSHEET_PIANO_AMT_CHECKPOINT` and
`MUSICSHEET_PIANO_AMT_CHECKPOINT_SHA256`. It acquires no files. A missing live
configuration fails when explicitly enabled. Actual smoke has no accuracy
reference and does not establish MAESTRO F1 or a model-selection result.
The verified smoke uses the complete 16-second CC0 fixture followed by 14 seconds
of PCM silence to match W05's fixed 30-second input. A 16-second attempt failed
because the pinned upstream's padded tail exceeded `duration+1`; it remains a
recorded failure. Short inputs may return exit 4 for that reason. The wrapper
preserves native predictions and enforces its output bounds.
