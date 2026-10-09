"""Serial schedules, immutable ledgers and reproducible session summaries."""
import asyncio
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
import platform
import statistics
import time
import wave

from musicsheet_pipeline.basic_pitch.io import run_owned_io

from .contracts import AudioPreparationReceipt, Candidate, Manifest, ManifestEntry, Metric, RunRecord, validate_metrics
from .manifest import canonical_json, digest_file, load_manifest, regular_file, safe_path
from .metrics import aggregate
from .results import read_reference
from .runner import REPO, candidate_wire, immutable_bytes, run_slot
from .selection import select_model

SESSION_SECONDS = 7200
RAW_JSON_LIMIT = 8 * 1024 * 1024
RAW_MIDI_LIMIT = 16 * 1024 * 1024
CC0_SHA = "2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a"
GATE_CODES = {"cancelled", "setup_invalid", "preflight_failure", "budget_preflight_failure", "budget_stop", "evaluation_limit"}


def build_schedule(manifest, candidates):
    if type(manifest) is not Manifest or len(candidates) != 2 or {c.id for c in candidates} != {"basic_pitch", "piano_amt"}:
        raise ValueError("two fixed CPU candidates required")
    ordered = sorted(candidates, key=lambda c: c.id)
    schedule = []
    for repeat in range(3):
        entries = tuple(enumerate(manifest.entries))
        if repeat == 1: entries = tuple(reversed(entries))
        for index, entry in entries:
            for candidate in reversed(ordered) if repeat == 1 else ordered:
                schedule.append(dict(slot_id=f"r{repeat}-{index:03}-{candidate.id}", recording_id=entry.recording_id,
                    candidate_id=candidate.id, repeat=repeat, diagnostic_for=None))
    return tuple(schedule)


def reproducible_failures(records):
    grouped = defaultdict(list)
    for record in records:
        if record.attribution == "model" and "model_cause_verified" in record.evidence:
            grouped[(record.candidate_id, record.recording_id, record.error_code)].append(record.slot_id)
    return [dict(candidate_id=key[0], recording_id=key[1], primitive_cause=key[2], slots=sorted(set(slots)))
            for key, slots in sorted(grouped.items()) if len(set(slots)) >= 2]


def build_summary(header, records, gates):
    if type(gates) is not list or any(code not in GATE_CODES for code in gates): raise ValueError("invalid gate code")
    for record in records:
        if record.status == "success": validate_metrics(record.metrics)
    models = {}
    original = [r for r in records if r.diagnostic_for is None]
    reproduced = reproducible_failures(records)
    for candidate in header["candidates"]:
        kind = candidate["id"]
        own = [r for r in original if r.candidate_id == kind]
        all_own = [r for r in records if r.candidate_id == kind]
        first, determinism = {}, {}
        for identity in header["recording_ids"]:
            accuracy = [r for r in own if r.recording_id == identity and r.repeat == 0]
            if len(accuracy) != 1: raise ValueError("incomplete or duplicate accuracy ledger")
            first[identity] = accuracy[0].metrics if accuracy[0].status == "success" else None
            successes = [r for r in all_own if r.recording_id == identity and r.status == "success"]
            hashes = [r.events_sha256 for r in successes]
            status = "nondeterministic_output" if len(set(hashes)) > 1 else "deterministic_observed" if len(hashes) >= 3 else "determinism_incomplete"
            f1 = [r.metrics["onset"]["f1"] for r in successes if r.metrics["onset"]["f1"] is not None]
            determinism[identity] = dict(status=status, hashes=hashes, f1_range=[min(f1), max(f1)] if f1 else None)
        started = [r for r in own if r.started]
        succeeded = [r for r in started if r.status == "success"]
        model_only = [r for r in started if r.status == "success" or r.attribution == "model"]
        model_failures = sum(r.status != "success" for r in model_only)
        elapsed = [r.elapsed_sec for r in succeeded]
        counts = Counter(r.status for r in own)
        reliability = dict(scheduled=36, started=len(started), success=len(succeeded), status_counts=dict(sorted(counts.items())),
            not_run=counts["not_run"], raw_failure_rate=(len(started)-len(succeeded))/len(started) if started else None,
            model_only_denominator=len(model_only), model_only_failures=model_failures,
            model_only_failure_rate=model_failures/len(model_only) if model_only else None,
            excluded_infrastructure=sum(r.attribution=="infrastructure" for r in started),
            excluded_unresolved=sum(r.attribution=="unresolved" for r in started))
        aggregates = {}
        for name in ("onset", "sustain", "key_release"):
            metrics = [Metric(**value[name]) for value in first.values() if value is not None]
            value = aggregate(metrics); value["micro"] = asdict(value["micro"])
            value["successful_first_runs"] = len(metrics); aggregates[name] = value
        references = header["reference_counts"]
        operational_recall = {}
        for name in ("key_release", "sustain"):
            known = all(references[key][name] is not None for key in header["recording_ids"])
            denominator = sum(references[key][name] for key in header["recording_ids"]) if known else None
            numerator = sum(value[name]["tp"] for value in first.values() if value is not None)
            operational_recall[name] = dict(tp=numerator, planned_reference_notes=denominator,
                recall=numerator/denominator if denominator else None)
        models[kind] = dict(first_runs=first, determinism=determinism, elapsed_sec=elapsed,
            not_run=counts["not_run"], operationally_ineligible=any(r["candidate_id"]==kind for r in reproduced),
            unresolved_failures=sum(r.attribution=="unresolved" for r in all_own), reliability=reliability,
            aggregates=aggregates, operational_recall=operational_recall,
            cpu=dict(n=len(elapsed),median_sec=statistics.median(elapsed) if elapsed else None,
                p95_sec=sorted(elapsed)[math.ceil(.95*len(elapsed))-1] if elapsed else None,
                rtf=[value/30 for value in elapsed]),
            reproducible_failures=[r for r in reproduced if r["candidate_id"]==kind])
    summary = dict(schema_version=1, gates=sorted(set(gates)), models=models,
                   diagnostic_count=sum(r.diagnostic_for is not None for r in records))
    summary["decision"] = select_model(summary)
    return summary


async def verify_session_inputs(manifest, candidates, *, manifest_path, input_root, cancellation):
    def verify(stop):
        loaded = load_manifest(manifest_path, run_root=input_root, stop=stop)
        if loaded != manifest: raise ValueError("manifest changed before session")
        return dict(manifest_sha256=digest_file(manifest_path, stop=stop),
                    payload_sha256=hashlib.sha256(canonical_json(__import__('json').loads(manifest_path.read_bytes())["manifest"])).hexdigest())
    return await run_owned_io(verify, cancellation=cancellation)


async def prepare_preflight(*, ffmpeg, run_root, cancellation):
    from .audio import prepare_audio
    import numpy as np
    source = REPO / "tests/fixtures/audio/basic_pitch_smoke.wav"
    directory = safe_path(run_root, "preflight-input")
    directory.mkdir()
    repeated = directory / "repeated-stereo.wav"
    def repeat_audio(stop):
        if digest_file(source, stop=stop) != CC0_SHA: raise ValueError("CC0 fixture changed")
        with wave.open(str(source), "rb") as incoming:
            if (incoming.getnchannels(), incoming.getsampwidth(), incoming.getframerate(), incoming.getnframes()) != (1, 2, 22050, 352800):
                raise ValueError("invalid CC0 source")
            pcm = incoming.readframes(incoming.getnframes())
        mono = (pcm * 2)[:30*22050*2]
        stereo = np.repeat(np.frombuffer(mono, dtype="<i2"), 2).astype("<i2").tobytes()
        with wave.open(str(repeated), "wb") as outgoing:
            outgoing.setparams((2, 2, 22050, 0, "NONE", "not compressed")); outgoing.writeframes(stereo)
        return digest_file(repeated, stop=stop)
    source_hash = await run_owned_io(repeat_audio, cancellation=cancellation)
    prepared = await prepare_audio(repeated, start_sec=0, destination=directory/"prepared", ffmpeg=ffmpeg, cancellation=cancellation)
    reference = directory / "reference.json"
    empty = dict(events=dict(notes=[], pedals=[]), censored_count=0)
    immutable_bytes(reference, canonical_json(dict(key_release=empty, sustain=empty)))
    def finish(stop):
        return tuple(digest_file(path, stop=stop) for path in (prepared.basic_audio, prepared.piano_audio, reference))
    basic_hash, piano_hash, ref_hash = await run_owned_io(finish, cancellation=cancellation)
    item = ManifestEntry(hashlib.sha256(b"W05-CC0-REPEATED-30").hexdigest(), "cc0/repeated.wav", "cc0/reference.json", 0,
        source_hash, ref_hash, prepared.basic_audio, prepared.piano_audio, basic_hash, piano_hash, reference, ref_hash,
        prepared.receipt, hashlib.sha256(canonical_json(asdict(prepared.receipt))).hexdigest())
    return item, dict(kind="cc0_repeat_then_crop30", fixture_sha256=CC0_SHA, source_sha256=source_hash,
                     basic_sha256=basic_hash, piano_sha256=piano_hash, receipt=asdict(prepared.receipt))


def collect_artifacts(root):
    hashes, unverified = {}, []
    for path in sorted(root.rglob("*")):
        if path.is_dir(): continue
        name = path.relative_to(root).as_posix()
        if name == "summary.json": continue
        safe_path(root, name); regular_file(path)
        limit = RAW_JSON_LIMIT if path.name == "raw_transcription.json" else RAW_MIDI_LIMIT
        size = path.stat().st_size
        if size > limit:
            unverified.append(dict(path=name, size_bytes=size, reason="size_limit"))
        else: hashes[name] = digest_file(path)
    return hashes, unverified


def record_wire(record, run_root):
    value = asdict(record)
    value["output_dir"] = record.output_dir.relative_to(run_root).as_posix() if record.output_dir is not None else None
    return value


def record_from_wire(value, run_root):
    if type(value) is not dict or set(value) != set(RunRecord.__dataclass_fields__): raise ValueError("invalid record fields")
    output = safe_path(run_root, value["output_dir"]) if value["output_dir"] is not None else None
    if type(value["evidence"]) is not list: raise ValueError("invalid evidence")
    return RunRecord(**{**value, "output_dir": output, "evidence": tuple(value["evidence"])})


def _not_run(slot, reason):
    return RunRecord(**slot, status="not_run", attribution="infrastructure", error_code=reason,
                     elapsed_sec=None, events_sha256=None, output_dir=None)


def _host():
    import os
    ram = None
    if platform.system() == "Windows":
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), *[(name, ctypes.c_ulonglong) for name in
                ("total", "available", "total_page", "available_page", "total_virtual", "available_virtual", "extended")]]
        info = Memory(); info.length = ctypes.sizeof(info)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)): ram = info.total
    elif hasattr(os, "sysconf"):
        try: ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (OSError, ValueError): pass
    return dict(system=platform.system(), evaluator_python=platform.python_version(), cpu=platform.processor(),
                logical_cores=os.cpu_count(), ram_bytes=ram)


async def run_evaluation(manifest, candidates, *, manifest_path, input_root, ffmpeg, run_root, cancellation):
    run_root = Path(run_root)
    if not run_root.is_absolute(): raise ValueError("absolute run directory required")
    safe_path(run_root.parent, run_root.name)
    if run_root.exists(): raise ValueError("existing run refused")
    schedule = build_schedule(manifest, candidates)
    run_root.mkdir(parents=True)
    records, preflight_records, gates = [], [], []
    identities, counts = {}, {}
    try:
        if cancellation.is_set(): gates.append("cancelled")
        else: identities = await verify_session_inputs(manifest, candidates, manifest_path=manifest_path, input_root=input_root, cancellation=cancellation)
    except asyncio.CancelledError:
        cancellation.set(); gates.append("cancelled")
    except Exception: gates.append("setup_invalid")
    for entry in manifest.entries:
        try:
            ref = read_reference(entry, stop=__import__('threading').Event())
            counts[entry.recording_id] = {key: len(value.events.notes) for key,value in ref.items()}
        except Exception:
            counts[entry.recording_id] = dict(key_release=None, sustain=None); gates.append("setup_invalid")
    header = dict(schema_version=1, manifest=identities, candidates=[candidate_wire(c) for c in candidates],
        recording_ids=[e.recording_id for e in manifest.entries], reference_counts=counts,
        host=_host(), input_preparation_sec=sum(e.audio_receipt.elapsed_sec for e in manifest.entries),
        schedule=list(schedule), evidence_kind="execution_ledger")
    immutable_bytes(run_root/"session.json", canonical_json(header))
    immutable_bytes(run_root/"schedule.json", canonical_json(list(schedule)))
    smoke = None
    if not gates:
        try:
            smoke, receipt = await prepare_preflight(ffmpeg=ffmpeg, run_root=run_root, cancellation=cancellation)
            immutable_bytes(run_root/"preflight-audio.json", canonical_json(receipt))
        except asyncio.CancelledError:
            cancellation.set(); gates.append("cancelled")
        except Exception: gates.append("preflight_failure")
    clock = time.monotonic()
    by_candidate = {c.id:c for c in candidates}; by_entry = {e.recording_id:e for e in manifest.entries}
    async def invoke(slot, item):
        remaining = SESSION_SECONDS - (time.monotonic()-clock)
        if remaining <= 0: return _not_run(slot, "budget_stop")
        try:
            async with asyncio.timeout(remaining):
                record = await run_slot(by_candidate[slot["candidate_id"]], item,
                    repeat=slot["repeat"], slot_id=slot["slot_id"], diagnostic_for=slot["diagnostic_for"],
                    run_root=run_root, cancellation=cancellation, timeout_sec=min(300,remaining))
        except (asyncio.CancelledError, TimeoutError):
            start = run_root/"starts"/(slot["slot_id"]+".json")
            record = RunRecord(**slot, status="cancelled", attribution="infrastructure", error_code="cancelled",
                elapsed_sec=0. if start.exists() else None, events_sha256=None, output_dir=None, started=start.exists())
        if time.monotonic()-clock >= SESSION_SECONDS: gates.append("budget_stop")
        elif record.status == "cancelled": cancellation.set(); gates.append("cancelled")
        if record.error_code == "evaluation_limit": gates.append("evaluation_limit")
        if record.status == "setup_failed": gates.append("setup_invalid")
        return record
    if smoke is not None:
        for candidate in sorted(candidates, key=lambda c:c.id):
            for repeat in range(2):
                if gates or cancellation.is_set(): break
                slot = dict(slot_id=f"preflight-{candidate.id}-{repeat}", recording_id=smoke.recording_id,
                            candidate_id=candidate.id, repeat=repeat, diagnostic_for=None)
                record = await invoke(slot, smoke); preflight_records.append(record)
                immutable_bytes(run_root/"preflight"/(record.slot_id+".json"), canonical_json(record_wire(record,run_root)))
                if record.status != "success": gates.append("preflight_failure")
        if len(preflight_records) == 4 and not gates:
            expected = 1.5*36*sum(max(r.elapsed_sec for r in preflight_records if r.candidate_id==c.id) for c in candidates)
            immutable_bytes(run_root/"budget-preflight.json", canonical_json(dict(expected_sec=expected,limit_sec=SESSION_SECONDS)))
            if expected > SESSION_SECONDS: gates.append("budget_preflight_failure")
    for slot in schedule:
        if cancellation.is_set() and "cancelled" not in gates: gates.append("cancelled")
        if time.monotonic()-clock >= SESSION_SECONDS and "budget_stop" not in gates: gates.append("budget_stop")
        reason = "cancelled" if cancellation.is_set() else "budget_stop" if "budget_stop" in gates else "preflight_failure" if "preflight_failure" in gates else "budget_preflight_failure" if "budget_preflight_failure" in gates else "setup_invalid"
        record = _not_run(slot, reason) if gates else await invoke(slot, by_entry[slot["recording_id"]])
        records.append(record)
        immutable_bytes(run_root/"records"/(record.slot_id+".json"), canonical_json(record_wire(record, run_root)))
        print(f"completed {len(records)}/72 {record.candidate_id} {record.status}",flush=True)
    for failed in tuple(records):
        if gates or cancellation.is_set() or not failed.started or failed.status not in {"model_error","timeout","output_invalid"}: continue
        own = [r for r in records if r.recording_id==failed.recording_id and r.candidate_id==failed.candidate_id]
        if sum(r.status=="success" for r in own)>=3 or reproducible_failures(own): continue
        slot = dict(slot_id="diag-"+failed.slot_id, recording_id=failed.recording_id,candidate_id=failed.candidate_id,
                    repeat=failed.repeat,diagnostic_for=failed.slot_id)
        record = await invoke(slot, by_entry[failed.recording_id]); records.append(record)
        immutable_bytes(run_root/"records"/(record.slot_id+".json"), canonical_json(record_wire(record,run_root)))
    hashes, unverified = collect_artifacts(run_root)
    if unverified: gates.append("evaluation_limit")
    summary = build_summary(header,records,gates)
    summary.update(records=["records/"+r.slot_id+".json" for r in records],
        preflight=["preflight/"+r.slot_id+".json" for r in preflight_records], artifacts=hashes,
        unverified_artifacts=unverified, session_elapsed_sec=time.monotonic()-clock)
    data = canonical_json(summary)
    immutable_bytes(run_root/"summary.json", canonical_json(dict(summary=summary,sha256=hashlib.sha256(data).hexdigest())))
    return run_root/"summary.json"
