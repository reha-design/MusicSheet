import dataclasses
import itertools

import pytest

from musicsheet_transcription_eval.contracts import EvaluationLimitError, Events, Note, Pedal
from musicsheet_transcription_eval.metrics import aggregate, score_notes, scoring_events, velocity_mae


def events(*notes):
    return Events(tuple(notes), ())


def test_duplicate_prediction_is_fp():
    ref = events(Note(60, 2.0, 3.0, 80.0))
    pred = events(Note(60, 2.0, 3.0, 80.0), Note(60, 2.0, 3.0, 80.0))
    result = score_notes(ref, pred, with_offsets=False)
    assert (result.tp, result.fp, result.fn) == (1, 1, 0)
    assert result.f1 == pytest.approx(2 / 3)


def test_empty_reference_is_null():
    result = score_notes(events(), events(Note(60, 2.0, 3.0, 80.0), Note(62, 2.0, 3.0, 80.0)), with_offsets=False)
    assert (result.tp, result.fp, result.fn) == (0, 2, 0)
    assert result.precision is result.recall is result.f1 is None


def test_empty_prediction_is_valid_zero_score():
    result = score_notes(events(Note(60, 2.0, 3.0, 80.0)), events(), with_offsets=True)
    assert (result.tp, result.fp, result.fn, result.f1) == (0, 0, 1, 0.0)


@pytest.mark.parametrize("delta,tp", [(0.05, 1), (0.0501, 0)])
def test_onset_50ms_boundary(delta, tp):
    assert score_notes(events(Note(60, 2.0, 3.0, None)), events(Note(60, 2.0 + delta, 3.0, None)), with_offsets=False).tp == tp


@pytest.mark.parametrize("offset,tp", [(3.2, 1), (3.2001, 0)])
def test_offset_duration_tolerance(offset, tp):
    ref, pred = events(Note(60, 2.0, 3.0, None)), events(Note(60, 2.0, offset, None))
    assert score_notes(ref, pred, with_offsets=True).tp == tp
    assert score_notes(ref, pred, with_offsets=False).tp == 1


@pytest.mark.parametrize("offset,tp", [(2.15, 1), (2.1501, 0)])
def test_offset_minimum_50ms(offset, tp):
    assert score_notes(events(Note(60, 2.0, 2.1, None)), events(Note(60, 2.0, offset, None)), with_offsets=True).tp == tp


def test_wrong_semitone_is_not_matched():
    assert score_notes(events(Note(60, 2.0, 3.0, None)), events(Note(61, 2.0, 3.0, None)), with_offsets=False).tp == 0


def test_maximum_matching_and_permutation_invariance():
    refs = (Note(60, 2.0, 3.0, 80.0), Note(60, 2.06, 3.0, 80.0))
    preds = (Note(60, 2.04, 3.0, 80.0), Note(60, 1.96, 3.0, 80.0))
    for ref, pred in itertools.product(itertools.permutations(refs), itertools.permutations(preds)):
        assert score_notes(events(*ref), events(*pred), with_offsets=False).tp == 2


def test_crop_preserves_prior_pedal_and_censors_offset():
    raw = Events((Note(60, 11.9, 32.0, 80.0), Note(61, 12.0, 41.0, 80.0), Note(62, 38.0, 39.0, 80.0)), (Pedal("sustain", 9.0, 41.0, 127),))
    scored = scoring_events(raw, start_sec=10)
    assert scored.events.notes == (Note(61, 2.0, 30.0, 80.0),)
    assert scored.events.pedals == (Pedal("sustain", 0.0, 30.0, 127),)
    assert scored.censored_count == 1
    pred = scoring_events(events(Note(61, 2.0, 31.0, 80.0)), start_sec=0)
    assert pred.events.notes[0].offset == 30.0
    assert pred.censored_count == 1


def test_velocity_uses_onset_matching():
    result = velocity_mae(events(Note(60, 2.0, 3.0, 80.0)), events(Note(60, 2.0, 5.0, 70.0)))
    assert result.mae == 10.0
    assert result.pairs == ((0, 0),)
    assert len(result.pairs) == 1


def test_velocity_matching_sorted_pairs_are_reproducible():
    ref = events(Note(62, 2.0, 3.0, 90.0), Note(60, 2.0, 3.0, 80.0))
    pred = events(Note(62, 2.0, 4.0, 80.0), Note(60, 2.0, 4.0, 60.0))
    a, b = velocity_mae(ref, pred), velocity_mae(events(*reversed(ref.notes)), events(*reversed(pred.notes)))
    assert a == b
    assert [n.pitch for n in a.reference_sorted] == [60, 62]
    assert a.mae == 15.0
    assert a.pairs == ((0, 0), (1, 1))


def test_velocity_missing_or_unmatched_is_null():
    ref = events(Note(60, 2.0, 3.0, 80.0))
    assert velocity_mae(ref, events()).mae is None
    result = velocity_mae(ref, events(Note(60, 2.0, 3.0, None)))
    assert result.mae is None
    assert result.pairs == ((0, 0),)


def test_macro_micro_and_empty_reference_counts():
    a = score_notes(events(Note(60, 2.0, 3.0, None)), events(Note(60, 2.0, 3.0, None)), with_offsets=False)
    b = score_notes(events(*(Note(60, 2.0, 3.0, None) for _ in range(3))), events(), with_offsets=False)
    c = score_notes(events(), events(Note(60, 2.0, 3.0, None)), with_offsets=False)
    summary = aggregate((a, b, c))
    assert summary["macro_f1"] == 0.5
    assert (summary["micro"].tp, summary["micro"].fp, summary["micro"].fn) == (1, 1, 3)
    assert summary["micro"].f1 == pytest.approx(1 / 3)
    assert summary["excluded_empty_reference"] == 1


def test_aggregate_empty_is_null():
    assert aggregate(())["macro_f1"] is None
    assert aggregate(())["micro"].f1 is None


@pytest.mark.parametrize("args", [(True, 2., 3., 80.), (128, 2., 3., 80.), (60, float("nan"), 3., 80.), (60, 2., float("inf"), 80.), (60, 2., 2., 80.), (60, -1., 3., 80.), (60, 2., 3., True), (60, 2., 3., 128.)])
def test_invalid_note_values_rejected(args):
    with pytest.raises(ValueError): Note(*args)


def test_contracts_frozen_and_strict():
    note = Note(60, 2., 3., None)
    with pytest.raises(dataclasses.FrozenInstanceError): note.pitch = 61
    with pytest.raises(ValueError): Events([note], ())
    with pytest.raises(ValueError): Pedal("invalid", 0., 1., 127)
    with pytest.raises(ValueError): Pedal("sustain", 0., 1., True)
    with pytest.raises(ValueError): scoring_events(events(note), start_sec=True)


@pytest.mark.parametrize("mode", ["onset", "offset", "velocity"])
def test_matching_cell_cap_before_arrays(monkeypatch, mode):
    from musicsheet_transcription_eval import metrics
    monkeypatch.setattr(metrics, "MATCH_CELL_LIMIT", 3, raising=False)
    ref = pred = events(Note(60, 2., 3., 80.), Note(62, 2., 3., 80.))
    def forbidden(*args, **kwargs):
        pytest.fail("array or matcher called before cell cap")
    monkeypatch.setattr(metrics.np, "array", forbidden)
    monkeypatch.setattr(metrics, "match_notes", forbidden)
    with pytest.raises(EvaluationLimitError, match="limit"):
        if mode == "velocity": velocity_mae(ref, pred)
        else: score_notes(ref, pred, with_offsets=mode == "offset")


def test_matching_cell_cap_boundary(monkeypatch):
    from musicsheet_transcription_eval import metrics
    monkeypatch.setattr(metrics, "MATCH_CELL_LIMIT", 4, raising=False)
    ref = pred = events(Note(60, 2., 3., 80.), Note(62, 2., 3., 80.))
    assert score_notes(ref, pred, with_offsets=False).tp == 2
    assert velocity_mae(ref, pred).mae == 0.


@pytest.mark.parametrize("mae,pairs,ref,pred", [
    (7., (), (), ()),
    (0., ((0, 0),), (Note(60, 2., 3., 80.),), (Note(60, 2., 3., 70.),)),
    (1., ((0, 0),), (Note(60, 2., 3., 80.),), (Note(60, 2., 3., None),)),
])
def test_velocity_match_rejects_inconsistent_mae(mae, pairs, ref, pred):
    from musicsheet_transcription_eval.contracts import VelocityMatch
    with pytest.raises(ValueError): VelocityMatch(mae, pairs, ref, pred)
