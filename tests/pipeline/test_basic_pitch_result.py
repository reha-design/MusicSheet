import json
import threading

import pytest

from musicsheet_pipeline.basic_pitch.result import validate_result_files
from musicsheet_pipeline.contracts import InvalidArtifact
from .basic_pitch_support import midi, payload, result_files


@pytest.mark.parametrize("notes", [True, False])
def test_valid_result_and_empty_notes(tmp_path, notes):
    files = result_files(tmp_path / "result", payload(notes=notes))
    assert validate_result_files(files[0].parent, stop=threading.Event()) == files


@pytest.mark.parametrize("field,value", [("pitch", True), ("pitch", "60"), ("pitch", 128),
    ("onset_sec", "0"), ("onset_sec", True), ("onset_sec", -1), ("offset_sec", -.1),
    ("amt_confidence", float("nan")), ("amt_confidence", float("inf")),
    ("activation", "0.5"), ("velocity_prediction", True), ("source_chunk", "1"),
    ("source_chunk", False), ("note_id", "")])
def test_invalid_note_wire_is_rejected(tmp_path, field, value):
    data = payload()
    data["note_events"][0][field] = value
    files = result_files(tmp_path / "result", data)
    with pytest.raises(InvalidArtifact):
        validate_result_files(files[0].parent, stop=threading.Event())


@pytest.mark.parametrize("case", ["duplicate-note", "duplicate-key", "provenance", "pedal",
    "schema-bool", "schema-string", "missing-midi", "bad-utf8", "huge-json", "huge-midi"])
def test_invalid_envelope_or_files_are_rejected(tmp_path, case):
    data = payload()
    if case == "duplicate-note":
        data["note_events"] *= 2
    if case == "provenance":
        data["provider"]["source_commit"] = "forged"
    if case == "pedal":
        data["pedal_events"] = [{"onset_sec": 0, "offset_sec": 1}]
    if case.startswith("schema"):
        data["schema_version"] = True if case == "schema-bool" else "1"
    raw, mid = result_files(tmp_path / "result", data)
    if case == "duplicate-key":
        raw.write_text(raw.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    if case == "missing-midi":
        mid.unlink()
    if case == "bad-utf8":
        raw.write_bytes(b"\xff")
    if case.startswith("huge"):
        target, limit = (raw, 8 * 1024 * 1024) if case == "huge-json" else (mid, 16 * 1024 * 1024)
        with target.open("wb") as stream:
            stream.seek(limit)
            stream.write(b"x")
    with pytest.raises(InvalidArtifact):
        validate_result_files(raw.parent, stop=threading.Event())


@pytest.mark.parametrize("data", [midi()[:14], midi()[:-1], midi(b"\x00\x90\x3c\x40"),
    midi() + b"tail", midi(b"\x00\xff\x2f\x00\x00\xff\x2f\x00"),
    midi(b"\x81\x81\x81\x81\x00\xff\x2f\x00")])
def test_invalid_midi_structure_is_rejected(tmp_path, data):
    raw, _ = result_files(tmp_path / "result", midi_bytes=data)
    with pytest.raises(InvalidArtifact):
        validate_result_files(raw.parent, stop=threading.Event())


def test_unknown_fields_and_nullable_fields_remain_compatible(tmp_path):
    data = payload()
    data["extension"] = {"future": True}
    data["note_events"][0]["extra"] = "allowed"
    files = result_files(tmp_path / "result", data)
    assert validate_result_files(files[0].parent, stop=threading.Event()) == files


def test_result_symlink_is_rejected(tmp_path):
    raw, mid = result_files(tmp_path / "result")
    outside = tmp_path / "outside"
    outside.write_bytes(mid.read_bytes())
    mid.unlink()
    try:
        mid.symlink_to(outside)
    except OSError:
        pytest.skip("OS does not grant symbolic link creation")
    with pytest.raises(InvalidArtifact):
        validate_result_files(raw.parent, stop=threading.Event())
