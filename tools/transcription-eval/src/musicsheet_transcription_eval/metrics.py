"""Pinned mir_eval matching and explicit micro/macro accounting."""

from collections.abc import Sequence
import math

from mir_eval.transcription import match_notes
import numpy as np

from .contracts import EvaluationLimitError, Events, Metric, Note, Pedal, ScoredEvents, VelocityMatch, integer, metric_values

MATCH_CELL_LIMIT = 1_000_000


def scoring_events(events: Events, *, start_sec: int) -> ScoredEvents:
    integer(start_sec, 0)
    if type(events) is not Events:
        raise ValueError("invalid events")
    notes, pedals, censored = [], [], 0
    for note in events.notes:
        onset = note.onset - start_sec
        if 2 <= onset < 28:
            offset = note.offset - start_sec
            censored += offset > 30
            notes.append(Note(note.pitch, onset, min(30.0, offset), note.velocity))
    for pedal in events.pedals:
        onset, offset = max(0.0, pedal.onset - start_sec), min(30.0, pedal.offset - start_sec)
        if offset > onset:
            pedals.append(Pedal(pedal.kind, onset, offset, pedal.value))
    return ScoredEvents(Events(tuple(notes), tuple(pedals)), censored)


def _sorted(events: Events) -> tuple[Note, ...]:
    if type(events) is not Events:
        raise ValueError("invalid events")
    return tuple(sorted(events.notes, key=lambda n: (n.pitch, n.onset, n.offset, n.velocity is not None, n.velocity or 0.0)))


def _match(ref: tuple[Note, ...], pred: tuple[Note, ...], *, with_offsets: bool) -> tuple[tuple[int, int], ...]:
    if len(ref) * len(pred) > MATCH_CELL_LIMIT:
        raise EvaluationLimitError("matching_cell_limit")
    if not ref or not pred:
        return ()
    def arrays(notes):
        intervals = np.array([(n.onset, n.offset) for n in notes], dtype=np.float64)
        pitches = np.array([440.0 * 2 ** ((n.pitch - 69) / 12) for n in notes], dtype=np.float64)
        return intervals, pitches
    ref_intervals, ref_pitches = arrays(ref)
    pred_intervals, pred_pitches = arrays(pred)
    return tuple((int(i), int(j)) for i, j in match_notes(
        ref_intervals, ref_pitches, pred_intervals, pred_pitches,
        onset_tolerance=0.05, pitch_tolerance=50.0,
        offset_ratio=0.2 if with_offsets else None,
        offset_min_tolerance=0.05, strict=False,
    ))


def _metric(tp: int, fp: int, fn: int) -> Metric:
    return Metric(tp, fp, fn, *metric_values(tp, fp, fn))


def score_notes(reference: Events, predicted: Events, *, with_offsets: bool) -> Metric:
    if type(with_offsets) is not bool:
        raise ValueError("invalid offset option")
    ref, pred = _sorted(reference), _sorted(predicted)
    tp = len(_match(ref, pred, with_offsets=with_offsets))
    return _metric(tp, len(pred) - tp, len(ref) - tp)


def velocity_mae(reference: Events, predicted: Events) -> VelocityMatch:
    ref, pred = _sorted(reference), _sorted(predicted)
    pairs = _match(ref, pred, with_offsets=False)
    # No invented velocities, nor a hidden smaller pair count for partial data.
    complete = bool(pairs) and all(ref[i].velocity is not None and pred[j].velocity is not None for i, j in pairs)
    mae = math.fsum(abs(ref[i].velocity - pred[j].velocity) for i, j in pairs) / len(pairs) if complete else None
    return VelocityMatch(mae, pairs, ref, pred)


def aggregate(metrics: Sequence[Metric]) -> dict[str, object]:
    values = tuple(metrics)
    if any(type(value) is not Metric for value in values):
        raise ValueError("invalid metric sequence")
    included = [value for value in values if value.f1 is not None]
    micro = _metric(sum(m.tp for m in values), sum(m.fp for m in values), sum(m.fn for m in values))
    return {
        "macro_f1": math.fsum(m.f1 for m in included) / len(included) if included else None,
        "micro": micro,
        "included_recordings": len(included),
        "excluded_empty_reference": len(values) - len(included),
    }
