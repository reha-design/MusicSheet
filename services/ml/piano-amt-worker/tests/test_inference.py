from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def backend(monkeypatch):
    from musicsheet_piano_amt_worker import inference
    calls = []

    class Tensor:
        shape = (2,)
        dtype = "float32"
        finite = True

    class Model:
        def __init__(self, **kwargs):
            assert kwargs == dict(frames_per_second=100, classes_num=88)
        def state_dict(self):
            return {"note_model.weight": Tensor(), "pedal_model.weight": Tensor()}

    state = {"model": {"note_model":{"weight":Tensor()}, "pedal_model":{"weight":Tensor()}}}

    class Torch:
        float32 = "float32"
        int64 = "int64"
        def load(self, path, **kwargs):
            calls.append(("load", kwargs))
            return state
        def get_num_threads(self): return 1
        def get_num_interop_threads(self): return 1
        def inference_mode(self): return nullcontext()
        def isfinite(self, tensor):
            return SimpleNamespace(all=lambda: SimpleNamespace(item=lambda: tensor.finite))
    torch = Torch()
    torch.Tensor = Tensor

    class Transcriber:
        onset_threshold = .3
        offset_threshod = .3
        frame_threshold = .1
        pedal_offset_threshold = .2
        raw_note = {"midi_note":60,"onset_time":np.float64(.01),"offset_time":np.float64(.08),"velocity":80}
        def __init__(self, **kwargs):
            calls.append(("constructor", kwargs))
        def transcribe(self, samples, midi_path):
            assert samples.dtype == np.float32 and samples.ndim == 1
            assert midi_path is None
            calls.append(("transcribe", len(samples)))
            return {"est_note_events": [self.raw_note], "est_pedal_events": None}

    monkeypatch.setattr(inference, "_load_backend", lambda: SimpleNamespace(
        torch=torch, numpy=np, model=Model, transcriber=Transcriber))
    return calls, state, Transcriber


def test_safe_weights_and_shapes_precede_fixed_cpu_constructor(audio, checkpoint, backend):
    from musicsheet_piano_amt_worker.inference import run_prediction
    calls, _, _ = backend
    result = run_prediction(audio(), checkpoint=checkpoint[0], device="cpu")
    assert calls[0] == ("load", {"map_location":"cpu", "weights_only":True})
    assert calls[1][0] == "constructor"
    assert calls[1][1] == dict(model_type="Note_pedal",checkpoint_path=str(checkpoint[0]),
        segment_samples=160000,device="cpu")
    assert result["notes"] == [dict(pitch=60,onset=.01,offset=.08,velocity=80)]
    assert result["pedals"] == [] and result["duration_sec"] == .1


@pytest.mark.parametrize("case", ["missing", "extra", "shape", "dtype", "missing_group",
    "extra_group", "malformed_group", "nonstring_key", "non_tensor", "nan", "inf"])
def test_checkpoint_state_mismatch_rejected_before_constructor(audio,checkpoint,backend,case):
    from musicsheet_piano_amt_worker.inference import run_prediction
    calls, state, _ = backend
    group = state["model"]["note_model"]
    if case == "missing": group.clear()
    elif case == "extra": group["unknown"] = group["weight"]
    elif case == "shape": group["weight"].shape = (3,)
    elif case == "dtype": group["weight"].dtype = "float64"
    elif case == "missing_group": del state["model"]["pedal_model"]
    elif case == "extra_group": state["model"]["unknown"] = {}
    elif case == "malformed_group": state["model"]["note_model"] = []
    elif case == "nonstring_key": group[1] = group.pop("weight")
    elif case == "non_tensor": group["weight"] = 1
    else: group["weight"].finite = False
    with pytest.raises(ValueError): run_prediction(audio(),checkpoint=checkpoint[0],device="cpu")
    assert not any(c[0] == "constructor" for c in calls)


def test_unexpected_threshold_does_not_run_transcription(audio,checkpoint,backend):
    from musicsheet_piano_amt_worker.inference import run_prediction
    calls, _, transcriber = backend
    transcriber.onset_threshold = .5
    with pytest.raises(ValueError): run_prediction(audio(),checkpoint=checkpoint[0],device="cpu")
    assert not any(c[0] == "transcribe" for c in calls)


def test_cuda_refused_before_backend_import(audio,checkpoint,monkeypatch):
    from musicsheet_piano_amt_worker import inference
    monkeypatch.setattr(inference,"_load_backend",lambda: pytest.fail("CUDA imported model"))
    with pytest.raises(ValueError): inference.run_prediction(audio(),checkpoint=checkpoint[0],device="cuda")


@pytest.mark.parametrize("field,value", [("onset_time",False),("offset_time",True),("onset_time","0.01")])
def test_raw_timestamp_types_not_coerced_to_valid_numbers(audio,checkpoint,backend,field,value):
    from musicsheet_piano_amt_worker.inference import run_prediction
    backend[2].raw_note = dict(backend[2].raw_note, **{field:value})
    with pytest.raises(ValueError): run_prediction(audio(),checkpoint=checkpoint[0],device="cpu")


def test_source_receipt_rejects_another_git_commit(monkeypatch):
    from musicsheet_piano_amt_worker import provenance
    import json
    fake = SimpleNamespace(read_text=lambda name: json.dumps({"url":provenance.SOURCE_URL,
        "vcs_info":{"vcs":"git","commit_id":"0"*40}}))
    monkeypatch.setattr(provenance.metadata,"distribution",lambda name: fake)
    monkeypatch.setattr(provenance.metadata,"version",lambda name: "0.0.6")
    with pytest.raises(ValueError): provenance.validate_installed_source()
