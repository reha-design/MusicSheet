"""Exact binary event identity, independent of runtime metadata."""
import hashlib
import struct

from .contracts import Events


def events_hash(events: Events) -> str:
    if type(events) is not Events: raise ValueError("invalid events")
    digest = hashlib.sha256(b"W05-EVENTS-1\0")
    def number(value):
        digest.update(struct.pack("<d", 0.0 if value == 0 else float(value)))
    notes = sorted(events.notes, key=lambda n: (n.pitch, n.onset, n.offset, n.velocity is not None, n.velocity or 0.0))
    digest.update(b"N" + struct.pack("<Q", len(notes)))
    for note in notes:
        for value in (note.pitch, note.onset, note.offset): number(value)
        digest.update(b"\0" if note.velocity is None else b"\1")
        if note.velocity is not None: number(note.velocity)
    pedals = sorted(events.pedals, key=lambda p: (p.kind.encode("utf-8"), p.onset, p.offset, p.value))
    digest.update(b"P" + struct.pack("<Q", len(pedals)))
    for pedal in pedals:
        kind = pedal.kind.encode("utf-8")
        digest.update(struct.pack("<I", len(kind)) + kind)
        for value in (pedal.onset, pedal.offset, pedal.value): number(value)
    return digest.hexdigest()
