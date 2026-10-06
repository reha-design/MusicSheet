"""Small wire fixtures shared by adapter tests; no model imports."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from musicsheet_common import ArtifactRole
from musicsheet_pipeline.contracts import ProviderIdentity, StageContext, StageMessage
from musicsheet_storage import LocalStorage

PROVENANCE = {"id": "spotify-basic-pitch", "package_version": "0.4.0",
    "source_commit": "049dc8a01a170c2370d7b246ec1c2067e060c3bf", "model_asset": "nmp.onnx",
    "supports_pedal": False, "confidence_semantics": "uncalibrated_note_activation_mean"}
IDENTITY = ProviderIdentity("spotify-basic-pitch", "0.1.0", {},
    frozenset({ArtifactRole.SEPARATED_AUDIO}),
    frozenset({ArtifactRole.RAW_TRANSCRIPTION, ArtifactRole.MIDI}))


def payload(*, notes=True):
    return {"schema_version": 1, "provider": dict(PROVENANCE), "pedal_events": [],
        "note_events": [{"note_id": "n1", "pitch": 60, "onset_sec": 0.0, "offset_sec": .2,
            "activation": None, "velocity_prediction": None, "amt_confidence": .5,
            "source_chunk": None}] if notes else []}


def midi(track=b"\x00\xff\x2f\x00"):
    return b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0MTrk" + len(track).to_bytes(4, "big") + track


def result_files(root, value=None, *, midi_bytes=None):
    root.mkdir()
    raw, mid = root / "raw_transcription.json", root / "transcription.mid"
    raw.write_text(json.dumps(payload() if value is None else value), encoding="utf-8")
    mid.write_bytes(midi() if midi_bytes is None else midi_bytes)
    return raw, mid


def context(root, inputs=(), *, storage=None):
    return StageContext(StageMessage(str(uuid4()), "TRANSCRIBE", 1), str(uuid4()),
        "UPLOAD", None, "piano", tuple(inputs), storage or LocalStorage(root / "storage"), asyncio.Event())
