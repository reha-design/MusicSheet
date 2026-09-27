"""Validate and atomically publish Basic Pitch JSON and MIDI outputs."""

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from numbers import Integral, Real

import pretty_midi

from musicsheet_basic_pitch_worker.inference import PredictionOutput
from musicsheet_basic_pitch_worker.mapping import map_note_events
from musicsheet_basic_pitch_worker.provenance import (
    BASIC_PITCH_CONFIDENCE_SEMANTICS,
    BASIC_PITCH_MODEL_ASSET,
    BASIC_PITCH_PROVIDER_ID,
    BASIC_PITCH_SUPPORTS_PEDAL,
)


class ResultValidationError(ValueError):
    """Raised when a result does not satisfy transcription schema version 1."""


class OutputError(RuntimeError):
    """Raised when output files cannot be staged and atomically published."""


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResultValidationError(f"{label} must be an object")
    return value


def _number(value: object, label: str, *, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ResultValidationError(f"{label} must be a finite number")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ResultValidationError(f"{label} must be a finite number") from error
    if not math.isfinite(converted) or converted < minimum:
        raise ResultValidationError(f"{label} is outside the allowed range")
    if maximum is not None and converted > maximum:
        raise ResultValidationError(f"{label} is outside the allowed range")
    return converted


def _integer(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ResultValidationError(f"{label} must be an integer")
    converted = int(value)
    if not minimum <= converted <= maximum:
        raise ResultValidationError(f"{label} is outside the allowed range")
    return converted


def build_result(
    prediction: PredictionOutput,
    *,
    package_version: str,
    source_commit: str,
) -> dict[str, object]:
    try:
        result: dict[str, object] = {
            "schema_version": 1,
            "provider": {
                "id": BASIC_PITCH_PROVIDER_ID,
                "package_version": package_version,
                "source_commit": source_commit,
                "model_asset": BASIC_PITCH_MODEL_ASSET,
                "supports_pedal": BASIC_PITCH_SUPPORTS_PEDAL,
                "confidence_semantics": BASIC_PITCH_CONFIDENCE_SEMANTICS,
            },
            "note_events": map_note_events(prediction.note_events),
            "pedal_events": [],
        }
        validate_result_payload(result)
        return result
    except ResultValidationError:
        raise
    except (TypeError, ValueError) as error:
        raise ResultValidationError(f"could not build transcription result: {error}") from error


def validate_result_payload(result: Mapping[str, object]) -> None:
    """Validate the worker JSON contract without importing the backend package."""
    payload = _require_mapping(result, "result")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ResultValidationError("schema_version must be 1")

    provider = _require_mapping(payload.get("provider"), "provider")
    for field in (
        "id",
        "package_version",
        "source_commit",
        "model_asset",
        "confidence_semantics",
    ):
        value = provider.get(field)
        if not isinstance(value, str) or not value:
            raise ResultValidationError(f"provider.{field} must be a nonempty string")
    if not isinstance(provider.get("supports_pedal"), bool):
        raise ResultValidationError("provider.supports_pedal must be a boolean")

    note_events = payload.get("note_events")
    if not isinstance(note_events, list):
        raise ResultValidationError("note_events must be an array")
    for index, event in enumerate(note_events):
        note = _require_mapping(event, f"note_events[{index}]")
        note_id = note.get("note_id")
        if not isinstance(note_id, str) or not note_id:
            raise ResultValidationError(f"note_events[{index}].note_id must be a nonempty string")
        _integer(note.get("pitch"), f"note_events[{index}].pitch", minimum=0, maximum=127)
        onset = _number(note.get("onset_sec"), f"note_events[{index}].onset_sec", minimum=0)
        offset = _number(note.get("offset_sec"), f"note_events[{index}].offset_sec", minimum=0)
        if offset < onset:
            raise ResultValidationError(f"note_events[{index}] ends before it starts")
        for field, minimum, maximum in (
            ("activation", 0.0, 1.0),
            ("velocity_prediction", 0.0, 127.0),
            ("amt_confidence", 0.0, 1.0),
        ):
            value = note.get(field)
            if value is None and field in {"activation", "velocity_prediction"}:
                continue
            _number(value, f"note_events[{index}].{field}", minimum=minimum, maximum=maximum)
        source_chunk = note.get("source_chunk")
        if source_chunk is not None and (
            isinstance(source_chunk, bool) or not isinstance(source_chunk, Integral)
        ):
            raise ResultValidationError(f"note_events[{index}].source_chunk must be an integer or null")

    pedal_events = payload.get("pedal_events")
    if not isinstance(pedal_events, list):
        raise ResultValidationError("pedal_events must be an array")
    for index, event in enumerate(pedal_events):
        pedal = _require_mapping(event, f"pedal_events[{index}]")
        event_type = pedal.get("event_type", "sustain")
        if not isinstance(event_type, str) or event_type not in {"sustain", "soft", "sostenuto"}:
            raise ResultValidationError(f"pedal_events[{index}].event_type is unsupported")
        onset = _number(pedal.get("onset_sec"), f"pedal_events[{index}].onset_sec", minimum=0)
        offset = _number(pedal.get("offset_sec"), f"pedal_events[{index}].offset_sec", minimum=0)
        if offset < onset:
            raise ResultValidationError(f"pedal_events[{index}] ends before it starts")
        _integer(pedal.get("value", 127), f"pedal_events[{index}].value", minimum=0, maximum=127)


def write_outputs(
    output_dir: Path,
    result: dict[str, object],
    midi_data: pretty_midi.PrettyMIDI | None,
) -> None:
    """Stage all artifacts in a sibling directory, then publish with one rename."""
    target = Path(output_dir)
    validate_result_payload(result)
    if target.exists() or target.is_symlink():
        raise OutputError(f"output path already exists: {target}")

    temporary_dir: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent)
        )
        json_path = temporary_dir / "raw_transcription.json"
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        if midi_data is not None:
            midi_data.write(str(temporary_dir / "transcription.mid"))
        os.rename(temporary_dir, target)
        temporary_dir = None
    except Exception as error:
        raise OutputError(f"could not publish transcription outputs: {error}") from error
    finally:
        if temporary_dir is not None:
            shutil.rmtree(temporary_dir, ignore_errors=True)
