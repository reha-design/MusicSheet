import json
from pathlib import Path

import pytest
import pretty_midi

from musicsheet_basic_pitch_worker.inference import PredictionOutput
from musicsheet_basic_pitch_worker.output import (
    OutputError,
    ResultValidationError,
    build_result,
    validate_result_payload,
    write_outputs,
)


SOURCE_COMMIT = "049dc8a01a170c2370d7b246ec1c2067e060c3bf"


def _prediction() -> PredictionOutput:
    return PredictionOutput(
        model_output=object(),
        midi_data=None,
        note_events=[(0.25, 1.5, 60, 0.82, [0, 1])],
    )


def test_builds_v1_envelope_with_provider_metadata():
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )

    assert result["schema_version"] == 1
    assert result["provider"] == {
        "id": "spotify-basic-pitch",
        "package_version": "0.4.0",
        "source_commit": SOURCE_COMMIT,
        "model_asset": "nmp.onnx",
        "supports_pedal": False,
        "confidence_semantics": "uncalibrated_note_activation_mean",
    }
    assert result["pedal_events"] == []
    assert result["note_events"][0]["activation"] == 0.82


def test_validate_result_payload_rejects_unsupported_version():
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    result["schema_version"] = 2

    with pytest.raises(ResultValidationError):
        validate_result_payload(result)


def test_validate_result_payload_rejects_out_of_range_note():
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    result["note_events"][0]["pitch"] = 128

    with pytest.raises(ResultValidationError):
        validate_result_payload(result)


def test_validate_result_payload_rejects_nonfinite_note():
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    result["note_events"][0]["amt_confidence"] = float("inf")

    with pytest.raises(ResultValidationError):
        validate_result_payload(result)


def test_validate_result_payload_rejects_reversed_note_interval():
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    result["note_events"][0]["offset_sec"] = 0.1

    with pytest.raises(ResultValidationError):
        validate_result_payload(result)


def test_validate_result_payload_rejects_invalid_pedal_event_type():
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    result["pedal_events"] = [
        {"event_type": [], "onset_sec": 0.0, "offset_sec": 1.0, "value": 127}
    ]

    with pytest.raises(ResultValidationError):
        validate_result_payload(result)


def test_write_outputs_publishes_valid_json(tmp_path: Path):
    output_dir = tmp_path / "result"
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )

    write_outputs(output_dir, result, None)

    saved = json.loads((output_dir / "raw_transcription.json").read_text(encoding="utf-8"))
    assert saved == result


def test_write_outputs_publishes_optional_midi(tmp_path: Path):
    output_dir = tmp_path / "result"
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    midi_data = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=0)
    instrument.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
    midi_data.instruments.append(instrument)

    write_outputs(output_dir, result, midi_data)

    saved_midi = pretty_midi.PrettyMIDI(str(output_dir / "transcription.mid"))
    assert len(saved_midi.instruments) == 1
    assert len(saved_midi.instruments[0].notes) == 1


def test_write_outputs_rejects_existing_output_directory(tmp_path: Path):
    output_dir = tmp_path / "result"
    output_dir.mkdir()
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )

    with pytest.raises(OutputError):
        write_outputs(output_dir, result, None)


def test_write_outputs_does_not_publish_invalid_result(tmp_path: Path):
    output_dir = tmp_path / "result"
    result = build_result(
        _prediction(),
        package_version="0.4.0",
        source_commit=SOURCE_COMMIT,
    )
    result["note_events"][0]["offset_sec"] = float("nan")

    with pytest.raises(ResultValidationError):
        write_outputs(output_dir, result, None)

    assert not output_dir.exists()
