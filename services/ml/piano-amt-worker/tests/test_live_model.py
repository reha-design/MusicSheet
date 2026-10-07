"""Explicit opt-in smoke; default tests neither import nor acquire models."""

import os
from pathlib import Path

import pytest


@pytest.mark.live_model
def test_installed_cpu_checkpoint_and_actual_audio(tmp_path):
    if os.environ.get("MUSICSHEET_W05_LIVE") != "1":
        pytest.skip("explicit W05 live opt-in required")
    from musicsheet_piano_amt_worker.cli import main
    import json
    import mido
    audio = Path(os.environ["MUSICSHEET_PIANO_AMT_AUDIO"])
    checkpoint = Path(os.environ["MUSICSHEET_PIANO_AMT_CHECKPOINT"])
    digest = os.environ["MUSICSHEET_PIANO_AMT_CHECKPOINT_SHA256"]
    output = tmp_path/"actual-result"
    assert main(["--input-audio",str(audio),"--checkpoint",str(checkpoint),
        "--checkpoint-sha256",digest,"--device","cpu","--output-dir",str(output)]) == 0
    result = json.loads((output/"raw_transcription.json").read_text())
    assert result["checkpoint_sha256"] == digest and result["device"] == "cpu"
    assert result["dtype"] == "float32" and result["source_commit"] == "0226e74cbc805660e34bbd6a8fed2083890ebb88"
    assert list(mido.MidiFile(output/"transcription.mid"))[-1].type == "end_of_track"
