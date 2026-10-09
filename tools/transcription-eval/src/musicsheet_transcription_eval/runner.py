"""Owned fresh worker executions with conservative cause attribution."""
import asyncio
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import threading
import time
import uuid
import wave

from musicsheet_pipeline.basic_pitch.io import check_stop, run_owned_io
from musicsheet_pipeline.basic_pitch.process import run_owned_process
from musicsheet_pipeline.providers import PermanentProviderError

from .contracts import Candidate, CANDIDATE_SOURCES, EvaluationLimitError, RunRecord, finite, integer
from .determinism import events_hash
from .manifest import canonical_json, digest_file, regular_file, relative_name, safe_path, strict_json
from .results import normalize_output, read_reference, score_output

REPO = Path(__file__).resolve().parents[4]


def immutable_bytes(path: Path, payload: bytes) -> None:
    """Atomic publication without replacing an existing target, including races."""
    safe_path(path.parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with part.open("xb") as handle: handle.write(payload)
        os.link(part, path)
    finally:
        part.unlink(missing_ok=True)


def candidate_wire(candidate):
    value = asdict(candidate)
    for name in ("python", "checkpoint", "lock"): value[name] = str(value[name])
    return value


async def probe_metadata(kind, python, *, cwd, cancellation):
    package = "basic-pitch" if kind == "basic_pitch" else "piano-transcription-inference"
    asset = "basic_pitch/saved_models/icassp_2022/nmp.onnx" if kind == "basic_pitch" else ""
    code = ("import sys,json,importlib.metadata as m;from pathlib import Path;"
        f"d=m.distribution({package!r});u=json.loads(d.read_text('direct_url.json'));"
        "v=u['vcs_info'];assert v['vcs']=='git';"
        f"print(json.dumps(dict(python_version=list(sys.version_info[:3]),package_version=d.version,"
        f"source_commit=v['commit_id'],source_url=u['url'],asset=str(Path(d.locate_file({asset!r})).absolute()),"
        f"backend_version=m.version({'onnxruntime' if kind == 'basic_pitch' else 'torch'!r}))))")
    probe = await run_owned_process((str(python), "-I", "-c", code), cwd=cwd,
                                    cancellation=cancellation, timeout=30, capture_stdout=True)
    if probe.returncode: raise ValueError("candidate metadata probe failed")
    value = strict_json(probe.stdout)
    expected_url = "https://github.com/spotify/basic-pitch" if kind == "basic_pitch" else "https://github.com/qiuqiangkong/piano_transcription_inference"
    if value["source_url"].removesuffix(".git") != expected_url: raise ValueError("candidate source URL mismatch")
    if kind == "piano_amt" and value["backend_version"] != "2.10.0+cpu": raise ValueError("CPU torch required")
    return value


def runtime_receipt(kind, value):
    runtime = {key: value[key] for key in ("python_version", "package_version", "source_commit", "backend_version")}
    runtime.update(backend="onnx_cpu" if kind == "basic_pitch" else "torch_cpu",
                   threads=None if kind == "basic_pitch" else {"intra": 1, "interop": 1})
    return runtime


async def prepare_candidates(basic_python, piano_python, checkpoint, checkpoint_sha256, *, cwd, cancellation):
    result = []
    for kind, python in (("basic_pitch", basic_python), ("piano_amt", piano_python)):
        python = Path(python); regular_file(python)
        if not python.is_absolute(): raise ValueError("absolute Python path required")
        value = await probe_metadata(kind, python, cwd=cwd, cancellation=cancellation)
        model = Path(value["asset"]) if kind == "basic_pitch" else Path(checkpoint)
        lock = REPO / "services/ml" / ("basic-pitch-worker" if kind == "basic_pitch" else "piano-amt-worker") / "uv.lock"
        def identities(stop):
            if kind == "piano_amt":
                from .checkpoint import _hash_file
                _, digest = _hash_file(model)
                if digest != checkpoint_sha256: raise ValueError("checkpoint SHA mismatch")
            else: digest = digest_file(model, stop=stop)
            return digest, digest_file(lock, stop=stop)
        model_hash, lock_hash = await run_owned_io(identities, cancellation=cancellation)
        runtime = runtime_receipt(kind, value)
        result.append(Candidate(kind, python, "cpu", model, model_hash, lock_hash, value["source_commit"], lock, runtime))
    return tuple(result)


def verify_candidate(candidate: Candidate, stop: threading.Event):
    Candidate(**{**asdict(candidate), "python": candidate.python, "lock": candidate.lock, "checkpoint": candidate.checkpoint})
    regular_file(candidate.python)
    if digest_file(candidate.lock, stop=stop) != candidate.lock_sha256: raise ValueError("lock changed")
    if candidate.id == "piano_amt":
        from .checkpoint import _hash_file
        _, digest = _hash_file(candidate.checkpoint)
    else: digest = digest_file(candidate.checkpoint, stop=stop)
    if digest != candidate.checkpoint_sha256: raise ValueError("checkpoint changed")
    check_stop(stop)


def verify_slot_input(candidate, entry, stop):
    verify_candidate(candidate, stop)
    audio = entry.basic_audio if candidate.id == "basic_pitch" else entry.piano_audio
    expected = entry.basic_audio_sha256 if candidate.id == "basic_pitch" else entry.piano_audio_sha256
    rate = 22050 if candidate.id == "basic_pitch" else 16000
    regular_file(audio, maximum=30 * rate * 2 + 4096)
    with wave.open(str(audio), "rb") as incoming:
        if (incoming.getnchannels(), incoming.getsampwidth(), incoming.getframerate(), incoming.getnframes(), incoming.getcomptype()) != (1, 2, rate, 30 * rate, "NONE"):
            raise ValueError("candidate audio mismatch")
        if len(incoming.readframes(30 * rate + 1)) != 30 * rate * 2: raise ValueError("incomplete PCM")
    if digest_file(audio, stop=stop) != expected: raise ValueError("input hash mismatch")
    read_reference(entry, stop=stop)
    return audio, expected


def worker_argv(candidate, audio, output):
    module = "musicsheet_basic_pitch_worker.cli" if candidate.id == "basic_pitch" else "musicsheet_piano_amt_worker.cli"
    args = [str(candidate.python), "-I", "-c", f"import sys;from {module} import main;sys.exit(main(sys.argv[1:]))",
            "--input-audio", str(audio), "--output-dir", str(output)]
    if candidate.id == "piano_amt":
        args.extend(("--checkpoint", str(candidate.checkpoint), "--checkpoint-sha256", candidate.checkpoint_sha256, "--device", "cpu"))
    return tuple(args)


async def run_slot(candidate, entry, *, repeat, slot_id, run_root, cancellation, timeout_sec=300, diagnostic_for=None):
    integer(repeat, 0, 2); finite(timeout_sec, 0, 300)
    if timeout_sec == 0: raise ValueError("positive slot timeout required")
    relative_name(slot_id)
    cwd = safe_path(run_root, "slots/" + slot_id)
    if cwd.exists(): raise ValueError("existing slot refused")
    output = cwd / "output"
    started, clock, elapsed, exit_code = False, None, None, None
    evidence, files, phase = (), {}, "setup"
    def record(status, attribution, error_code, *, digest=None, metrics=None):
        duration = elapsed if elapsed is not None else (time.monotonic() - clock if clock is not None else None)
        return RunRecord(slot_id, entry.recording_id, candidate.id, repeat, diagnostic_for, status, attribution,
            error_code, duration, digest, output if started else None, started, exit_code, evidence, files, metrics)
    try:
        value = await probe_metadata(candidate.id, candidate.python, cwd=run_root, cancellation=cancellation)
        if runtime_receipt(candidate.id, value) != candidate.runtime or (
            candidate.id == "basic_pitch" and Path(value["asset"]) != candidate.checkpoint):
            raise ValueError("installed candidate changed")
        audio, input_hash = await run_owned_io(lambda stop: verify_slot_input(candidate, entry, stop), cancellation=cancellation)
        cwd.mkdir(parents=True)
        start = dict(slot_id=slot_id, recording_id=entry.recording_id, candidate_id=candidate.id,
                     repeat=repeat, diagnostic_for=diagnostic_for)
        immutable_bytes(safe_path(run_root, "starts/" + slot_id + ".json"), canonical_json(start))
        evidence = ("input_verified", "environment_verified")
        started, clock = True, time.monotonic()
        phase = "output"
        async with asyncio.timeout(timeout_sec):
            process = await run_owned_process(worker_argv(candidate, audio, output), cwd=cwd,
                                              cancellation=cancellation, timeout=timeout_sec)
            exit_code = process.returncode
            evidence += ("owned_process_cleaned",)
            if exit_code != 0:
                evidence += ("cause_unavailable",)
                if exit_code == 2: return record("setup_failed", "infrastructure", "worker_exit_2")
                if exit_code == 3: return record("model_error", "unresolved", "worker_exit_3")
                if exit_code == 4: return record("output_invalid", "unresolved", "worker_exit_4")
                return record("model_error", "unresolved", "worker_exit_unknown")
            def validate(stop):
                events = normalize_output(candidate, output, input_sha256=input_hash, stop=stop)
                digest = events_hash(events)
                normalized = cwd / "events.json"
                check_stop(stop); immutable_bytes(normalized, canonical_json(asdict(events)))
                artifacts = {path.relative_to(run_root).as_posix(): digest_file(path, stop=stop)
                             for path in (output / "raw_transcription.json", output / "transcription.mid", normalized)}
                return events, digest, artifacts
            events, digest, files = await run_owned_io(validate, cancellation=cancellation)
        elapsed = time.monotonic() - clock
        phase = "metric"
        metrics = await run_owned_io(lambda stop: score_output(entry, events, stop=stop), cancellation=cancellation)
        if cancellation.is_set(): raise asyncio.CancelledError
        return record("success", None, None, digest=digest, metrics=metrics)
    except asyncio.CancelledError:
        return record("cancelled", "infrastructure", "cancelled")
    except TimeoutError:
        return record("timeout", "unresolved", "slot_timeout")
    except EvaluationLimitError:
        return record("output_invalid" if started else "setup_failed", "infrastructure", "evaluation_limit")
    except (PermissionError, PermanentProviderError, OSError):
        return record("setup_failed", "infrastructure", "runner_failure" if started else "setup_invalid")
    except Exception:
        if phase == "metric": return record("setup_failed", "infrastructure", "runner_failure")
        return record("output_invalid", "unresolved", "output_invalid") if started else record("setup_failed", "infrastructure", "setup_invalid")
