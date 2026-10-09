"""Model-free native output validation and metric conversion."""
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import threading

import mido

from musicsheet_pipeline.basic_pitch.io import check_stop
from musicsheet_pipeline.basic_pitch.result import PROVENANCE, validate_result_files

from .contracts import Candidate, Events, EvaluationLimitError, Note, Pedal, ScoredEvents, finite, integer
from .manifest import JSON_LIMIT, digest_file, regular_file, safe_path, strict_json
from .metrics import score_notes, scoring_events, velocity_mae
from .reference import parse_reference, read_validated_midi_bytes
from . import reference as midi_limits

PIANO_OPTIONS = {"onset_threshold": .3, "offset_threshold": .3, "frame_threshold": .1,
                 "pedal_offset_threshold": .2, "segment_samples": 160000, "sample_rate": 16000}


def read_json(path: Path, *, stop: threading.Event):
    regular_file(path)
    if path.stat().st_size > JSON_LIMIT: raise EvaluationLimitError("json_byte_limit")
    data = bytearray()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            check_stop(stop); data.extend(chunk)
            if len(data) > JSON_LIMIT: raise EvaluationLimitError("json_byte_limit")
    check_stop(stop)
    return strict_json(bytes(data))


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys): raise ValueError("invalid wire fields")


def events_from_dict(value) -> Events:
    exact(value, ("notes", "pedals"))
    if type(value["notes"]) is not list or type(value["pedals"]) is not list: raise ValueError("invalid events")
    notes, pedals = [], []
    for n in value["notes"]:
        exact(n, ("pitch", "onset", "offset", "velocity")); notes.append(Note(**n))
    for p in value["pedals"]:
        exact(p, ("kind", "onset", "offset", "value")); pedals.append(Pedal(**p))
    return Events(tuple(notes), tuple(pedals))


def _piano(wire, candidate, midi_path, input_sha256, stop):
    expected = dict(schema_version=1, source_commit=candidate.source_commit,
        source_url="https://github.com/qiuqiangkong/piano_transcription_inference", package_version="0.0.6",
        model="Note_pedal", checkpoint_name="CRNN_note_F1=0.9677_pedal_F1=0.9186.pth",
        checkpoint_sha256=candidate.checkpoint_sha256, input_sha256=input_sha256, device=candidate.device,
        dtype="float32", options=PIANO_OPTIONS, runtime={"torch_num_threads": 1, "torch_num_interop_threads": 1}, duration_sec=30)
    exact(wire, (*expected, "notes", "pedals"))
    for key, value in expected.items():
        if wire[key] != value: raise ValueError("candidate receipt mismatch")
    integer(wire["schema_version"], 1, 1); finite(wire["duration_sec"], 30, 30)
    for key in ("options", "runtime"):
        exact(wire[key], expected[key])
        for field, value in wire[key].items():
            if type(value) is not type(expected[key][field]): raise ValueError("invalid runtime number")
    events = events_from_dict({key: wire[key] for key in ("notes", "pedals")})
    for note in events.notes:
        integer(note.pitch, 21, 108); integer(note.velocity, 1, 127)
    for pedal in events.pedals:
        if pedal.kind != "sustain": raise ValueError("invalid pedal")
        integer(pedal.value, 64, 127)
    for event in (*events.notes, *events.pedals):
        if int(event.offset * 768) <= int(event.onset * 768): raise ValueError("invalid quantized interval")
    native = mido.MidiFile(midi_path)
    tempos = [(index, message) for index, message in enumerate(native.tracks[0]) if message.type == "set_tempo"]
    if native.type != 0 or native.ticks_per_beat != 384 or len(native.tracks) != 1 or len(tempos) != 1:
        raise ValueError("invalid native MIDI timebase")
    if tempos[0][0] != 0 or tempos[0][1].time != 0 or tempos[0][1].tempo != 500000:
        raise ValueError("invalid native MIDI tempo")
    parsed = parse_reference(midi_path).key_release
    def notes(values, quantized):
        return Counter((n.pitch, int(n.onset * 768) if quantized else round(n.onset * 768),
            int(n.offset * 768) if quantized else round(n.offset * 768), n.velocity) for n in values)
    def pedals(values, quantized):
        return Counter((p.kind, int(p.onset * 768) if quantized else round(p.onset * 768),
            int(p.offset * 768) if quantized else round(p.offset * 768), p.value) for p in values)
    if notes(events.notes, True) != notes(parsed.notes, False) or pedals(events.pedals, True) != pedals(parsed.pedals, False):
        raise ValueError("JSON MIDI mismatch")
    check_stop(stop)
    return events


def normalize_output(candidate: Candidate, output_dir: Path, *, input_sha256: str, stop: threading.Event) -> Events:
    # Dispose raw gate bytes before the existing validator or any Mido object.
    midi = safe_path(output_dir, "transcription.mid")
    try: regular_file(midi)
    except FileNotFoundError: raise ValueError("missing MIDI output") from None
    if midi.stat().st_size > midi_limits.MIDI_LIMIT: raise EvaluationLimitError("midi_byte_limit")
    read_validated_midi_bytes(midi)
    check_stop(stop)
    raw = safe_path(output_dir, "raw_transcription.json")
    wire = read_json(raw, stop=stop)
    if candidate.id == "basic_pitch":
        validate_result_files(output_dir, stop=stop)
        exact(wire, ("schema_version", "provider", "note_events", "pedal_events"))
        exact(wire["provider"], PROVENANCE)
        if any(type(wire["provider"][key]) is not type(value) or wire["provider"][key] != value for key, value in PROVENANCE.items()):
            raise ValueError("invalid Basic Pitch source")
        if wire["provider"]["source_commit"] != candidate.source_commit: raise ValueError("source mismatch")
        notes = []
        for n in wire["note_events"]:
            check_stop(stop)
            exact(n, ("note_id", "pitch", "onset_sec", "offset_sec", "velocity_prediction", "activation", "amt_confidence", "source_chunk"))
            notes.append(Note(n["pitch"], n["onset_sec"], n["offset_sec"], n["velocity_prediction"]))
        events = Events(tuple(notes), ())
    elif candidate.id == "piano_amt":
        events = _piano(wire, candidate, midi, input_sha256, stop)
    else: raise ValueError("unknown candidate")
    if any(event.offset > 31 for event in (*events.notes, *events.pedals)): raise ValueError("padding bound")
    check_stop(stop)
    return events


def read_reference(entry, *, stop):
    if digest_file(entry.reference_path, stop=stop) != entry.reference_sha256: raise ValueError("reference hash mismatch")
    value = read_json(entry.reference_path, stop=stop)
    exact(value, ("key_release", "sustain"))
    result = {}
    for name, ref in value.items():
        exact(ref, ("events", "censored_count"))
        result[name] = ScoredEvents(events_from_dict(ref["events"]), ref["censored_count"])
    return result


def score_output(entry, events: Events, *, stop: threading.Event) -> dict:
    reference = read_reference(entry, stop=stop)
    predicted = scoring_events(events, start_sec=0)
    key, sustain = reference["key_release"], reference["sustain"]
    result = {"onset": asdict(score_notes(key.events, predicted.events, with_offsets=False)),
              "key_release": asdict(score_notes(key.events, predicted.events, with_offsets=True)),
              "sustain": asdict(score_notes(sustain.events, predicted.events, with_offsets=True)),
              "velocity": asdict(velocity_mae(key.events, predicted.events)),
              "censored": {"reference_key_release": key.censored_count,
                           "reference_sustain": sustain.censored_count, "predicted": predicted.censored_count}}
    check_stop(stop)
    return result
