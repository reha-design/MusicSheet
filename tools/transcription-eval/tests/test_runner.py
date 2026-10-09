import asyncio
from dataclasses import asdict,replace
import json
from pathlib import Path
import sys
import threading
import time

import pytest

from task4_support import candidate,entry,metric,output


def slot_fixture(tmp_path,monkeypatch,mode='success'):
    from musicsheet_transcription_eval import runner
    model=candidate(tmp_path/'candidate');item=entry(tmp_path/'inputs');root=tmp_path/'run';root.mkdir()
    seed=tmp_path/'seed';output(seed)
    def argv(candidate,audio,destination):
        return (sys.executable,'-I',str(Path(__file__).with_name('fake_worker.py')),
                '--mode',mode,'--seed',str(seed),'--output',str(destination))
    monkeypatch.setattr(runner,'worker_argv',argv)
    async def metadata(*args,**kwargs):
        return {**{key:model.runtime[key] for key in ('python_version','package_version','source_commit','backend_version')},
                'asset':str(model.checkpoint)}
    monkeypatch.setattr(runner,'probe_metadata',metadata)
    return runner,model,item,root


@pytest.mark.parametrize('mode,status,attribution',[('success','success',None),('exit3','model_error','unresolved'),
    ('exit4','output_invalid','unresolved'),('invalid','output_invalid','unresolved'),('hang','timeout','unresolved')])
def test_real_owned_worker_status_and_monotonic_elapsed(tmp_path,monkeypatch,mode,status,attribution):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch,mode)
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,
        cancellation=asyncio.Event(),timeout_sec=.25 if mode=='hang' else 5))
    assert record.status==status and record.attribution==attribution and record.started
    assert record.elapsed_sec>=0 and (root/'starts/r0-000-basic_pitch.json').exists()
    assert 'secret-sentinel' not in json.dumps(asdict(record),default=str)
    if status=='success':assert record.metrics['onset']['tp']==1 and record.events_sha256 and len(record.files)>=3
    else:assert record.events_sha256 is None and record.metrics is None


def test_cancel_after_valid_output_not_success(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    async def run():
        cancellation=asyncio.Event();loop=asyncio.get_running_loop();original=runner.normalize_output
        def cancel(*args,**kwargs):
            events=original(*args,**kwargs);loop.call_soon_threadsafe(cancellation.set);return events
        monkeypatch.setattr(runner,'normalize_output',cancel)
        return await runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=cancellation)
    record=asyncio.run(run())
    assert record.status=='cancelled' and record.events_sha256 is None and record.metrics is None


def test_runner_cleanup_failure_not_model_error(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    from musicsheet_pipeline.providers import PermanentProviderError
    async def cleanup_failure(*args,**kwargs):raise PermanentProviderError()
    monkeypatch.setattr(runner,'run_owned_process',cleanup_failure)
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.attribution=='infrastructure' and record.error_code=='runner_failure'


def test_owned_descendant_is_stopped_before_success(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch,'descendant')
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.status=='success'
    pid=int((root/'slots/r0-000-basic_pitch/child.pid').read_text())
    if sys.platform=='win32':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if handle:
            code=ctypes.c_ulong();kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))
            kernel.CloseHandle(ctypes.c_void_p(handle));assert code.value!=259
    else:
        process=Path(f'/proc/{pid}/stat')
        assert not process.exists() or process.read_text().rsplit(')',1)[1].split()[0] in {'Z','X'}


def test_setup_hash_failure_never_starts_and_existing_slot_preserved(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    item.basic_audio.write_bytes(b'tampered')
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.status=='setup_failed' and record.attribution=='infrastructure' and not record.started
    assert not (root/'starts').exists()


def test_evaluator_limit_invalidates_selection(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    from musicsheet_transcription_eval.contracts import EvaluationLimitError
    def cap(*args,**kwargs):raise EvaluationLimitError('matching_cell_limit')
    monkeypatch.setattr(runner,'score_output',cap)
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.attribution=='infrastructure' and record.error_code=='evaluation_limit' and record.metrics is None


def test_midi_byte_cap_is_infrastructure_before_validator(tmp_path,monkeypatch):
    from musicsheet_transcription_eval import reference,results
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(reference,'MIDI_LIMIT',14)
    def forbidden(*args,**kwargs):pytest.fail('downstream validator before byte cap')
    monkeypatch.setattr(results,'validate_result_files',forbidden)
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.attribution=='infrastructure' and record.error_code=='evaluation_limit'


def test_byte_cap_stops_remaining_session_slots(tmp_path,monkeypatch):
    from musicsheet_transcription_eval import reference
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    runner,model,item,root=slot_fixture(tmp_path/'actual',monkeypatch)
    monkeypatch.setattr(reference,'MIDI_LIMIT',14);original=session.run_slot
    async def limited(candidate,item,**kwargs):
        if kwargs['slot_id']=='r0-000-basic_pitch':return await runner.run_slot(model,item,**kwargs)
        return await original(candidate,item,**kwargs)
    monkeypatch.setattr(session,'run_slot',limited)
    value=json.loads(run_session(tmp_path,session,manifest,models).read_bytes())['summary']
    assert 'evaluation_limit' in value['gates'] and value['decision']['status']=='no_selection'
    assert sum(m['not_run'] for m in value['models'].values())==71


def test_exit0_missing_output_remains_unresolved_output_invalid(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch,'missing')
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.status=='output_invalid' and record.attribution=='unresolved'


def test_metric_exception_is_infrastructure_not_model_output(tmp_path,monkeypatch):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    def fail(*args,**kwargs):raise ValueError('secret-sentinel reference failure')
    monkeypatch.setattr(runner,'score_output',fail)
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.attribution=='infrastructure' and record.error_code=='runner_failure'


@pytest.mark.parametrize('field,value',[('source_commit','0'*40),('python_version',[3,13,1]),
    ('backend_version','1.99.0'),('asset','D:/changed/model.onnx')])
def test_installed_source_changed_before_slot_never_starts_inference(tmp_path,monkeypatch,field,value):
    runner,model,item,root=slot_fixture(tmp_path,monkeypatch)
    async def changed(*args,**kwargs):
        receipt=dict(python_version=[3,12,13],package_version='0.4.0',source_commit=model.source_commit,
            source_url='https://github.com/spotify/basic-pitch',asset=str(model.checkpoint),backend_version='1.23.2')
        receipt[field]=value
        return receipt
    monkeypatch.setattr(runner,'probe_metadata',changed,raising=False)
    record=asyncio.run(runner.run_slot(model,item,repeat=0,slot_id='r0-000-basic_pitch',run_root=root,cancellation=asyncio.Event()))
    assert record.status=='setup_failed' and not record.started and record.attribution=='infrastructure'
    assert not (root/'starts').exists()


def test_session_deadline_drains_active_slot_and_preserves_not_run_ledger(tmp_path,monkeypatch):
    from musicsheet_transcription_eval.report import load_verified_run
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(session,'SESSION_SECONDS',2.)
    original=session.run_slot;drained=[]
    async def waiting(*args,**kwargs):
        record=await original(*args,**kwargs)
        if record.slot_id.startswith('r0-000-'):
            try:await asyncio.sleep(30)
            finally:drained.append(True)
        return replace(record,elapsed_sec=.00001)
    monkeypatch.setattr(session,'run_slot',waiting)
    path=run_session(tmp_path,session,manifest,models)
    value,_,_,_=load_verified_run(path.parent)
    assert drained==[True] and 'budget_stop' in value['gates']
    assert value['decision']['status']=='no_selection'
    assert sum(model['not_run'] for model in value['models'].values())==71


def test_budget_preflight_uses_maximum_not_average_and_keeps_all_not_run(tmp_path,monkeypatch):
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    original=session.run_slot
    async def expensive(*args,**kwargs):
        record=await original(*args,**kwargs)
        return replace(record,elapsed_sec=250. if record.slot_id=='preflight-basic_pitch-0' else .1)
    monkeypatch.setattr(session,'run_slot',expensive)
    value=json.loads(run_session(tmp_path,session,manifest,models).read_bytes())['summary']
    assert len(calls)==4 and value['gates']==['budget_preflight_failure']
    assert all(model['not_run']==36 for model in value['models'].values())


def test_task_cancellation_drains_current_slot_and_publishes_remaining_not_run(tmp_path,monkeypatch):
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    async def run():
        arrived=asyncio.Event();drained=[];original=session.run_slot
        async def waiting(*args,**kwargs):
            record=await original(*args,**kwargs)
            if record.slot_id.startswith('r0-000-'):
                arrived.set()
                try:await asyncio.sleep(30)
                finally:drained.append(True)
            return record
        monkeypatch.setattr(session,'run_slot',waiting)
        task=asyncio.create_task(session.run_evaluation(manifest,models,manifest_path=tmp_path/'manifest.json',input_root=tmp_path,
            ffmpeg=Path(sys.executable),run_root=tmp_path/'run',cancellation=asyncio.Event()))
        await arrived.wait();task.cancel();path=await task
        assert drained==[True]
        return path
    value=json.loads(asyncio.run(run()).read_bytes())['summary']
    assert value['gates']==['cancelled'] and sum(model['not_run'] for model in value['models'].values())==71


def test_actual_preflight_repeats_original_pcm_then_crops30(tmp_path):
    import hashlib
    import shutil
    import wave
    from musicsheet_transcription_eval.session import prepare_preflight,REPO
    executable=shutil.which('ffmpeg')
    if not executable:pytest.skip('FFmpeg not installed')
    item,receipt=asyncio.run(prepare_preflight(ffmpeg=Path(executable),run_root=tmp_path,cancellation=asyncio.Event()))
    with wave.open(str(REPO/'tests/fixtures/audio/basic_pitch_smoke.wav'),'rb') as incoming:
        pcm=incoming.readframes(incoming.getnframes())
    with wave.open(str(tmp_path/'preflight-input/repeated-stereo.wav'),'rb') as incoming:
        assert incoming.getnframes()==661500 and incoming.getnchannels()==2
        stereo=incoming.readframes(incoming.getnframes())
    expected=(pcm*2)[:661500*2]
    assert b''.join(stereo[i:i+2] for i in range(0,len(stereo),4))==expected
    assert receipt['kind']=='cc0_repeat_then_crop30' and item.audio_receipt.piano_frames==480000


def session_fixture(tmp_path,monkeypatch,failures=None):
    from musicsheet_transcription_eval import session
    from musicsheet_transcription_eval.contracts import Manifest,RunRecord,Events,Note
    from musicsheet_transcription_eval.determinism import events_hash
    from musicsheet_transcription_eval.manifest import canonical_json,digest_file
    items=tuple(entry(tmp_path/f'input{i}',i) for i in range(12))
    manifest=Manifest(1,'w05-r1-selection-r2-crop',items,{'v3':'a'*64,'v2':'b'*64},{})
    models=(candidate(tmp_path/'basic'),candidate(tmp_path/'piano','piano_amt'))
    calls=[];failures=failures or {}
    async def frozen(*args,**kwargs):return {'manifest_sha256':'c'*64,'input_root_sha256':'d'*64}
    async def preflight(*args,**kwargs):return items[0],{'synthetic':True,'elapsed_sec':.1}
    monkeypatch.setattr(session,'verify_session_inputs',frozen);monkeypatch.setattr(session,'prepare_preflight',preflight)
    async def slot(model,item,*,repeat,slot_id,run_root,cancellation,diagnostic_for=None,**kwargs):
        calls.append(slot_id)
        start=run_root/'starts'/f'{slot_id}.json';start.parent.mkdir(exist_ok=True)
        start.write_bytes(canonical_json(dict(slot_id=slot_id,recording_id=item.recording_id,candidate_id=model.id,repeat=repeat,diagnostic_for=diagnostic_for)))
        path=run_root/'slots'/slot_id/'output';path.mkdir(parents=True)
        wire=output(path/'native',model.id,checkpoint_sha=model.checkpoint_sha256,
            input_sha=item.basic_audio_sha256 if model.id=='basic_pitch' else item.piano_audio_sha256)
        events=Events((Note(60,3.,4.,None if model.id=='basic_pitch' else 80.),),())
        native=path/'native';normalized=path/'events.json';normalized.write_bytes(canonical_json(asdict(events)))
        files={p.relative_to(run_root).as_posix():digest_file(p) for p in (*native.iterdir(),normalized)}
        failure=failures.get(slot_id)
        if failure:
            return RunRecord(slot_id,item.recording_id,model.id,repeat,diagnostic_for,failure[0],failure[1],failure[2],
                .1,None,path,True,3,('cause_unavailable',),files,None)
        metrics=dict(onset=metric(1,0,0),sustain=metric(1,0,0),key_release=metric(1,0,0),
            velocity=dict(mae=None if model.id=='basic_pitch' else 0.,pairs=[[0,0]],
                reference_sorted=[dict(pitch=60,onset=3.,offset=4.,velocity=80.)],
                prediction_sorted=[asdict(events.notes[0])]),
            censored=dict(reference_key_release=0,reference_sustain=0,predicted=0))
        return RunRecord(slot_id,item.recording_id,model.id,repeat,diagnostic_for,'success',None,None,.1,
            events_hash(events),path,True,0,('input_verified','environment_verified','owned_process_cleaned'),files,metrics)
    monkeypatch.setattr(session,'run_slot',slot)
    return session,manifest,models,calls


def run_session(tmp_path,session,manifest,models,cancellation=None):
    return asyncio.run(session.run_evaluation(manifest,models,manifest_path=tmp_path/'manifest.json',input_root=tmp_path,
        ffmpeg=Path(sys.executable),run_root=tmp_path/'run',cancellation=cancellation or asyncio.Event()))


def test_schedule_order_72_and_first_accuracy_is_not_repeats(tmp_path,monkeypatch):
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    schedule=session.build_schedule(manifest,models)
    assert len(schedule)==72
    assert [(s['recording_id'],s['candidate_id']) for s in schedule[:2]]==[(manifest.entries[0].recording_id,'basic_pitch'),(manifest.entries[0].recording_id,'piano_amt')]
    assert schedule[24]['recording_id']==manifest.entries[-1].recording_id and schedule[24]['candidate_id']=='piano_amt'
    path=run_session(tmp_path,session,manifest,models)
    value=json.loads(path.read_bytes())['summary']
    assert len(calls)==76 and len(value['records'])==72 and value['decision']['winner']=='basic_pitch'
    assert len(value['models']['basic_pitch']['first_runs'])==12
    assert value['models']['basic_pitch']['reliability']['scheduled']==36


def test_diagnostic_success_preserves_failure(tmp_path,monkeypatch):
    failures={'r0-000-basic_pitch':('model_error','unresolved','worker_exit_3')}
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch,failures)
    path=run_session(tmp_path,session,manifest,models);value=json.loads(path.read_bytes())['summary']
    model=value['models']['basic_pitch']
    assert model['first_runs'][manifest.entries[0].recording_id] is None
    assert model['reliability']['started']==36 and model['reliability']['success']==35
    assert model['reliability']['model_only_denominator']==35
    assert model['reliability']['raw_failure_rate']==pytest.approx(1/36)
    assert len(model['elapsed_sec'])==35 and value['decision']['status']=='no_selection'
    assert len(value['records'])==73 and sum(s.startswith('diag-') for s in calls)==1


def test_reference_recalls_use_their_own_success_tp_and_planned_denominators(tmp_path,monkeypatch):
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch);original=session.run_slot
    async def offsets_differ(*args,**kwargs):
        record=await original(*args,**kwargs)
        record.metrics['key_release']=metric(0,1,1)
        return replace(record,metrics=record.metrics)
    monkeypatch.setattr(session,'run_slot',offsets_differ)
    value=json.loads(run_session(tmp_path,session,manifest,models).read_bytes())['summary']
    for model in value['models'].values():
        recall=model['operational_recall']
        assert recall['key_release']==dict(tp=0,planned_reference_notes=12,recall=0.)
        assert recall['sustain']==dict(tp=12,planned_reference_notes=12,recall=1.)


@pytest.mark.parametrize('code',['worker_exit_3','worker_exit_4'])
def test_repeated_generic_error_never_becomes_model_ineligible(tmp_path,monkeypatch,code):
    failures={f'r{i}-000-basic_pitch':('model_error' if code.endswith('3') else 'output_invalid','unresolved',code) for i in (1,2)}
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch,failures)
    value=json.loads(run_session(tmp_path,session,manifest,models).read_bytes())['summary']
    model=value['models']['basic_pitch']
    assert model['operationally_ineligible'] is False and model['reliability']['model_only_denominator']==34
    assert model['unresolved_failures']==2 and value['decision']['status']=='selection_requires_review'


def test_preflight_failure_creates_all_not_run_and_no_overwrite(tmp_path,monkeypatch):
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch,{'preflight-basic_pitch-0':('model_error','unresolved','worker_exit_3')})
    path=run_session(tmp_path,session,manifest,models);value=json.loads(path.read_bytes())['summary']
    assert value['gates']==['preflight_failure'] and all(v['not_run']==36 for v in value['models'].values())
    assert value['decision']['status']=='no_selection'
    before=path.read_bytes()
    with pytest.raises(ValueError):run_session(tmp_path,session,manifest,models)
    assert path.read_bytes()==before


def test_pre_cancelled_session_preserves72_not_run(tmp_path,monkeypatch):
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch);cancel=asyncio.Event();cancel.set()
    value=json.loads(run_session(tmp_path,session,manifest,models,cancel).read_bytes())['summary']
    assert not calls and all(v['not_run']==36 for v in value['models'].values())


def test_reproduction_requires_same_input_and_verified_primitive_cause(tmp_path):
    from musicsheet_transcription_eval.contracts import RunRecord
    from musicsheet_transcription_eval.session import reproducible_failures
    def record(slot,recording='a'*64,cause='verified_model_prediction'):
        return RunRecord(slot,recording,'basic_pitch',0,None,'model_error','model',cause,.1,None,tmp_path,True,3,
            ('input_verified','environment_verified','model_cause_verified','cause_native_prediction'),{},None)
    assert not reproducible_failures([record('r0-a'),record('r1-a','b'*64)])
    assert not reproducible_failures([record('r0-a'),record('r1-a',cause='verified_model_inference')])
    assert reproducible_failures([record('r0-a'),record('r1-a')])
