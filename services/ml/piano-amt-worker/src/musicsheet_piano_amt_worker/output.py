"""Strict evaluation wire and bounded MIDI, published only into a new directory."""

from collections import Counter
from io import BytesIO
import json
import math
from pathlib import Path
import uuid

from .provenance import (CHECKPOINT_NAME, OPTIONS, PACKAGE_VERSION, SOURCE_COMMIT,
                         SOURCE_URL, safe_path, valid_sha256)

JSON_LIMIT = 8 * 1024 * 1024
MIDI_LIMIT = 16 * 1024 * 1024
EVENT_LIMIT = 100000


class OutputValidationError(ValueError):
    """An invalid native prediction, distinguished from an inference exception."""


def _number(value) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def validate_prediction(prediction: dict) -> None:
    if type(prediction) is not dict or set(prediction) != {"duration_sec", "notes", "pedals", "runtime"}:
        raise OutputValidationError("invalid prediction fields")
    duration = prediction["duration_sec"]
    if not _number(duration) or not 0 < duration <= 30:
        raise OutputValidationError("invalid duration")
    notes, pedals = prediction["notes"], prediction["pedals"]
    if type(notes) is not list or type(pedals) is not list or 2 * (len(notes) + len(pedals)) + 2 > EVENT_LIMIT:
        raise OutputValidationError("invalid event lists or limit")
    for event, keys in [*((n, {"pitch", "onset", "offset", "velocity"}) for n in notes),
                        *((p, {"kind", "onset", "offset", "value"}) for p in pedals)]:
        if type(event) is not dict or set(event) != keys:
            raise OutputValidationError("invalid event fields")
        if (not _number(event["onset"]) or not _number(event["offset"])
            or not 0 <= event["onset"] < event["offset"] <= duration + 1):
            raise OutputValidationError("invalid event interval")
        if int(event["offset"] * 768) <= int(event["onset"] * 768):
            raise OutputValidationError("unrepresentable MIDI interval")
    for note in notes:
        if type(note["pitch"]) is not int or not 21 <= note["pitch"] <= 108 or (
            type(note["velocity"]) is not int or not 1 <= note["velocity"] <= 127):
            raise OutputValidationError("invalid note")
    for pedal in pedals:
        if pedal["kind"] != "sustain" or type(pedal["value"]) is not int or not 64 <= pedal["value"] <= 127:
            raise OutputValidationError("invalid pedal")
    runtime = prediction["runtime"]
    if type(runtime) is not dict or set(runtime) != {"torch_num_threads", "torch_num_interop_threads"} or any(
        type(value) is not int or value != 1 for value in runtime.values()
    ):
        raise OutputValidationError("invalid CPU runtime")


def _validate_midi(data: bytes, prediction: dict) -> None:
    """Reconstruct sounding intervals from the complete Mido tick stream."""
    import mido
    notes, pedals = Counter(), Counter()
    active_notes, active_pedals = {}, {}
    tick = 0
    midi = mido.MidiFile(file=BytesIO(data))
    for message in midi.tracks[0]:
        tick += message.time
        if message.type == "note_on" and message.velocity > 0:
            key = (message.channel, message.note)
            if key in active_notes:
                raise OutputValidationError("overlapping MIDI notes")
            active_notes[key] = (tick, message.velocity)
        elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            key = (message.channel, message.note)
            if key not in active_notes:
                raise OutputValidationError("unmatched MIDI note release")
            start, velocity = active_notes.pop(key)
            if tick <= start:
                raise OutputValidationError("nonpositive MIDI note interval")
            notes[(message.note, start, tick, velocity)] += 1
        elif message.type == "control_change" and message.control == 64:
            if message.value >= 64:
                if message.channel in active_pedals:
                    raise OutputValidationError("overlapping MIDI sustain")
                active_pedals[message.channel] = (tick, message.value)
            else:
                if message.channel not in active_pedals:
                    raise OutputValidationError("unmatched MIDI sustain release")
                start, value = active_pedals.pop(message.channel)
                if tick <= start:
                    raise OutputValidationError("nonpositive MIDI sustain interval")
                pedals[("sustain", start, tick, value)] += 1
    expected_notes = Counter((n["pitch"], int(n["onset"] * 768), int(n["offset"] * 768), n["velocity"])
                             for n in prediction["notes"])
    expected_pedals = Counter((p["kind"], int(p["onset"] * 768), int(p["offset"] * 768), p["value"])
                              for p in prediction["pedals"])
    if active_notes or active_pedals or notes != expected_notes or pedals != expected_pedals:
        raise OutputValidationError("MIDI prediction mismatch")


def _midi_bytes(prediction: dict) -> bytes:
    import mido
    midi = mido.MidiFile(type=0, ticks_per_beat=384)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    events = []
    for note in prediction["notes"]:
        events.append((note["onset"], 3, mido.Message("note_on", note=note["pitch"], velocity=note["velocity"])))
        events.append((note["offset"], 0, mido.Message("note_off", note=note["pitch"], velocity=0)))
    for pedal in prediction["pedals"]:
        events.append((pedal["onset"], 2, mido.Message("control_change", control=64, value=pedal["value"])))
        events.append((pedal["offset"], 1, mido.Message("control_change", control=64, value=0)))
    events.sort(key=lambda item: (item[0], item[1]))
    previous = 0
    for time_sec, _, message in events:
        tick = int(time_sec * 768)
        track.append(message.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    buffer = BytesIO()
    midi.save(file=buffer)
    data = buffer.getvalue()
    if len(data) > MIDI_LIMIT:
        raise ValueError("MIDI size limit")
    _validate_midi(data, prediction)
    return data


def _write_file(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)


def write_outputs(output_dir: Path, prediction: dict, *, input_sha256: str,
                  checkpoint_sha256: str, device: str) -> None:
    validate_prediction(prediction)
    if device != "cpu":
        raise ValueError("CPU device required")
    wire = {"schema_version": 1, "source_commit": SOURCE_COMMIT, "source_url": SOURCE_URL,
        "package_version": PACKAGE_VERSION, "model": "Note_pedal", "checkpoint_name": CHECKPOINT_NAME,
        "checkpoint_sha256": valid_sha256(checkpoint_sha256), "input_sha256": valid_sha256(input_sha256),
        "device": device, "dtype": "float32", "options": OPTIONS, **prediction}
    data = json.dumps(wire, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > JSON_LIMIT:
        raise ValueError("JSON size limit")
    midi = _midi_bytes(prediction)
    directory = safe_path(output_dir)
    owned = []
    created = False
    try:
        directory.mkdir()
        created = True
        for name, payload in [("raw_transcription.json", data), ("transcription.mid", midi)]:
            target = directory / name
            part = directory / (name + "." + uuid.uuid4().hex + ".part")
            owned.append(part)
            _write_file(part, payload)
            part.rename(target)
            owned.append(target)
    except OSError:
        if created:
            for path in reversed(owned):
                path.unlink(missing_ok=True)
            directory.rmdir()
        raise ValueError("output publication failed") from None
