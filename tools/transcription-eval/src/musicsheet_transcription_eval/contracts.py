"""Strict immutable metric inputs, separate from product schemas."""

from dataclasses import dataclass
import math


class EvaluationLimitError(ValueError):
    """Evaluator resource limit; never attribute this to model reliability."""


def integer(value: object, minimum: int, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or maximum is not None and value > maximum:
        raise ValueError("invalid integer")


def finite(value: object, minimum: float = 0.0, maximum: float | None = None) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum or maximum is not None and value > maximum:
        raise ValueError("invalid finite number")


def interval(onset: float, offset: float) -> None:
    finite(onset)
    finite(offset)
    if offset <= onset:
        raise ValueError("nonpositive interval")


@dataclass(frozen=True)
class Note:
    pitch: int
    onset: float
    offset: float
    velocity: float | None

    def __post_init__(self) -> None:
        integer(self.pitch, 0, 127)
        interval(self.onset, self.offset)
        if self.velocity is not None:
            finite(self.velocity, 0, 127)


@dataclass(frozen=True)
class Pedal:
    kind: str
    onset: float
    offset: float
    value: int

    def __post_init__(self) -> None:
        if self.kind not in {"sustain", "soft", "sostenuto"}:
            raise ValueError("invalid pedal kind")
        interval(self.onset, self.offset)
        integer(self.value, 0, 127)


@dataclass(frozen=True)
class Events:
    notes: tuple[Note, ...]
    pedals: tuple[Pedal, ...]

    def __post_init__(self) -> None:
        for values, cls in ((self.notes, Note), (self.pedals, Pedal)):
            if type(values) is not tuple or any(type(value) is not cls for value in values):
                raise ValueError("invalid event tuple")


@dataclass(frozen=True)
class Reference:
    key_release: Events
    sustain: Events

    def __post_init__(self) -> None:
        if type(self.key_release) is not Events or type(self.sustain) is not Events:
            raise ValueError("invalid reference")


@dataclass(frozen=True)
class Metric:
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None

    def __post_init__(self) -> None:
        for count in (self.tp, self.fp, self.fn):
            integer(count, 0)
        for value in (self.precision, self.recall, self.f1):
            if value is not None:
                finite(value, 0, 1)
        expected = metric_values(self.tp, self.fp, self.fn)
        if (self.precision, self.recall, self.f1) != expected:
            raise ValueError("inconsistent metric")


def metric_values(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    if tp + fn == 0:
        return None, None, None
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn)
    f1 = 2 * tp / (2 * tp + fp + fn)
    return precision, recall, f1


@dataclass(frozen=True)
class ScoredEvents:
    events: Events
    censored_count: int

    def __post_init__(self) -> None:
        if type(self.events) is not Events:
            raise ValueError("invalid events")
        integer(self.censored_count, 0, len(self.events.notes))


@dataclass(frozen=True)
class VelocityMatch:
    mae: float | None
    pairs: tuple[tuple[int, int], ...]
    reference_sorted: tuple[Note, ...]
    prediction_sorted: tuple[Note, ...]

    def __post_init__(self) -> None:
        Events(self.reference_sorted, ())
        Events(self.prediction_sorted, ())
        if type(self.pairs) is not tuple:
            raise ValueError("invalid matching")
        seen_ref, seen_pred = set(), set()
        for pair in self.pairs:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("invalid pair")
            i, j = pair
            integer(i, 0, len(self.reference_sorted) - 1)
            integer(j, 0, len(self.prediction_sorted) - 1)
            if i in seen_ref or j in seen_pred:
                raise ValueError("matching is not one-to-one")
            seen_ref.add(i)
            seen_pred.add(j)
        if self.mae is not None:
            finite(self.mae, 0, 127)
        complete = bool(self.pairs) and all(
            self.reference_sorted[i].velocity is not None and self.prediction_sorted[j].velocity is not None
            for i, j in self.pairs
        )
        expected = math.fsum(
            abs(self.reference_sorted[i].velocity - self.prediction_sorted[j].velocity)
            for i, j in self.pairs
        ) / len(self.pairs) if complete else None
        if self.mae != expected:
            raise ValueError("inconsistent velocity MAE")
