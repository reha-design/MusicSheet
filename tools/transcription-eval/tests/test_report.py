import json

import pytest

from test_runner import run_session,session_fixture


def test_verified_report_keeps_metrics_failure_denominators_and_product_boundary(tmp_path,monkeypatch):
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    summary=run_session(tmp_path,session,manifest,models);destination=tmp_path/'report.md'
    write_report(summary.parent,destination)
    text=destination.read_text(encoding='utf-8')
    assert 'provisional_operational_default' in text and '36' in text and 'MAESTRO' in text
    assert 'macro' in text and 'micro' in text and 'p95' in text and 'velocity' in text
    assert 'selected_pending_integration' in text
    assert '0.4.0' in text and '0.0.6' in text and 'Logical cores' in text
    assert models[0].checkpoint_sha256 in text and models[0].lock_sha256 in text
    with pytest.raises(ValueError):write_report(summary.parent,destination)


@pytest.mark.parametrize('case',['raw','record','summary','start'])
def test_report_rejects_tampered_artifact(tmp_path,monkeypatch,case):
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch);summary=run_session(tmp_path,session,manifest,models)
    if case=='raw':path=next((summary.parent/'slots').rglob('raw_transcription.json'))
    elif case=='record':path=next((summary.parent/'records').glob('*.json'))
    elif case=='start':path=next((summary.parent/'starts').glob('*.json'))
    else:path=summary
    path.write_bytes(b'tampered')
    with pytest.raises(ValueError):write_report(summary.parent,tmp_path/'report.md')
    assert not (tmp_path/'report.md').exists()


def test_preflight_failure_report_allows_unstarted_slots_without_start(tmp_path,monkeypatch):
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch,{'preflight-basic_pitch-0':('model_error','unresolved','worker_exit_3')})
    summary=run_session(tmp_path,session,manifest,models);destination=tmp_path/'report.md'
    write_report(summary.parent,destination)
    assert 'no_selection' in destination.read_text(encoding='utf-8')
    assert 'preflight-basic_pitch-0' in destination.read_text(encoding='utf-8')
    assert 'worker_exit_3' in destination.read_text(encoding='utf-8')


def test_public_report_no_raw_diagnostics_or_paths(tmp_path,monkeypatch):
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    summary=run_session(tmp_path,session,manifest,models);destination=tmp_path/'report.md'
    write_report(summary.parent,destination)
    text=destination.read_text(encoding='utf-8')
    assert 'Traceback' not in text and 'secret-sentinel' not in text and str(tmp_path) not in text


def test_run_and_report_cli_help_without_model_import(capsys):
    from musicsheet_transcription_eval.cli import main
    for name in ('run','report'):
        with pytest.raises(SystemExit) as error:main([name,'--help'])
        assert error.value.code==0
    text=capsys.readouterr().out
    assert '--basic-python' in text and '--run-dir' in text


def test_oversize_raw_is_preserved_without_read_or_hash_and_blocks_selection(tmp_path,monkeypatch):
    from musicsheet_transcription_eval import session
    from musicsheet_transcription_eval.report import write_report
    root=tmp_path/'artifacts';root.mkdir();raw=root/'raw_transcription.json';raw.write_bytes(b'oversized')
    monkeypatch.setattr(session,'RAW_JSON_LIMIT',4)
    def forbidden(*args,**kwargs):pytest.fail('oversize body must not be hashed')
    monkeypatch.setattr(session,'digest_file',forbidden)
    hashes,unverified=session.collect_artifacts(root)
    assert hashes=={} and unverified==[dict(path='raw_transcription.json',size_bytes=9,reason='size_limit')]
    assert raw.read_bytes()==b'oversized'


def test_orphan_start_cannot_become_complete_report_even_with_updated_hashes(tmp_path,monkeypatch):
    import hashlib
    from musicsheet_transcription_eval.manifest import canonical_json
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch);summary=run_session(tmp_path,session,manifest,models)
    orphan=summary.parent/'starts/orphan.json';orphan.write_bytes(b'{}')
    wrapper=json.loads(summary.read_bytes());wrapper['summary']['artifacts']['starts/orphan.json']=hashlib.sha256(b'{}').hexdigest()
    wrapper['sha256']=hashlib.sha256(canonical_json(wrapper['summary'])).hexdigest();summary.write_bytes(canonical_json(wrapper))
    with pytest.raises(ValueError,match='orphan'):write_report(summary.parent,tmp_path/'report.md')


def test_full_oversize_session_report_preserves_bytes_and_forbids_winner(tmp_path,monkeypatch):
    from musicsheet_transcription_eval import report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(session,'RAW_JSON_LIMIT',4);monkeypatch.setattr(report,'RAW_JSON_LIMIT',4)
    path=run_session(tmp_path,session,manifest,models)
    value=json.loads(path.read_bytes())['summary']
    assert value['decision']['status']=='no_selection' and 'evaluation_limit' in value['gates']
    assert len(value['unverified_artifacts'])==76
    first=value['unverified_artifacts'][0];raw=path.parent/first['path'];before=raw.read_bytes()
    assert first['path'] not in value['artifacts']
    report.write_report(path.parent,tmp_path/'report.md')
    assert raw.read_bytes()==before and 'winner: none' in (tmp_path/'report.md').read_text()


@pytest.mark.parametrize('case',['censor_string','censor_bool','censor_range','velocity_index','velocity_mae','velocity_extra'])
def test_hashed_invalid_success_metrics_rejected_before_public_report(tmp_path,monkeypatch,case):
    import hashlib
    from musicsheet_transcription_eval.manifest import canonical_json
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch);path=run_session(tmp_path,session,manifest,models)
    wrapper=json.loads(path.read_bytes());name=wrapper['summary']['preflight'][0]
    record=json.loads((path.parent/name).read_bytes());metrics=record['metrics']
    if case=='censor_string':metrics['censored']['predicted']='secret-sentinel'
    elif case=='censor_bool':metrics['censored']['predicted']=True
    elif case=='censor_range':metrics['censored']['reference_sustain']=1000
    elif case=='velocity_index':metrics['velocity']['pairs']=[[99,99]]
    elif case=='velocity_mae':metrics['velocity']['mae']=12.
    elif case=='velocity_extra':metrics['velocity']['extra']='secret-sentinel'
    raw=canonical_json(record);(path.parent/name).write_bytes(raw)
    wrapper['summary']['artifacts'][name]=hashlib.sha256(raw).hexdigest()
    wrapper['sha256']=hashlib.sha256(canonical_json(wrapper['summary'])).hexdigest();path.write_bytes(canonical_json(wrapper))
    with pytest.raises(ValueError):write_report(path.parent,tmp_path/'invalid.md')
    assert not (tmp_path/'invalid.md').exists()


def test_public_report_explains_unresolved_failure_and_reference_recalls(tmp_path,monkeypatch):
    from musicsheet_transcription_eval.report import write_report
    session,manifest,models,calls=session_fixture(tmp_path,monkeypatch,{'r1-000-basic_pitch':('model_error','unresolved','worker_exit_3')})
    path=run_session(tmp_path,session,manifest,models);destination=tmp_path/'report.md';write_report(path.parent,destination)
    text=destination.read_text()
    assert all(word in text for word in ('worker_exit_3','model_error','unresolved','excluded_unresolved','precision','recall','key_release','sustain','diag-r1-000-basic_pitch'))
    value=json.loads(path.read_bytes())['summary']['models']['basic_pitch']['operational_recall']
    assert set(value)=={'key_release','sustain'}
    assert value['sustain']['planned_reference_notes']==12 and value['key_release']['tp']==12
