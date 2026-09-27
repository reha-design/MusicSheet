"""Translate Basic Pitch note tuples into the shared JSON event shape."""

import math
from collections.abc import Iterable, Sequence
from numbers import Integral, Real


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(converted):
        raise ValueError(f"{label} must be a finite number")
    return converted


def map_note_events(
    note_events: Iterable[Sequence[object]],
) -> list[dict[str, object]]:
    """Map (start, end, pitch, amplitude, pitch_bends) tuples to JSON events."""
    mapped: list[dict[str, object]] = []

    for index, note_event in enumerate(note_events, start=1):
        if (
            not isinstance(note_event, Sequence)
            or isinstance(note_event, (str, bytes))
            or len(note_event) != 5
        ):
            raise ValueError("each Basic Pitch note event must contain five values")

        start, end, pitch, amplitude, _pitch_bend_values = note_event
        onset_sec = _finite_number(start, "start")
        offset_sec = _finite_number(end, "end")
        if onset_sec < 0 or offset_sec < onset_sec:
            raise ValueError("note event must satisfy 0 <= start <= end")

        if isinstance(pitch, bool) or not isinstance(pitch, Integral):
            raise ValueError("pitch must be an integer MIDI note number")
        pitch_value = int(pitch)
        if not 0 <= pitch_value <= 127:
            raise ValueError("pitch must be in the MIDI range 0..127")

        activation = _finite_number(amplitude, "amplitude")
        if not 0.0 <= activation <= 1.0:
            raise ValueError("amplitude must be in the range 0..1")

        mapped.append(
            {
                "note_id": f"bp-{index:06d}",
                "pitch": pitch_value,
                "onset_sec": onset_sec,
                "offset_sec": offset_sec,
                "activation": activation,
                "velocity_prediction": None,
                "amt_confidence": activation,
                "source_chunk": None,
            }
        )

    return mapped
