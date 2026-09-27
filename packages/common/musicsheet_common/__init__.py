"""MusicSheet Common Package.

Core domain models, schemas, and contracts.
"""

from musicsheet_common.schemas import (
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
    ProviderMetadata,
    RawNoteEvent,
    ScoreNote,
    SeparationQuality,
    TempoEvent,
    TranscriptionResult,
)

__version__ = "0.1.0"

__all__ = [
    "ArtifactRef",
    "ArtifactRole",
    "BeatGrid",
    "CleanNoteEvent",
    "ConfidenceScores",
    "JobProgressEvent",
    "JobStatus",
    "MeterEvent",
    "PedalEvent",
    "PipelineStage",
    "ProviderMetadata",
    "RawNoteEvent",
    "ScoreNote",
    "SeparationQuality",
    "TempoEvent",
    "TranscriptionResult",
]
