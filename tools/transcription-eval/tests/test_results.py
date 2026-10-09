import json
import threading

import pytest

from task4_support import candidate,output


@pytest.mark.parametrize('kind',['basic_pitch','piano_amt'])
def test_normalize_preserves_native_events_and_empty_predictions(tmp_path,kind):
    from musicsheet_transcription_eval.results import normalize_output
    model=candidate(tmp_path/'candidate',kind)
    path=tmp_path/'result';output(path,kind,checkpoint_sha=model.checkpoint_sha256)
    events=normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())
    assert [(n.pitch,n.onset,n.offset,n.velocity) for n in events.notes]==[(60,3.,4.,None if kind=='basic_pitch' else 80.)]
    empty=tmp_path/'empty';output(empty,kind,checkpoint_sha=model.checkpoint_sha256,notes=[])
    assert not normalize_output(model,empty,input_sha256='a'*64,stop=threading.Event()).notes


@pytest.mark.parametrize('kind',['basic_pitch','piano_amt'])
def test_output_event_cap_before_existing_validator(tmp_path,kind,monkeypatch):
    from musicsheet_transcription_eval import results,reference
    from musicsheet_transcription_eval.contracts import EvaluationLimitError
    model=candidate(tmp_path/'candidate',kind);path=tmp_path/'result'
    output(path,kind,checkpoint_sha=model.checkpoint_sha256)
    monkeypatch.setattr(reference,'MIDI_EVENT_LIMIT',1)
    def forbidden(*args,**kwargs):pytest.fail('downstream parser called before raw cap')
    monkeypatch.setattr(results,'validate_result_files',forbidden)
    monkeypatch.setattr(reference.mido,'MidiFile',forbidden)
    with pytest.raises(EvaluationLimitError):results.normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())


@pytest.mark.parametrize('kind',['basic_pitch','piano_amt'])
@pytest.mark.parametrize('case',['bool','nan','padding','zero_interval','extra','source','duplicate_key','truncated_midi'])
def test_invalid_wire_and_full_midi_refused(tmp_path,kind,case):
    from musicsheet_transcription_eval.results import normalize_output
    model=candidate(tmp_path/'candidate',kind);path=tmp_path/'result'
    wire=output(path,kind,checkpoint_sha=model.checkpoint_sha256)
    note=wire['note_events' if kind=='basic_pitch' else 'notes'][0]
    onset='onset_sec' if kind=='basic_pitch' else 'onset';offset='offset_sec' if kind=='basic_pitch' else 'offset'
    if case=='bool':note['pitch']=True
    elif case=='nan':note[onset]=float('nan')
    elif case=='padding':note[offset]=31.001
    elif case=='zero_interval':note[offset]=note[onset]
    elif case=='extra':wire['unrecognized']=1
    elif case=='source':
        (wire['provider'] if kind=='basic_pitch' else wire)['source_commit']='0'*40
    (path/'raw_transcription.json').write_text(json.dumps(wire))
    if case=='duplicate_key':(path/'raw_transcription.json').write_text('{"schema_version":1,"schema_version":1}')
    if case=='truncated_midi':
        midi=path/'transcription.mid';midi.write_bytes(midi.read_bytes()[:-1])
    with pytest.raises(ValueError):normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())


@pytest.mark.parametrize('field,value',[('input_sha256','f'*64),('checkpoint_sha256','f'*64),
    ('device','cuda'),('dtype','float64'),('duration_sec',True),('duration_sec',29),('options',{}),('runtime',{})])
def test_piano_candidate_receipt_mismatch(tmp_path,field,value):
    from musicsheet_transcription_eval.results import normalize_output
    model=candidate(tmp_path/'candidate','piano_amt');path=tmp_path/'result'
    wire=output(path,'piano_amt',checkpoint_sha=model.checkpoint_sha256);wire[field]=value
    (path/'raw_transcription.json').write_text(json.dumps(wire))
    with pytest.raises(ValueError):normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())


def test_piano_json_midi_semantic_mismatch_rejected(tmp_path):
    from musicsheet_transcription_eval.results import normalize_output
    model=candidate(tmp_path/'candidate','piano_amt');path=tmp_path/'result'
    wire=output(path,'piano_amt',checkpoint_sha=model.checkpoint_sha256);wire['notes'][0]['velocity']=81
    (path/'raw_transcription.json').write_text(json.dumps(wire))
    with pytest.raises(ValueError):normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())


@pytest.mark.parametrize('kind',['basic_pitch','piano_amt'])
def test_padding31_is_valid_and_reference_score_censors(tmp_path,kind):
    from musicsheet_transcription_eval.results import normalize_output,score_output
    from task4_support import entry
    item=entry(tmp_path/'input');model=candidate(tmp_path/'candidate',kind);path=tmp_path/'result'
    output(path,kind,checkpoint_sha=model.checkpoint_sha256,notes=[dict(pitch=60,onset=3.,offset=31.,velocity=80)])
    events=normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())
    score=score_output(item,events,stop=threading.Event())
    assert score['censored']['predicted']==1 and score['onset']['tp']==1
    assert score['sustain']['tp']==0


def test_piano_midi_timebase_and_tempo_must_match_native_contract(tmp_path):
    import mido
    from musicsheet_transcription_eval.results import normalize_output
    model=candidate(tmp_path/'candidate','piano_amt');path=tmp_path/'result'
    output(path,'piano_amt',checkpoint_sha=model.checkpoint_sha256)
    midi=mido.MidiFile(path/'transcription.mid');midi.tracks[0][0].tempo=500001;midi.save(path/'transcription.mid')
    with pytest.raises(ValueError):normalize_output(model,path,input_sha256='a'*64,stop=threading.Event())


@pytest.mark.parametrize('case',['pair_bool','unsorted','population','note_extra'])
def test_success_record_rejects_invalid_full_metric_contract(tmp_path,case):
    from musicsheet_transcription_eval.contracts import Events,Note,RunRecord
    from musicsheet_transcription_eval.results import score_output
    from task4_support import entry,metric
    item=entry(tmp_path/'input')
    value=score_output(item,Events((Note(60,3.,4.,None),Note(64,5.,6.,None)),()),stop=threading.Event())
    if case=='pair_bool':value['velocity']['pairs']=[[True,0]]
    elif case=='unsorted':value['velocity']['prediction_sorted']=list(reversed(value['velocity']['prediction_sorted']))
    elif case=='population':value['onset']=metric(1,0,0)
    elif case=='note_extra':value['velocity']['reference_sorted'][0]['extra']='secret-sentinel'
    with pytest.raises(ValueError):RunRecord('r0-a',item.recording_id,'basic_pitch',0,None,'success',None,None,
        .1,'a'*64,tmp_path,True,0,(),{},value)
