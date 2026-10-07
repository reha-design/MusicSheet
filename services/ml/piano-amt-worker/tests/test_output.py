import copy
import json

import mido
import pytest


def write(path,prediction):
    from musicsheet_piano_amt_worker.output import write_outputs
    return write_outputs(path,prediction,input_sha256="a"*64,checkpoint_sha256="b"*64,device="cpu")


def test_valid_wire_and_full_midi_roundtrip(tmp_path,prediction):
    from musicsheet_piano_amt_worker.provenance import SOURCE_COMMIT
    path=tmp_path/"result"
    write(path,prediction)
    wire=json.loads((path/"raw_transcription.json").read_text())
    assert wire["schema_version"] == 1 and wire["source_commit"] == SOURCE_COMMIT
    assert wire["dtype"] == "float32" and wire["notes"] == prediction["notes"] and wire["pedals"] == prediction["pedals"]
    assert "confidence" not in json.dumps(wire)
    midi=mido.MidiFile(path/"transcription.mid")
    events=list(midi)
    assert [(e.note,e.velocity) for e in events if e.type=="note_on"] == [(60,80)]
    assert [(e.control,e.value) for e in events if e.type=="control_change"] == [(64,127),(64,0)]
    assert any(e.type=="note_off" for e in events) and events[-1].type=="end_of_track"


def test_empty_output_is_valid(tmp_path,prediction):
    prediction.update(notes=[],pedals=[])
    write(tmp_path/"result",prediction)
    assert json.loads((tmp_path/"result"/"raw_transcription.json").read_text())["notes"] == []


def test_midi_quantization_keeps_short_note_on_before_off_and_restrike_order(tmp_path,prediction):
    prediction.update(notes=[dict(pitch=60,onset=.1001,offset=.1016,velocity=80),
        dict(pitch=60,onset=.1016,offset=.2,velocity=70)],pedals=[])
    write(tmp_path/"result",prediction)
    events=[e.type for e in mido.MidiFile(tmp_path/"result"/"transcription.mid") if e.type in {"note_on","note_off"}]
    assert events == ["note_on","note_off","note_on","note_off"]


@pytest.mark.parametrize("field,value", [("pitch",True),("pitch",60.0),("pitch",20),("pitch",109),
    ("onset",True),("onset",float("nan")),("onset",-.1),("offset",float("inf")),("offset",.1),
    ("offset",2.001),("velocity",False),("velocity",-1),("velocity",0),("velocity",128)])
def test_invalid_note_refuses_output(tmp_path,prediction,field,value):
    prediction["notes"][0][field]=value
    with pytest.raises(ValueError):
        write(tmp_path/"result",prediction)
    assert not (tmp_path/"result").exists()


@pytest.mark.parametrize("field,value", [("kind","soft"),("onset",False),("offset",.2),("value",True),("value",0),("value",63),("value",128)])
def test_invalid_pedal_refuses_output(tmp_path,prediction,field,value):
    prediction["pedals"][0][field]=value
    with pytest.raises(ValueError):
        write(tmp_path/"result",prediction)
    assert not (tmp_path/"result").exists()


def test_existing_output_and_partial_write_preserve_user_files(tmp_path,prediction,monkeypatch):
    from musicsheet_piano_amt_worker import output
    directory=tmp_path/"existing"
    directory.mkdir()
    marker=directory/"keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError):
        write(directory,prediction)
    assert marker.read_text()=="keep"
    def fail(*args,**kwargs):
        raise OSError("secret-sentinel")
    monkeypatch.setattr(output,"_write_file",fail)
    with pytest.raises(ValueError) as error:
        write(tmp_path/"partial",prediction)
    assert "secret-sentinel" not in str(error.value) and not (tmp_path/"partial").exists()


@pytest.mark.parametrize("limit", ["JSON_LIMIT", "MIDI_LIMIT", "EVENT_LIMIT"])
def test_limits_refuse_publication(tmp_path,prediction,monkeypatch,limit):
    from musicsheet_piano_amt_worker import output
    monkeypatch.setattr(output,limit,1)
    with pytest.raises(ValueError): write(tmp_path/"result",prediction)
    assert not (tmp_path/"result").exists()


@pytest.mark.parametrize("group", ["notes", "pedals"])
def test_same_tick_interval_refused_without_adjusting_prediction(tmp_path,prediction,group):
    from musicsheet_piano_amt_worker.output import OutputValidationError
    prediction[group][0].update(onset=.1001,offset=.1002)
    original=copy.deepcopy(prediction)
    with pytest.raises(OutputValidationError): write(tmp_path/"result",prediction)
    assert prediction == original and not (tmp_path/"result").exists()


@pytest.mark.parametrize("group", ["notes", "pedals"])
def test_overlapping_same_midi_state_is_refused_without_dropping_events(tmp_path,prediction,group):
    from musicsheet_piano_amt_worker.output import OutputValidationError
    prediction[group].append(dict(prediction[group][0],onset=.3,offset=.8))
    original=copy.deepcopy(prediction)
    with pytest.raises(OutputValidationError): write(tmp_path/"result",prediction)
    assert prediction == original and not (tmp_path/"result").exists()


@pytest.mark.parametrize("velocity,value", [(1,64),(127,127)])
def test_one_tick_and_sounding_boundaries_and_polyphony_are_preserved(tmp_path,prediction,velocity,value):
    prediction["notes"]=[dict(pitch=pitch,onset=1/768,offset=2/768,velocity=velocity) for pitch in (60,64)]
    prediction["pedals"]=[dict(kind="sustain",onset=3/768,offset=4/768,value=value)]
    original=copy.deepcopy(prediction)
    write(tmp_path/"result",prediction)
    midi=mido.MidiFile(tmp_path/"result"/"transcription.mid")
    events=list(midi)
    assert [m.velocity for m in events if m.type=="note_on"] == [velocity,velocity]
    assert [m.value for m in events if m.type=="control_change"] == [value,0]
    assert prediction == original
