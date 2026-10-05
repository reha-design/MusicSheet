"""Strict full-recording MIDI parsing before crop or metric conversion."""

from bisect import bisect_right
from collections import defaultdict
from fractions import Fraction
from io import BytesIO
from pathlib import Path
import stat

import mido

from .contracts import EvaluationLimitError, Events, Note, Pedal, Reference

MIDI_LIMIT = 16 * 1024 * 1024
MIDI_EVENT_LIMIT = 100_000
FIXED_META_LENGTHS = {0x00: 2, 0x20: 1, 0x21: 1, 0x2F: 0, 0x51: 3, 0x54: 5, 0x58: 4, 0x59: 2}


def _vlq(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 127)
        if byte < 128:
            return value, position
    raise ValueError("overlong MIDI integer")


def _track(data: bytes, *, event_budget: int) -> int:
    position, running, ended, count = 0, None, False, 0
    while position < len(data):
        if ended:
            raise ValueError("events after end_of_track")
        if count >= event_budget:
            raise EvaluationLimitError("midi_event_limit")
        count += 1
        _, position = _vlq(data, position)
        status = data[position]
        if status >= 128:
            position += 1
        elif running is None:
            raise ValueError("invalid running status")
        else:
            status = running
        if 0x80 <= status < 0xF0:
            running = status
            length = 1 if status & 0xF0 in {0xC0, 0xD0} else 2
            payload = data[position:position + length]
            if len(payload) != length or any(byte >= 128 for byte in payload):
                raise ValueError("invalid MIDI data")
            position += length
        elif status in {0xF0, 0xF7, 0xFF}:
            meta = data[position] if status == 0xFF else None
            position += status == 0xFF
            length, position = _vlq(data, position)
            if position + length > len(data):
                raise ValueError("truncated MIDI data")
            if meta is not None:
                if meta > 127 or meta in FIXED_META_LENGTHS and length != FIXED_META_LENGTHS[meta]:
                    raise ValueError("invalid MIDI meta event")
            if meta == 0x2F:
                if length:
                    raise ValueError("invalid end_of_track")
                ended = True
            position += length
        else:
            raise ValueError("invalid MIDI status")
    if not ended:
        raise ValueError("missing end_of_track")
    return count


def _read_bytes(path: Path) -> bytes:
    if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
        raise ValueError("linked MIDI path")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 14 <= info.st_size <= MIDI_LIMIT:
        raise ValueError("invalid MIDI file")
    with path.open("rb") as stream:
        data = stream.read(MIDI_LIMIT + 1)
    if len(data) != info.st_size or data[:8] != b"MThd\x00\x00\x00\x06":
        raise ValueError("invalid MIDI header")
    form, count, resolution = (int.from_bytes(data[i:i + 2], "big") for i in (8, 10, 12))
    if form not in {0, 1} or not count or form == 0 and count != 1 or not 0 < resolution < 0x8000:
        raise ValueError("unsupported MIDI format")
    position, event_count = 14, 0
    for _ in range(count):
        if data[position:position + 4] != b"MTrk" or position + 8 > len(data):
            raise ValueError("invalid MIDI chunk")
        length = int.from_bytes(data[position + 4:position + 8], "big")
        position += 8
        if position + length > len(data):
            raise ValueError("truncated MIDI chunk")
        event_count += _track(data[position:position + length], event_budget=MIDI_EVENT_LIMIT - event_count)
        position += length
    if position != len(data):
        raise ValueError("trailing MIDI data")
    return data


def read_validated_midi_bytes(path: Path) -> bytes:
    """Gate reference AND candidate output MIDI before any Mido allocation."""
    try:
        return _read_bytes(path)
    except EvaluationLimitError:
        raise
    except (OSError, EOFError, IndexError, KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("malformed MIDI file") from None


def parse_reference(path: Path) -> Reference:
    try:
        midi = mido.MidiFile(file=BytesIO(read_validated_midi_bytes(path)), clip=False)
        merged = []
        for track_id, track in enumerate(midi.tracks):
            tick = 0
            for event_id, message in enumerate(track):
                tick += message.time
                merged.append((tick, track_id, event_id, message))
        merged.sort(key=lambda item: item[:3])
        tempo, previous_tick, seconds = 500000, 0, Fraction(0)
        active, pressed, releases, pedal_ends, pedals = {}, {}, [], {}, []
        onsets = defaultdict(list)
        serial = 0
        for tick, _, _, message in merged:
            seconds += Fraction((tick - previous_tick) * tempo, midi.ticks_per_beat * 1000000)
            previous_tick = tick
            now = float(seconds)
            if message.type == "set_tempo":
                if message.tempo <= 0:
                    raise ValueError("invalid tempo")
                tempo = message.tempo
            elif message.type == "note_on" and message.velocity > 0:
                key = (message.channel, message.note)
                if key in active:
                    raise ValueError("overlapping note_on")
                active[key] = (now, message.velocity)
                onsets[key].append(now)
            elif message.type == "note_off" or message.type == "note_on" and message.velocity == 0:
                key = (message.channel, message.note)
                if key not in active:
                    raise ValueError("unmatched note_off")
                onset, velocity = active.pop(key)
                note = Note(message.note, onset, now, float(velocity))
                pedal_id = pressed[message.channel][0] if message.channel in pressed else None
                releases.append((key, note, pedal_id))
            elif message.type == "control_change" and message.control == 64:
                channel = message.channel
                if message.value >= 64 and channel not in pressed:
                    pressed[channel] = (serial, now, message.value)
                    serial += 1
                elif message.value < 64 and channel in pressed:
                    pedal_id, onset, value = pressed.pop(channel)
                    pedals.append(Pedal("sustain", onset, now, value))
                    pedal_ends[pedal_id] = now
        if active or pressed:
            raise ValueError("open note/pedal at EOF")
        key_notes, sustain_notes = [], []
        for key, note, pedal_id in releases:
            offset = note.offset
            if pedal_id is not None:
                offset = max(offset, pedal_ends[pedal_id])
                index = bisect_right(onsets[key], note.onset)
                if index < len(onsets[key]):
                    offset = min(offset, onsets[key][index])
            key_notes.append(note)
            sustain_notes.append(Note(note.pitch, note.onset, offset, note.velocity))
        ordering = lambda note: (note.onset, note.pitch, note.offset, note.velocity)
        pedal_tuple = tuple(sorted(pedals, key=lambda p: (p.onset, p.offset, p.value)))
        return Reference(Events(tuple(sorted(key_notes, key=ordering)), pedal_tuple), Events(tuple(sorted(sustain_notes, key=ordering)), pedal_tuple))
    except EvaluationLimitError:
        raise
    except (OSError, EOFError, IndexError, KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("malformed reference MIDI") from None
