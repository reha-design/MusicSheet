"""Lazy CPU model boundary; safe state validation precedes upstream construction."""

from collections import OrderedDict
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from numbers import Real
from pathlib import Path
from types import SimpleNamespace

from .audio import validate_input_audio
from .output import OutputValidationError, validate_prediction
from .provenance import OPTIONS, validate_checkpoint, validate_installed_source


def _load_backend():
    validate_installed_source()
    import numpy
    import torch
    from piano_transcription_inference import PianoTranscription
    from piano_transcription_inference.models import Note_pedal
    if torch.__version__ != "2.10.0+cpu" or torch.version.cuda is not None:
        raise ValueError("pinned CPU torch required")
    return SimpleNamespace(torch=torch, numpy=numpy, model=Note_pedal, transcriber=PianoTranscription)


def _validate_state(backend, checkpoint: Path) -> None:
    torch = backend.torch
    state = torch.load(str(checkpoint), map_location="cpu", weights_only=True)
    if type(state) is not dict or type(state.get("model")) not in {dict, OrderedDict}:
        raise ValueError("invalid checkpoint state")
    groups = state["model"]
    if set(groups) != {"note_model", "pedal_model"}:
        raise ValueError("checkpoint groups mismatch")
    actual = {}
    for name, group in groups.items():
        if type(group) not in {dict, OrderedDict} or any(type(key) is not str for key in group):
            raise ValueError("invalid checkpoint group")
        actual.update({f"{name}.{key}": value for key, value in group.items()})
    expected = backend.model(frames_per_second=100, classes_num=88).state_dict()
    if actual.keys() != expected.keys():
        raise ValueError("checkpoint keys mismatch")
    for key, template in expected.items():
        tensor = actual[key]
        if (not isinstance(tensor, torch.Tensor) or tensor.shape != template.shape
            or tensor.dtype != template.dtype or tensor.dtype not in {torch.float32, torch.int64}
            or not torch.isfinite(tensor).all().item()):
            raise ValueError("checkpoint tensor mismatch")


def _timestamp(value) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise OutputValidationError("invalid raw timestamp type")
    try:
        return float(value)
    except OverflowError:
        raise OutputValidationError("invalid raw timestamp") from None


def run_prediction(audio_path: Path, *, checkpoint: Path, device: str) -> dict:
    if device != "cpu":
        raise ValueError("CPU device required")
    validate_checkpoint(checkpoint)
    audio = validate_input_audio(audio_path)
    backend = _load_backend()
    torch = backend.torch
    if torch.get_num_threads() != 1:
        torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        _validate_state(backend, checkpoint)
        # No default checkpoint path; the official size/hash has already passed.
        transcriber = backend.transcriber(model_type="Note_pedal", checkpoint_path=str(checkpoint),
            segment_samples=OPTIONS["segment_samples"], device="cpu")
        defaults = {"onset_threshold": transcriber.onset_threshold,
            "offset_threshold": transcriber.offset_threshod,
            "frame_threshold": transcriber.frame_threshold,
            "pedal_offset_threshold": transcriber.pedal_offset_threshold}
        if any(defaults[key] != OPTIONS[key] for key in defaults):
            raise ValueError("upstream default threshold mismatch")
        samples = backend.numpy.frombuffer(audio.pcm, dtype="<i2").astype(backend.numpy.float32) / 32768
        with torch.inference_mode():
            result = transcriber.transcribe(samples, midi_path=None)
    try:
        notes = [{"pitch": item["midi_note"], "onset": _timestamp(item["onset_time"]),
            "offset": _timestamp(item["offset_time"]), "velocity": item["velocity"]}
            for item in result["est_note_events"]]
        pedals = [{"kind": "sustain", "onset": _timestamp(item["onset_time"]),
            "offset": _timestamp(item["offset_time"]), "value": 127}
            for item in (result["est_pedal_events"] or [])]
    except (KeyError, TypeError, OverflowError):
        raise OutputValidationError("invalid native model events") from None
    prediction = {"duration_sec": audio.duration_sec, "notes": notes, "pedals": pedals,
        "runtime": {"torch_num_threads": torch.get_num_threads(),
                    "torch_num_interop_threads": torch.get_num_interop_threads()}}
    validate_prediction(prediction)
    return prediction
