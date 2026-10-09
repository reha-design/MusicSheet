import copy

import pytest

from task4_support import metric,selection_input


def change(summary,kind,which,value):
    for record in summary['models'][kind]['first_runs'].values():record[which]=value


def test_equal_accuracy_equal_speed_keeps_provisional_basic():
    from musicsheet_transcription_eval.selection import select_model
    result=select_model(selection_input())
    assert result['status']=='provisional_operational_default' and result['winner']=='basic_pitch'
    assert result['accuracy_winner'] is False


def test_clear_piano_onset_winner_is_pending_product_integration():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();change(summary,'piano_amt','onset',metric(90,10,10))
    result=select_model(summary)
    assert result['status']=='selected_for_subset' and result['winner']=='piano_amt'
    assert result['product_status']=='selected_pending_integration' and result['paired_n']==12
    assert result['onset_ci'][0]>.09 and result['onset_ci'][1]<.11


def test_macro_micro_reversal_requires_review():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input()
    change(summary,'basic_pitch','onset',metric(88,12,12));change(summary,'piano_amt','onset',metric(91,9,9))
    key=list(summary['models']['basic_pitch']['first_runs'])[-1]
    summary['models']['basic_pitch']['first_runs'][key]['onset']=metric(9200,800,800)
    summary['models']['piano_amt']['first_runs'][key]['onset']=metric(8800,1200,1200)
    assert select_model(summary)['status']=='tradeoff_requires_review'


@pytest.mark.parametrize('case',['incomplete','one_bit','unresolved','time_samples'])
def test_incomplete_determinism_blocks_selection(case):
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();model=summary['models']['piano_amt'];key=next(iter(model['determinism']))
    if case=='incomplete':model['determinism'][key]=dict(status='determinism_incomplete',hashes=['a'*64]*2,f1_range=[.8,.8])
    elif case=='one_bit':model['determinism'][key]=dict(status='nondeterministic_output',hashes=['a'*64,'b'*64,'a'*64],f1_range=[.8,.9])
    elif case=='unresolved':model['unresolved_failures']=1
    else:model['elapsed_sec']=[10.]*23
    assert select_model(summary)['status']=='selection_requires_review'


@pytest.mark.parametrize('case',['first_failure','not_run','invalid_benchmark','pairs'])
def test_invalid_first_or_gate_cannot_select(case):
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();model=summary['models']['piano_amt']
    if case=='first_failure':model['first_runs'][next(iter(model['first_runs']))]=None
    elif case=='not_run':model['not_run']=1
    elif case=='invalid_benchmark':summary['gates']=['evaluation_limit']
    else:
        for kind in summary['models']:
            for key in list(summary['models'][kind]['first_runs'])[7:]:
                summary['models'][kind]['first_runs'][key]['onset']=metric(0,0,0)
    assert select_model(summary)['status']=='no_selection'


@pytest.mark.parametrize('piano_time,winner',[(8.,'piano_amt'),(8.001,'basic_pitch')])
def test_cpu20_percent_boundary_and_minimum_samples(piano_time,winner):
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();summary['models']['piano_amt']['elapsed_sec']=[piano_time]*24
    result=select_model(summary)
    assert result['winner']==winner and result['accuracy_winner'] is False


def test_exact_one_percentage_point_effect_and_offset_tradeoff_guard():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();change(summary,'basic_pitch','onset',metric(10,90,90));change(summary,'piano_amt','onset',metric(11,89,89))
    assert select_model(summary)['winner']=='piano_amt'
    change(summary,'piano_amt','sustain',metric(78,22,22))
    assert select_model(summary)['status']=='tradeoff_requires_review'


def test_bootstrap_crosses_zero_and_sustain_winner_fallback():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input()
    for i,record in enumerate(summary['models']['piano_amt']['first_runs'].values()):record['onset']=metric(90 if i%2 else 70,10 if i%2 else 30,10 if i%2 else 30)
    result=select_model(summary);assert result['onset_ci'][0]<0<result['onset_ci'][1]
    change(summary,'piano_amt','sustain',metric(90,10,10))
    assert select_model(summary)['reason']=='sustain_accuracy'


def test_malformed_metric_or_bool_cannot_produce_winner():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();key=next(iter(summary['models']['piano_amt']['first_runs']))
    summary['models']['piano_amt']['first_runs'][key]['onset']['tp']=True
    with pytest.raises(ValueError):select_model(summary)


def test_empty_reference_false_positives_remain_in_micro_guard():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();change(summary,'piano_amt','onset',metric(90,10,10))
    for key in list(summary['models']['basic_pitch']['first_runs'])[-4:]:
        for kind,fp in [('basic_pitch',0),('piano_amt',1000)]:
            for name in ('onset','sustain','key_release'):summary['models'][kind]['first_runs'][key][name]=metric(0,fp,0)
    assert select_model(summary)['status']=='tradeoff_requires_review'


def test_onset_winner_uses_sustain_macro_guard_without_extra_sustain_micro_veto():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();change(summary,'piano_amt','onset',metric(90,10,10))
    change(summary,'basic_pitch','sustain',metric(80,20,20));change(summary,'piano_amt','sustain',metric(81,19,19))
    key=list(summary['models']['basic_pitch']['first_runs'])[-1]
    summary['models']['basic_pitch']['first_runs'][key]['sustain']=metric(9000,1000,1000)
    summary['models']['piano_amt']['first_runs'][key]['sustain']=metric(8000,2000,2000)
    assert select_model(summary)['status']=='selected_for_subset'


@pytest.mark.parametrize('tp,expected',[(7901,'selected_for_subset'),(7900,'selected_for_subset'),(7899,'tradeoff_requires_review')])
def test_sustain_macro_one_pp_guard_exact_and_adjacent_boundaries(tp,expected):
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input();change(summary,'piano_amt','onset',metric(90,10,10))
    change(summary,'piano_amt','sustain',metric(tp,10000-tp,10000-tp))
    assert select_model(summary)['status']==expected


def test_paired_one_pp_effect_avoids_rounding_separate_decimal_means():
    from musicsheet_transcription_eval.selection import select_model
    summary=selection_input()
    for kind,increment in [('basic_pitch',0),('piano_amt',1)]:
        for index,record in enumerate(summary['models'][kind]['first_runs'].values()):
            tp=(9 if index<8 else 10)+increment
            record['onset']=metric(tp,100-tp,100-tp)
    result=select_model(summary)
    assert result['status']=='selected_for_subset' and result['winner']=='piano_amt'
