import pytest

from musicsheet_transcription_eval.contracts import EvaluationLimitError
from musicsheet_transcription_eval.reference import parse_reference


def test_tempo_map_and_velocity_zero_note_off(midi_file):
    path = midi_file([
        ("note_on", dict(note=60, velocity=80, time=0)),
        ("set_tempo", dict(tempo=1000000, time=1000)),
        ("note_on", dict(note=60, velocity=0, time=1000)),
    ])
    ref = parse_reference(path)
    assert (ref.key_release.notes[0].onset, ref.key_release.notes[0].offset) == (0.0, 1.5)


def test_key_release_and_sustain_differ(midi_file):
    path = midi_file([
        ("note_on", dict(note=60, velocity=80, time=200)),
        ("control_change", dict(control=64, value=127, time=200)),
        ("note_off", dict(note=60, time=600)),
        ("note_on", dict(note=60, velocity=90, time=600)),
        ("note_off", dict(note=60, time=100)),
        ("control_change", dict(control=64, value=0, time=300)),
    ])
    ref = parse_reference(path)
    assert [note.offset for note in ref.key_release.notes] == [0.5, 0.85]
    assert [note.offset for note in ref.sustain.notes] == [0.8, 1.0]
    assert (ref.sustain.pedals[0].onset, ref.sustain.pedals[0].offset) == (0.2, 1.0)


def test_simultaneous_tempo_restrike_pedal(midi_file):
    path = midi_file([], tracks=[[
        ("note_on", dict(note=60, velocity=80, time=0)),
        ("control_change", dict(control=64, value=64, time=100)),
        ("note_off", dict(note=60, time=900)),
        ("set_tempo", dict(tempo=1000000, time=0)),
        ("note_on", dict(note=60, velocity=90, time=0)),
        ("note_off", dict(note=60, time=1000)),
    ], [
        ("control_change", dict(control=64, value=63, time=1000)),
    ]])
    ref = parse_reference(path)
    assert [(n.onset, n.offset) for n in ref.sustain.notes] == [(0.0, 0.5), (0.5, 1.5)]
    assert ref.sustain.pedals[0].offset == 0.5


def test_pedal_is_channel_specific_and_66_67_do_not_extend(midi_file):
    path = midi_file([
        ("control_change", dict(channel=1, control=64, value=127, time=0)),
        ("control_change", dict(channel=0, control=66, value=127, time=0)),
        ("control_change", dict(channel=0, control=67, value=127, time=0)),
        ("note_on", dict(channel=0, note=60, velocity=80, time=100)),
        ("note_off", dict(channel=0, note=60, time=100)),
        ("control_change", dict(channel=1, control=64, value=0, time=800)),
    ])
    ref = parse_reference(path)
    assert ref.sustain.notes == ref.key_release.notes


@pytest.mark.parametrize("events", [
    [("note_on", dict(note=60, velocity=80, time=0))],
    [("control_change", dict(control=64, value=127, time=0))],
    [("note_off", dict(note=60, time=0))],
    [("note_on", dict(note=60, velocity=80, time=0)), ("note_on", dict(note=60, velocity=90, time=1))],
    [("note_on", dict(note=60, velocity=80, time=0)), ("note_off", dict(note=60, time=0))],
])
def test_malformed_event_state_is_rejected(midi_file, events):
    with pytest.raises(ValueError, match="reference"):
        parse_reference(midi_file(events))


@pytest.mark.parametrize("ticks,midi_type", [(-24 * 256 + 40, 1), (1000, 2), (0, 1)])
def test_smpte_type2_and_zero_resolution_rejected(midi_file, ticks, midi_type):
    with pytest.raises(ValueError, match="reference"):
        parse_reference(midi_file([], ticks_per_beat=ticks, midi_type=midi_type))


@pytest.mark.parametrize("damage", ["truncated", "trailing", "missing_eot", "extra_after_eot"])
def test_malformed_file_structure_rejected(midi_file, damage):
    path = midi_file([])
    data = path.read_bytes()
    if damage == "truncated": data = data[:-1]
    elif damage == "trailing": data += b"junk"
    elif damage == "missing_eot": data = data[:18] + (0).to_bytes(4, "big")
    else: data = data[:18] + (8).to_bytes(4, "big") + b"\x00\xff\x2f\x00\x00\xff\x2f\x00"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="reference"):
        parse_reference(path)


def test_symlink_and_non_file_rejected(midi_file, tmp_path, monkeypatch):
    path = midi_file([])
    monkeypatch.setattr(type(path), "is_symlink", lambda self: True)
    with pytest.raises(ValueError, match="reference"):
        parse_reference(path)
    monkeypatch.undo()
    with pytest.raises(ValueError, match="reference"):
        parse_reference(tmp_path)


def test_empty_reference_valid(midi_file):
    result = parse_reference(midi_file([]))
    assert result.key_release.notes == result.sustain.notes == ()


@pytest.mark.parametrize("payload", [
    b"\x00\xff\x51\x04\x07\xa1\x20\x7f",  # oversized tempo
    b"\x00\xff\x80\x00",  # meta type must be a 7-bit byte
    b"\x00\xff\x58\x05\x04\x02\x18\x08\x7f",  # oversized time signature
    b"\x00\xff\x00\x03\x00\x01\x02",  # oversized sequence number
    b"\x00\xff\x20\x02\x00\x01",  # oversized channel prefix
    b"\x00\xff\x21\x02\x00\x01",  # oversized port
    b"\x00\xff\x54\x06\x00\x00\x00\x00\x00\x00",  # oversized SMPTE offset
    b"\x00\xff\x59\x03\x00\x00\x00",  # oversized key signature
])
def test_fixed_meta_payload_and_type_rejected(midi_file, payload):
    path = midi_file([])
    original = path.read_bytes()
    track = payload + b"\x00\xff\x2f\x00"
    path.write_bytes(original[:18] + len(track).to_bytes(4, "big") + track)
    with pytest.raises(ValueError, match="reference"):
        parse_reference(path)


def test_reference_event_cap_before_mido(midi_file, monkeypatch):
    from musicsheet_transcription_eval import reference
    path = midi_file([], tracks=[[
        ("program_change", dict(program=0, time=0)),
        ("program_change", dict(program=1, time=0)),
    ], [
        ("program_change", dict(program=2, time=0)),
        ("program_change", dict(program=3, time=0)),
    ]])  # six events, including the two EOT messages
    monkeypatch.setattr(reference, "MIDI_EVENT_LIMIT", 5, raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("mido called before raw event cap")
    monkeypatch.setattr(reference.mido, "MidiFile", forbidden)
    with pytest.raises(EvaluationLimitError, match="limit"):
        parse_reference(path)


def test_reference_event_cap_boundary_includes_eot(midi_file, monkeypatch):
    from musicsheet_transcription_eval import reference
    path = midi_file([("program_change", dict(program=0, time=0))])
    monkeypatch.setattr(reference, "MIDI_EVENT_LIMIT", 2, raising=False)
    assert parse_reference(path).key_release.notes == ()
