import math

import pytest

from musicsheet_basic_pitch_worker.mapping import map_note_events


def test_maps_activation_and_uncalibrated_confidence():
    mapped = map_note_events([(0.25, 1.5, 60, 0.82, [0, 1])])

    assert mapped == [
        {
            "note_id": "bp-000001",
            "pitch": 60,
            "onset_sec": 0.25,
            "offset_sec": 1.5,
            "activation": 0.82,
            "velocity_prediction": None,
            "amt_confidence": 0.82,
            "source_chunk": None,
        }
    ]


@pytest.mark.parametrize(
    "note_event",
    [
        (-0.1, 1.0, 60, 0.5, []),
        (1.0, 0.5, 60, 0.5, []),
        (0.0, math.nan, 60, 0.5, []),
        (10**400, 10**400, 60, 0.5, []),
        (0.0, 1.0, 60, 10**400, []),
        (0.0, 1.0, -1, 0.5, []),
        (0.0, 1.0, 128, 0.5, []),
        (0.0, 1.0, 60, -0.1, []),
        (0.0, 1.0, 60, 1.1, []),
        (0.0, 1.0, True, 0.5, []),
    ],
)
def test_mapping_rejects_invalid_note_values(note_event):
    with pytest.raises(ValueError):
        map_note_events([note_event])


def test_mapping_generates_stable_ids():
    note_events = [
        (0.0, 0.5, 60, 0.4, []),
        (0.5, 1.0, 64, 0.7, []),
    ]

    mapped = map_note_events(note_events)

    assert [event["note_id"] for event in mapped] == ["bp-000001", "bp-000002"]
