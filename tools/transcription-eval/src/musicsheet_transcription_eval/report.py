"""Rebuild decisions from verified immutable records before rendering."""
from dataclasses import asdict
import hashlib
import re
from pathlib import Path
import threading

from .contracts import Candidate, Metric, hash_value, integer, validate_metrics
from .determinism import events_hash
from .manifest import canonical_json, digest_file, regular_file, safe_path
from .results import events_from_dict, exact, read_json
from .runner import immutable_bytes
from .session import RAW_JSON_LIMIT, RAW_MIDI_LIMIT, build_summary, record_from_wire


def load_verified_run(run_dir):
    run_dir = Path(run_dir)
    if not run_dir.is_absolute(): raise ValueError("absolute run directory required")
    safe_path(run_dir.parent, run_dir.name)
    stop = threading.Event()
    try:
        wrapper = read_json(safe_path(run_dir,"summary.json"), stop=stop)
        exact(wrapper,("summary","sha256")); summary=wrapper["summary"]
        hash_value(wrapper["sha256"])
        if hashlib.sha256(canonical_json(summary)).hexdigest()!=wrapper["sha256"]: raise ValueError("summary hash mismatch")
        hashes=summary["artifacts"]; unverified=summary["unverified_artifacts"]
        if type(hashes) is not dict or type(unverified) is not list: raise ValueError("invalid artifact inventory")
        excluded={}
        for value in unverified:
            exact(value,("path","size_bytes","reason")); integer(value["size_bytes"],0)
            name=value["path"]; path=safe_path(run_dir,name);regular_file(path)
            if name in excluded or name in hashes or value["reason"]!="size_limit" or path.stat().st_size!=value["size_bytes"]:
                raise ValueError("unverified artifact changed")
            excluded[name]=value
        if excluded and ("evaluation_limit" not in summary["gates"] or summary["decision"]["status"]!="no_selection"):
            raise ValueError("unverified output cannot select")
        for name,digest in hashes.items():
            hash_value(digest);path=safe_path(run_dir,name)
            regular_file(path,maximum=RAW_JSON_LIMIT if path.name=="raw_transcription.json" else RAW_MIDI_LIMIT)
            if digest_file(path)!=digest: raise ValueError("artifact hash mismatch")
        actual={path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file() and path.name!="summary.json"}
        if actual!=set(hashes)|set(excluded): raise ValueError("artifact inventory changed")
        for name in ("session.json","schedule.json"):
            if name not in hashes: raise ValueError("missing session receipt")
        header=read_json(run_dir/"session.json",stop=stop)
        schedule=read_json(run_dir/"schedule.json",stop=stop)
        if schedule!=header["schedule"] or len(schedule)!=72: raise ValueError("invalid schedule")
        if len({value["slot_id"] for value in schedule})!=72: raise ValueError("duplicate slot")
        for candidate in header["candidates"]:
            Candidate(**{**candidate,**{key:Path(candidate[key]) for key in ("python","checkpoint","lock")}})
        records, preflight=[],[]
        referenced_starts=set()
        all_names=summary["records"]+summary["preflight"]
        if len(set(all_names))!=len(all_names): raise ValueError("duplicate record path")
        for name in all_names:
            if name not in hashes: raise ValueError("unhashed terminal record")
            wire=read_json(safe_path(run_dir,name),stop=stop); record=record_from_wire(wire,run_dir)
            expected_directory="preflight" if name in summary["preflight"] else "records"
            if name!=expected_directory+"/"+record.slot_id+".json": raise ValueError("record path mismatch")
            if record.started:
                start="starts/"+record.slot_id+".json";referenced_starts.add(start)
                if start not in hashes: raise ValueError("interrupted: missing start receipt")
                value=read_json(safe_path(run_dir,start),stop=stop)
                expected={key:wire[key] for key in ("slot_id","recording_id","candidate_id","repeat","diagnostic_for")}
                if value!=expected: raise ValueError("start receipt mismatch")
            for artifact,digest in (record.files or {}).items():
                if artifact not in excluded and hashes.get(artifact)!=digest: raise ValueError("record artifact mismatch")
            if record.status=="success":
                validate_metrics(record.metrics)
                normalized=[p for p in record.files if p.endswith("/events.json")]
                if len(normalized)!=1: raise ValueError("missing normalized events")
                events=events_from_dict(read_json(safe_path(run_dir,normalized[0]),stop=stop))
                if events_hash(events)!=record.events_sha256: raise ValueError("normalized events mismatch")
            (preflight if name in summary["preflight"] else records).append(record)
        starts={name for name in hashes if name.startswith("starts/")}
        if starts!=referenced_starts: raise ValueError("interrupted: orphan start receipt")
        original={r.slot_id:r for r in records if r.diagnostic_for is None}
        if len(original)!=72 or set(original)!={s["slot_id"] for s in schedule}: raise ValueError("incomplete scheduled ledger")
        for value in schedule:
            record=original[value["slot_id"]]
            if any(getattr(record,key)!=expected for key,expected in value.items()): raise ValueError("scheduled identity mismatch")
        diagnostics=set()
        for record in records:
            if record.diagnostic_for is not None:
                failed=original.get(record.diagnostic_for)
                if failed is None or not failed.started or failed.status=="success" or record.diagnostic_for in diagnostics or (
                    record.candidate_id,record.recording_id)!=(failed.candidate_id,failed.recording_id):
                    raise ValueError("invalid diagnostic linkage")
                diagnostics.add(record.diagnostic_for)
        rebuilt=build_summary(header,records,summary["gates"])
        for key,value in rebuilt.items():
            if canonical_json(summary[key])!=canonical_json(value): raise ValueError("derived summary mismatch")
        return summary,header,records,wrapper["sha256"]
    except (OSError, KeyError, TypeError, OverflowError):
        raise ValueError("invalid or incomplete evaluation run") from None


def _number(value):
    return "null" if value is None else format(value,".8g")


def _label(value):
    return re.sub(r"[^A-Za-z0-9 ._+()/-]", "_", str(value))[:160]


def write_report(run_dir:Path,destination:Path)->None:
    destination=Path(destination)
    if not destination.is_absolute() or destination.suffix!=".md" or destination.exists(): raise ValueError("new absolute Markdown report required")
    summary,header,records,digest=load_verified_run(run_dir)
    decision=summary["decision"]
    lines=["# W05 transcription comparison", "", "MAESTRO v3 test subset: 12 fixed 30-second inputs; CPU fresh-process execution.",
        "Dataset: CC-BY-NC-SA-4.0. Piano checkpoint: Qiuqiang Kong, Zenodo 4034264, CC-BY-4.0.",
        "",f"Summary SHA256: `{digest}`",f"Manifest SHA256: `{header['manifest'].get('manifest_sha256','not_verified')}`",
        "",f"Status: **{decision['status']}**; winner: {decision['winner'] or 'none'}; reason: {decision['reason']}.",
        f"Product status: {decision['product_status']}. ByteDance requires selected_pending_integration before product use.",
        "Accuracy uses first runs only; repetitions and diagnostics never replace a failed first run.",
        "This small classical piano subset does not establish YouTube/mixed-instrument/full-song performance.",
        "", f"Host: {_label(header['host'].get('system', 'unknown'))}; CPU: {_label(header['host'].get('cpu', 'unknown'))}.",
        f"Logical cores: {_label(header['host'].get('logical_cores', 'unknown'))}; RAM bytes: {_label(header['host'].get('ram_bytes', 'unknown'))}.",
        "", "| Candidate | Package version | Worker Python | Backend | Source commit | Checkpoint SHA256 | Lock SHA256 |", "|---|---|---|---|---|---|---|"]
    for model in header["candidates"]:
        runtime=model["runtime"]
        lines.append(f"| {model['id']} | {runtime['package_version']} | {'.'.join(map(str,runtime['python_version']))} | {runtime['backend']} {runtime['backend_version']} | `{model['source_commit']}` | `{model['checkpoint_sha256']}` | `{model['lock_sha256']}` |")
    lines.extend(["", "Piano: CPU float32, torch intra/inter-op threads 1/1. Basic Pitch: ONNX CPU, upstream thread defaults (not assumed equal).",
        "", "| Candidate | Started / scheduled | Success | Raw failure rate | Model-only failures / denominator | Not run |", "|---|---:|---:|---:|---:|---:|"])
    for kind,model in summary["models"].items():
        r=model["reliability"]
        lines.append(f"| {kind} | {r['started']} / 36 | {r['success']} | {_number(r['raw_failure_rate'])} | {r['model_only_failures']} / {r['model_only_denominator']} | {r['not_run']} |")
    lines.extend(["", "Gates: "+(", ".join(summary["gates"]) or "none")+".",
        "", "| Candidate | State counts | excluded_infrastructure | excluded_unresolved | CPU excluded scheduled / diagnostics |", "|---|---|---:|---:|---|"])
    for kind,model in summary["models"].items():
        r=model["reliability"];diagnostics=sum(record.candidate_id==kind and record.diagnostic_for is not None for record in records)
        counts=", ".join(f"{status}={count}" for status,count in r["status_counts"].items())
        lines.append(f"| {kind} | {counts} | {r['excluded_infrastructure']} | {r['excluded_unresolved']} | {36-model['cpu']['n']} / {diagnostics} |")
    lines.extend(["", "CPU excludes unsuccessful and unstarted scheduled slots; every diagnostic and preflight is also excluded.",
        "", "| Slot | Candidate | Status | Attribution | Error code | Diagnostic for |", "|---|---|---|---|---|---|"])
    for record in records:
        if record.status!="success" or record.diagnostic_for is not None:
            lines.append(f"| {record.slot_id} | {record.candidate_id} | {record.status} | {record.attribution or 'none'} | {record.error_code or 'none'} | {record.diagnostic_for or 'none'} |")
    lines.extend(["", "| Preflight slot | Candidate | Status | Attribution | Error code | Elapsed sec |", "|---|---|---|---|---|---:|"])
    for name in summary["preflight"]:
        record=record_from_wire(read_json(safe_path(Path(run_dir),name),stop=threading.Event()),Path(run_dir))
        lines.append(f"| {record.slot_id} | {record.candidate_id} | {record.status} | {record.attribution or 'none'} | {record.error_code or 'none'} | {_number(record.elapsed_sec)} |")
    lines.extend(["",f"Diagnostics excluded from accuracy/reliability/speed denominators: {summary['diagnostic_count']}.",
        "Generic worker exit3/4 does not identify a model cause; unresolved failures block automatic selection.",
        f"Unverified size-limited artifacts: {len(summary['unverified_artifacts'])}; contents were preserved and not hashed.",
        "", "| Candidate | Metric | macro F1 (success-only) | micro precision / recall / F1 | TP / FP / FN | Empty reference excluded |", "|---|---|---:|---|---:|---:|"])
    for kind,model in summary["models"].items():
        for name,value in model["aggregates"].items():
            m=value["micro"]
            prf=" / ".join(_number(m[key]) for key in ("precision","recall","f1"))
            lines.append(f"| {kind} | {name} | {_number(value['macro_f1'])} | {prf} | {m['tp']} / {m['fp']} / {m['fn']} | {value['excluded_empty_reference']} |")
    lines.extend(["", "| Candidate | CPU valid samples | Median sec | p95 sec (nearest rank) |", "|---|---:|---:|---:|"])
    for kind,model in summary["models"].items():
        c=model["cpu"]
        lines.append(f"| {kind} | {c['n']} | {_number(c['median_sec'])} | {_number(c['p95_sec'])} |")
    lines.extend(["", "| Candidate | Reference | Operational recall TP / planned reference | recall |", "|---|---|---:|---:|"])
    for kind,model in summary["models"].items():
        for name,r in model["operational_recall"].items():
            lines.append(f"| {kind} | {name} | {r['tp']} / {_number(r['planned_reference_notes'])} | {_number(r['recall'])} |")
    for kind,model in summary["models"].items():
        c=model["cpu"]
        lines.append("")
        lines.append(f"{kind} individual seconds: "+", ".join(_number(v) for v in model["elapsed_sec"])+".")
        lines.append(f"{kind} individual RTF (elapsed/30): "+", ".join(_number(v) for v in c["rtf"])+".")
    lines.extend(["",f"Paired nonempty recordings: {decision['paired_n']}; bootstrap PCG64 seed20261005,10000 paired samples.",
        f"Onset difference 95% CI: {decision['onset_ci']}; sustain difference 95% CI: {decision['sustain_ci']}.",
        f"Input preparation seconds: {_number(header['input_preparation_sec'])}; execution includes process startup, cleanup and output validation.",
        "CPU measurements are not warm inference or pure neural-network compute time. Linux/CUDA support requires separate evidence.",
        "", "| Candidate | Recording SHA256 | First precision/recall/F1: onset; sustain; key-release | velocity MAE / pairs | Censored predicted / key / sustain | Determinism |", "|---|---|---|---|---|---|"])
    for kind,model in summary["models"].items():
        for identity,value in model["first_runs"].items():
            scores="not_measured" if value is None else "; ".join(" / ".join(_number(value[n][key]) for key in ("precision","recall","f1")) for n in ("onset","sustain","key_release"))
            velocity="not_measured" if value is None else f"{_number(value['velocity']['mae'])} / {len(value['velocity']['pairs'])}"
            censor="not_measured" if value is None else " / ".join(str(value["censored"][n]) for n in ("predicted","reference_key_release","reference_sustain"))
            lines.append(f"| {kind} | `{identity}` | {scores} | {velocity} | {censor} | {model['determinism'][identity]['status']} |")
    lines.extend(["", "Raw slot states, all matching pair indices/sorted inputs, censor counts, normalized hashes and individual repeat scores remain in the verified ledger.",
        "Preflight inputs and four fresh smoke runs are excluded from the 36-slot denominators; session budget includes their execution and diagnostics.",
        "The report changes no product provider or fallback configuration. Only an installed, verified, integrated provider can be used for fallback."])
    immutable_bytes(destination,("\n".join(lines)+"\n").encode("utf-8"))
