"""Strict immutable metric inputs, separate from product schemas."""

from dataclasses import dataclass
import math
from pathlib import Path
import re


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


def hash_value(value: object) -> None:
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA256")


@dataclass(frozen=True)
class AudioPreparationReceipt:
    source_crop_sha256: str
    mono_sha256: str
    source_rate: int
    source_frames: int
    start_frame: int
    basic_frames: int
    piano_frames: int
    ffmpeg_version: str
    argv: tuple[tuple[str, ...], ...]
    pcm_revision: str
    elapsed_sec: float

    def __post_init__(self):
        hash_value(self.source_crop_sha256)
        hash_value(self.mono_sha256)
        integer(self.source_rate, 1)
        integer(self.source_frames, 1)
        integer(self.start_frame, 0)
        integer(self.basic_frames, 1)
        integer(self.piano_frames, 1)
        if self.source_frames != 30 * self.source_rate or self.start_frame % self.source_rate or self.basic_frames != 661500 or self.piano_frames != 480000:
            raise ValueError("invalid crop/frame receipt")
        if type(self.ffmpeg_version) is not str or not self.ffmpeg_version.startswith("ffmpeg version "):
            raise ValueError("missing FFmpeg version")
        if type(self.argv) is not tuple or len(self.argv) != 2 or any(type(args) is not tuple or not args or any(type(arg) is not str or not arg or "\0" in arg for arg in args) for args in self.argv):
            raise ValueError("invalid FFmpeg argv")
        if self.pcm_revision != "w05-pcm-r2":
            raise ValueError("invalid PCM revision")
        finite(self.elapsed_sec)


@dataclass(frozen=True)
class PreparedAudio:
    basic_audio: Path
    piano_audio: Path
    receipt: AudioPreparationReceipt

    def __post_init__(self):
        if not isinstance(self.basic_audio, Path) or not isinstance(self.piano_audio, Path) or type(self.receipt) is not AudioPreparationReceipt:
            raise ValueError("invalid prepared audio")


@dataclass(frozen=True)
class ManifestEntry:
    recording_id: str
    audio_filename: str
    midi_filename: str
    start_sec: int
    source_audio_sha256: str
    source_midi_sha256: str
    basic_audio: Path
    piano_audio: Path
    basic_audio_sha256: str
    piano_audio_sha256: str
    reference_path: Path
    reference_sha256: str
    audio_receipt: AudioPreparationReceipt
    audio_receipt_sha256: str

    def __post_init__(self):
        hash_value(self.recording_id)
        integer(self.start_sec, 0)
        for value in (self.source_audio_sha256, self.source_midi_sha256, self.basic_audio_sha256, self.piano_audio_sha256, self.reference_sha256, self.audio_receipt_sha256):
            hash_value(value)
        if any(not isinstance(path, Path) for path in (self.basic_audio, self.piano_audio, self.reference_path)) or type(self.audio_receipt) is not AudioPreparationReceipt:
            raise ValueError("invalid manifest entry")
        if self.audio_receipt.start_frame != self.start_sec * self.audio_receipt.source_rate:
            raise ValueError("inconsistent crop receipt")


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    selection_revision: str
    entries: tuple[ManifestEntry, ...]
    metadata_hashes: dict[str, str]
    source_receipt: dict[str, object]

    def __post_init__(self):
        integer(self.schema_version, 1, 1)
        if self.selection_revision != "w05-r1-selection-r2-crop" or type(self.entries) is not tuple or len(self.entries) != 12 or any(type(entry) is not ManifestEntry for entry in self.entries):
            raise ValueError("invalid manifest version/entries")
        if len({entry.recording_id for entry in self.entries}) != 12:
            raise ValueError("duplicate recording")
        if type(self.metadata_hashes) is not dict or set(self.metadata_hashes) != {"v3", "v2"}:
            raise ValueError("invalid metadata hashes")
        for value in self.metadata_hashes.values(): hash_value(value)
        if type(self.source_receipt) is not dict:
            raise ValueError("missing source receipt")
