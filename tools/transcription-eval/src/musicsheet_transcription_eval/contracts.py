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


CANDIDATE_SOURCES = {"basic_pitch": "049dc8a01a170c2370d7b246ec1c2067e060c3bf",
                     "piano_amt": "0226e74cbc805660e34bbd6a8fed2083890ebb88"}
CANDIDATE_VERSIONS = {"basic_pitch": "0.4.0", "piano_amt": "0.0.6"}


@dataclass(frozen=True)
class Candidate:
    id: str
    python: Path
    device: str
    checkpoint: Path
    checkpoint_sha256: str
    lock_sha256: str
    source_commit: str
    lock: Path
    runtime: dict

    def __post_init__(self):
        if self.id not in CANDIDATE_SOURCES or self.device != "cpu" or self.source_commit != CANDIDATE_SOURCES[self.id]:
            raise ValueError("invalid candidate identity")
        for path in (self.python, self.checkpoint, self.lock):
            if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
                raise ValueError("absolute candidate path required")
        hash_value(self.checkpoint_sha256); hash_value(self.lock_sha256)
        runtime = self.runtime
        if type(runtime) is not dict or set(runtime) != {"python_version", "package_version", "source_commit", "backend", "backend_version", "threads"}:
            raise ValueError("invalid runtime receipt")
        if type(runtime["backend_version"]) is not str or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:\+[a-z0-9.]+)?", runtime["backend_version"]) is None:
            raise ValueError("invalid backend version")
        if self.id == "piano_amt" and runtime["backend_version"] != "2.10.0+cpu": raise ValueError("CPU torch required")
        version = runtime["python_version"]
        if type(version) is not list or len(version) != 3 or any(type(n) is not int or n < 0 for n in version) or version[:2] != [3, 12]:
            raise ValueError("candidate Python 3.12 required")
        if runtime["package_version"] != CANDIDATE_VERSIONS[self.id] or runtime["source_commit"] != self.source_commit:
            raise ValueError("candidate runtime mismatch")
        expected_backend = "onnx_cpu" if self.id == "basic_pitch" else "torch_cpu"
        expected_threads = None if self.id == "basic_pitch" else {"intra": 1, "interop": 1}
        if runtime["backend"] != expected_backend or runtime["threads"] != expected_threads or (
            expected_threads is not None and any(type(v) is not int for v in runtime["threads"].values())
        ):
            raise ValueError("invalid CPU runtime")


STATUSES = {"success", "model_error", "timeout", "output_invalid", "setup_failed", "cancelled", "not_run", "interrupted"}
ERROR_CODES = {"worker_exit_2", "worker_exit_3", "worker_exit_4", "worker_exit_unknown", "output_invalid",
               "slot_timeout", "setup_invalid", "runner_failure", "evaluation_limit", "cancelled", "budget_stop",
               "preflight_failure", "budget_preflight_failure", "interrupted", "verified_model_prediction",
               "verified_model_inference"}
EVIDENCE_CODES = {"input_verified", "environment_verified", "owned_process_cleaned", "cause_unavailable",
                  "model_cause_verified", "cause_native_prediction", "cause_inference_exception", "synthetic_evidence"}


def validate_metrics(value):
    """Validate both native asdict output and JSON-reloaded success metrics."""
    def fields(item, names):
        if type(item) is not dict or set(item) != set(names): raise ValueError("invalid metric fields")
    def sequence(item):
        if type(item) not in (tuple, list): raise ValueError("invalid metric sequence")
        return item
    fields(value, ("onset", "key_release", "sustain", "velocity", "censored"))
    metrics = {}
    for name in ("onset", "key_release", "sustain"):
        fields(value[name], Metric.__dataclass_fields__); metrics[name] = Metric(**value[name])
    onset = metrics["onset"]
    if any(m.tp + m.fp != onset.tp + onset.fp for m in metrics.values()) or (
        metrics["key_release"].tp + metrics["key_release"].fn != onset.tp + onset.fn):
        raise ValueError("inconsistent metric populations")
    velocity = value["velocity"]; fields(velocity, VelocityMatch.__dataclass_fields__)
    arrays = {}
    for name in ("reference_sorted", "prediction_sorted"):
        notes = []
        for note in sequence(velocity[name]):
            fields(note, Note.__dataclass_fields__); event = Note(**note)
            if not 2 <= event.onset < 28 or event.offset > 30: raise ValueError("invalid scoring note")
            notes.append(event)
        key = lambda n: (n.pitch, n.onset, n.offset, n.velocity is not None, n.velocity or 0.0)
        if notes != sorted(notes, key=key): raise ValueError("unsorted velocity input")
        arrays[name] = tuple(notes)
    pairs = tuple(tuple(sequence(pair)) for pair in sequence(velocity["pairs"]))
    match = VelocityMatch(velocity["mae"], pairs, **arrays)
    if len(match.pairs) != onset.tp or len(match.reference_sorted) != onset.tp + onset.fn or len(match.prediction_sorted) != onset.tp + onset.fp:
        raise ValueError("inconsistent velocity populations")
    censored = value["censored"]; fields(censored, ("reference_key_release", "reference_sustain", "predicted"))
    integer(censored["predicted"], 0, onset.tp + onset.fp)
    for name in ("key_release", "sustain"):
        integer(censored["reference_" + name], 0, metrics[name].tp + metrics[name].fn)


@dataclass(frozen=True)
class RunRecord:
    slot_id: str
    recording_id: str
    candidate_id: str
    repeat: int
    diagnostic_for: str | None
    status: str
    attribution: str | None
    error_code: str | None
    elapsed_sec: float | None
    events_sha256: str | None
    output_dir: Path | None
    started: bool = False
    exit_code: int | None = None
    evidence: tuple[str, ...] = ()
    files: dict[str, str] | None = None
    metrics: dict | None = None

    def __post_init__(self):
        for identity in (self.slot_id, self.diagnostic_for):
            if identity is not None and (type(identity) is not str or re.fullmatch(r"[a-z0-9_-]{1,160}", identity) is None):
                raise ValueError("invalid slot identity")
        hash_value(self.recording_id); integer(self.repeat, 0, 2)
        if self.candidate_id not in CANDIDATE_SOURCES or self.status not in STATUSES or self.attribution not in {None, "model", "infrastructure", "unresolved"}:
            raise ValueError("invalid run classification")
        if type(self.started) is not bool or self.error_code is not None and self.error_code not in ERROR_CODES:
            raise ValueError("invalid run evidence")
        if type(self.evidence) is not tuple or any(code not in EVIDENCE_CODES for code in self.evidence):
            raise ValueError("invalid evidence code")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise ValueError("invalid exit code")
        if self.elapsed_sec is not None: finite(self.elapsed_sec)
        if self.events_sha256 is not None: hash_value(self.events_sha256)
        if self.output_dir is not None and (not isinstance(self.output_dir, Path) or not self.output_dir.is_absolute()):
            raise ValueError("invalid output path")
        if self.status == "success" and (not self.started or self.attribution is not None or self.error_code is not None or
                self.elapsed_sec is None or self.events_sha256 is None or self.output_dir is None or self.exit_code != 0):
            raise ValueError("incomplete success record")
        if self.status == "success": validate_metrics(self.metrics)
        if self.status != "success" and (self.attribution is None or self.error_code is None or self.events_sha256 is not None or self.metrics is not None):
            raise ValueError("invalid failure record")
        if self.status == "not_run" and (self.started or self.elapsed_sec is not None or self.output_dir is not None):
            raise ValueError("invalid unstarted record")
        if self.attribution == "model" and ("model_cause_verified" not in self.evidence or
                self.error_code not in {"verified_model_prediction", "verified_model_inference"}):
            raise ValueError("primitive model cause required")
        if self.files is not None:
            if type(self.files) is not dict: raise ValueError("invalid artifact hashes")
            for name, digest in self.files.items():
                if type(name) is not str or not name: raise ValueError("invalid artifact path")
                hash_value(digest)
