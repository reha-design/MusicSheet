"""Narrow adapter around Basic Pitch's public inference API."""

from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
import sys
from collections.abc import Sequence

import pretty_midi


class InferenceError(RuntimeError):
    """Raised when Basic Pitch cannot complete a prediction."""


@dataclass(frozen=True)
class PredictionOutput:
    model_output: object
    midi_data: pretty_midi.PrettyMIDI | None
    note_events: Sequence[Sequence[object]]


def run_prediction(audio_path: Path) -> PredictionOutput:
    """Run the pinned Basic Pitch API and keep progress text off stdout."""
    try:
        from basic_pitch.inference import predict

        with redirect_stdout(sys.stderr):
            model_output, midi_data, note_events = predict(str(Path(audio_path)))
        return PredictionOutput(
            model_output=model_output,
            midi_data=midi_data,
            note_events=note_events,
        )
    except Exception as error:
        raise InferenceError(f"Basic Pitch prediction failed: {error}") from error
