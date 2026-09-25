import pytest
from pydantic import ValidationError

from musicsheet_common import (
    ArtifactRef,
    ArtifactRole,
    BeatGrid,
    CleanNoteEvent,
    ConfidenceScores,
    JobProgressEvent,
    JobStatus,
    MeterEvent,
    PedalEvent,
    PipelineStage,
    RawNoteEvent,
    ScoreNote,
    SeparationQuality,
    TempoEvent,
)

# -------------------------------------------------------------
# 1. Job State & Stage Tests
# -------------------------------------------------------------
def test_job_status_and_pipeline_stage_enums():
    """Verify distinct enum definitions for JobStatus and PipelineStage."""
    assert JobStatus.PENDING == "PENDING"
    assert JobStatus.RUNNING == "RUNNING"
    assert JobStatus.CANCEL_REQUESTED == "CANCEL_REQUESTED"
    assert JobStatus.COMPLETED == "COMPLETED"

    assert PipelineStage.DOWNLOAD == "DOWNLOAD"
    assert PipelineStage.SEPARATE == "SEPARATE"
    assert PipelineStage.TRANSCRIBE == "TRANSCRIBE"
    assert PipelineStage.RENDER == "RENDER"

def test_job_progress_event_validation():
    """Verify JobProgressEvent boundaries and required fields."""
    event = JobProgressEvent(
        job_id="job-123",
        status=JobStatus.RUNNING,
        stage=PipelineStage.TRANSCRIBE,
        stage_progress=65,
        overall_progress=50,
        message="Transcribing piano notes...",
    )
    assert event.job_id == "job-123"
    assert event.stage_progress == 65

    # Out of bounds progress
    with pytest.raises(ValidationError):
        JobProgressEvent(
            job_id="job-123",
            status=JobStatus.RUNNING,
            stage=PipelineStage.TRANSCRIBE,
            stage_progress=101,  # Invalid: > 100
            overall_progress=50,
            message="Invalid progress",
        )

# -------------------------------------------------------------
# 2. Artifact Tests
# -------------------------------------------------------------
def test_artifact_ref_validation():
    """Verify ArtifactRef fields, role enum, and sha256 64-char length requirement."""
    valid_sha256 = "a" * 64
    artifact = ArtifactRef(
        id="art-001",
        job_id="job-123",
        role=ArtifactRole.CANONICAL_AUDIO,
        filename="canonical.wav",
        uri="file:///outputs/job-123/canonical.wav",
        mime_type="audio/wav",
        size_bytes=1048576,
        sha256=valid_sha256,
        producer="FFmpegPreprocessor",
        producer_version="6.1.1",
    )
    assert artifact.role == ArtifactRole.CANONICAL_AUDIO
    assert artifact.size_bytes == 1048576

    # Invalid sha256 length
    with pytest.raises(ValidationError):
        ArtifactRef(
            id="art-002",
            job_id="job-123",
            role=ArtifactRole.PDF,
            filename="result.pdf",
            uri="file:///outputs/job-123/result.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            sha256="short_hash",  # Invalid
            producer="MuseScoreRenderer",
            producer_version="4.2",
        )

# -------------------------------------------------------------
# 3. Note Events & 3-Tier Hierarchy Tests
# -------------------------------------------------------------
def test_raw_note_event_duration_and_pitch():
    """Verify RawNoteEvent computes duration_sec dynamically without duplicate source of truth."""
    raw_note = RawNoteEvent(
        note_id="n-001",
        pitch=60,  # Middle C (C4)
        onset_sec=1.50,
        offset_sec=2.25,
        amt_confidence=0.95,
        activation=0.88,
    )
    assert raw_note.duration_sec == pytest.approx(0.75, rel=1e-5)

    # Negative onset
    with pytest.raises(ValidationError):
        RawNoteEvent(
            note_id="n-bad",
            pitch=60,
            onset_sec=-1.0,
            offset_sec=1.0,
            amt_confidence=0.9,
        )

    # Invalid pitch > 127
    with pytest.raises(ValidationError):
        RawNoteEvent(
            note_id="n-bad2",
            pitch=128,
            onset_sec=1.0,
            offset_sec=2.0,
            amt_confidence=0.9,
        )

def test_clean_note_event_and_confidence_scores():
    """Verify CleanNoteEvent confidence scores bound between 0.0 and 1.0."""
    conf = ConfidenceScores(
        amt=0.92,
        separation_quality=0.85,
        rhythm_fit=0.78,
        final=0.86,
    )
    clean_note = CleanNoteEvent(
        note_id="clean-001",
        pitch=64,  # E4
        onset_sec=2.0,
        offset_sec=2.5,
        velocity=85,
        confidence=conf,
        flags=["staccato"],
    )
    assert clean_note.duration_sec == pytest.approx(0.5, rel=1e-5)
    assert clean_note.flags == ["staccato"]

    # Invalid confidence > 1.0
    with pytest.raises(ValidationError):
        ConfidenceScores(amt=1.2, final=1.0)

def test_pedal_event():
    """Verify sustain pedal event and properties."""
    pedal = PedalEvent(
        event_type="sustain",
        onset_sec=1.0,
        offset_sec=3.5,
        value=127,
    )
    assert pedal.duration_sec == pytest.approx(2.5, rel=1e-5)
    assert pedal.event_type == "sustain"

# -------------------------------------------------------------
# 4. Score Model (ScoreNote) Tests
# -------------------------------------------------------------
def test_score_note_rational_representation():
    """Verify ScoreNote uses rational numbers for beat position and duration."""
    score_note = ScoreNote(
        note_id="score-001",
        pitch=67,  # G4
        measure=1,
        beat_numerator=0,
        beat_denominator=1,       # 1st beat of measure
        duration_numerator=1,
        duration_denominator=4,   # Quarter note
        staff=1,                  # Treble
        voice=1,
        hand="right",
        enharmonic_spelling="G4",
    )
    assert score_note.staff == 1
    assert score_note.duration_numerator == 1
    assert score_note.duration_denominator == 4

    # Invalid staff (e.g. staff 3)
    with pytest.raises(ValidationError):
        ScoreNote(
            note_id="score-bad",
            pitch=67,
            measure=1,
            beat_numerator=0,
            beat_denominator=1,
            duration_numerator=1,
            duration_denominator=4,
            staff=3,  # Invalid: staff must be 1 or 2
            voice=1,
        )

# -------------------------------------------------------------
# 5. Beat Grid & Rhythm Tests
# -------------------------------------------------------------
def test_beat_grid_and_tempo_map():
    """Verify BeatGrid can accommodate rubato tempo changes and meter changes."""
    tempo_map = [
        TempoEvent(time_sec=0.0, bpm=120.0),
        TempoEvent(time_sec=10.5, bpm=90.0),  # Ritardando
    ]
    meter_map = [
        MeterEvent(time_sec=0.0, numerator=4, denominator=4),
        MeterEvent(time_sec=15.0, numerator=3, denominator=4),  # Meter change
    ]
    grid = BeatGrid(
        beats=[0.0, 0.5, 1.0, 1.5, 2.0],
        downbeats=[0.0, 2.0],
        tempo_map=tempo_map,
        meter_map=meter_map,
    )
    assert len(grid.tempo_map) == 2
    assert grid.tempo_map[1].bpm == 90.0
    assert grid.meter_map[1].numerator == 3

# -------------------------------------------------------------
# 6. Separation Quality Tests
# -------------------------------------------------------------
def test_separation_quality_and_solo_bypass():
    """Verify SeparationQuality metrics and solo bypass flag."""
    quality = SeparationQuality(
        score=0.91,
        bleed_score=0.05,
        artifact_score=0.04,
        silence_ratio=0.10,
        is_solo_piano=True,
    )
    assert quality.is_solo_piano is True
    assert quality.score == 0.91

    with pytest.raises(ValidationError):
        SeparationQuality(score=1.5)  # Invalid: > 1.0
