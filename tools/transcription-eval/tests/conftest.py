from pathlib import Path

import mido
import pytest


@pytest.fixture
def midi_file(tmp_path):
    def write(events, *, tracks=None, ticks_per_beat=1000, midi_type=1):
        midi = mido.MidiFile(type=midi_type, ticks_per_beat=ticks_per_beat)
        for track_events in tracks if tracks is not None else [events]:
            track = mido.MidiTrack()
            for kind, fields in track_events:
                cls = mido.MetaMessage if kind in {"set_tempo", "end_of_track"} else mido.Message
                track.append(cls(kind, **fields))
            midi.tracks.append(track)
        path = Path(tmp_path) / "reference.mid"
        midi.save(path)
        return path
    return write
