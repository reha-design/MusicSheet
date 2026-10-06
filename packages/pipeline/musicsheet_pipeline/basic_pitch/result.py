"""Strict, bounded wire validation without importing the inference runtime."""
from io import BytesIO
import json
import math
from pathlib import Path
import stat
import threading

import mido
from musicsheet_common.schemas.transcription_result import TranscriptionResult
from ..contracts import InvalidArtifact
from .io import check_stop

JSON_LIMIT = 8 * 1024 * 1024
MIDI_LIMIT = 16 * 1024 * 1024
PROVENANCE = {"id": "spotify-basic-pitch", "package_version": "0.4.0",
    "source_commit": "049dc8a01a170c2370d7b246ec1c2067e060c3bf", "model_asset": "nmp.onnx",
    "supports_pedal": False, "confidence_semantics": "uncalibrated_note_activation_mean"}


def _read(path, root, limit, stop):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.resolve().parent != root or not 0 < info.st_size <= limit:
        raise ValueError
    data = bytearray()
    with path.open("rb") as stream:
        while len(data) <= limit:
            check_stop(stop)
            block = stream.read(min(65536, limit + 1 - len(data)))
            if not block:
                break
            data.extend(block)
    if not 0 < len(data) <= limit:
        raise ValueError
    return bytes(data)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(value):
    raise ValueError


def _json(data, stop):
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError
    provider = value.get("provider")
    if type(provider) is not dict or any(type(provider.get(key)) is not type(expected)
            or provider[key] != expected for key, expected in PROVENANCE.items()):
        raise ValueError
    notes = value.get("note_events")
    if type(notes) is not list or type(value.get("pedal_events")) is not list or value["pedal_events"]:
        raise ValueError
    seen = set()
    for note in notes:
        check_stop(stop)
        if type(note) is not dict or type(note.get("note_id")) is not str or not note["note_id"] or note["note_id"] in seen:
            raise ValueError
        seen.add(note["note_id"])
        if type(note.get("pitch")) is not int:
            raise ValueError
        for field in ("onset_sec", "offset_sec", "amt_confidence", "activation", "velocity_prediction"):
            number = note.get(field)
            if number is None and field in {"activation", "velocity_prediction"}:
                continue
            if type(number) not in (int, float) or not math.isfinite(number):
                raise ValueError
        if note.get("source_chunk") is not None and type(note["source_chunk"]) is not int:
            raise ValueError
    TranscriptionResult.model_validate(value)


def _vlq(data, position):
    value = 0
    for _ in range(4):
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 127)
        if byte < 128:
            return value, position
    raise ValueError  # Bound Mido's otherwise unbounded variable-length integer loop.


def _track(data, stop):
    position, running, eot = 0, None, False
    while position < len(data):
        check_stop(stop)
        if eot:
            raise ValueError
        _, position = _vlq(data, position)
        status = data[position]
        if status >= 128:
            position += 1
        else:
            if running is None:
                raise ValueError
            status = running
        if 0x80 <= status < 0xF0:
            running = status
            length = 1 if status & 0xF0 in {0xC0, 0xD0} else 2
            payload = data[position:position + length]
            if len(payload) != length or any(byte >= 128 for byte in payload):
                raise ValueError
            position += length
        elif status in {0xF0, 0xF7, 0xFF}:
            meta = data[position] if status == 0xFF else None
            position += 1 if status == 0xFF else 0
            length, position = _vlq(data, position)
            if position + length > len(data):
                raise ValueError
            if meta == 0x2F:
                if length:
                    raise ValueError
                eot = True
            position += length
        else:
            raise ValueError
    if not eot:
        raise ValueError


def _midi(data, stop):
    if data[:8] != b"MThd\x00\x00\x00\x06":
        raise ValueError
    count = int.from_bytes(data[10:12], "big")
    form = int.from_bytes(data[8:10], "big")
    if form not in {0, 1, 2} or not count or form == 0 and count != 1 or data[12:14] == b"\0\0":
        raise ValueError
    position = 14
    for _ in range(count):
        check_stop(stop)
        if data[position:position + 4] != b"MTrk" or position + 8 > len(data):
            raise ValueError
        size = int.from_bytes(data[position + 4:position + 8], "big")
        position += 8
        if position + size > len(data):
            raise ValueError
        _track(data[position:position + size], stop)
        position += size
    if position != len(data):
        raise ValueError
    stream = BytesIO(data)
    parsed = mido.MidiFile(file=stream, clip=False)
    if stream.tell() != len(data) or len(parsed.tracks) != count:
        raise ValueError
    for track in parsed.tracks:
        if not track or track[-1].type != "end_of_track" or sum(msg.type == "end_of_track" for msg in track) != 1:
            raise ValueError


def validate_result_files(output_dir: Path, *, stop: threading.Event) -> tuple[Path, Path]:
    try:
        if not stat.S_ISDIR(output_dir.lstat().st_mode):
            raise ValueError
        root = output_dir.resolve()
        raw, mid = output_dir / "raw_transcription.json", output_dir / "transcription.mid"
        _json(_read(raw, root, JSON_LIMIT, stop), stop)
        _midi(_read(mid, root, MIDI_LIMIT, stop), stop)
        check_stop(stop)
        return raw, mid
    except InterruptedError:
        raise
    except Exception:
        raise InvalidArtifact() from None
