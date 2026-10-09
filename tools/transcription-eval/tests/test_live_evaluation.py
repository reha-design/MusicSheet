"""Validate a captured first CPU session; never launch or acquire models.

A passing integrity check can describe a partial/no_selection evaluation.
It does not imply a completed comparison or an approved default model.
"""
import copy
import os
from pathlib import Path

import pytest


MANIFEST_SHA = "b3f664dd3c6372216712d3916639df017182c291d4e0f797b35aae3e51c7dfb9"
MODEL_SHAS = {
    "basic_pitch": "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec",
    "piano_amt": "c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141",
}
LOCK_SHAS = {
    "basic_pitch": "2d7d8128b0809d4ea759b6fc0d8ea6ba413a596c5aff864bc823b145a443597c",
    "piano_amt": "3c97296a2ae6af71230cc79117d2b1df4d35ed20c764618fb94235133708b6e5",
}


def configured_run(environ):
    if environ.get("MUSICSHEET_W05_LIVE") != "1":
        pytest.skip("explicit W05 live opt-in required; no benchmark executed")
    value = environ.get("MUSICSHEET_W05_RUN_DIR")
    if not value:
        pytest.skip("captured W05 run directory required; no benchmark validated")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("absolute captured run directory required")
    return path


def check_fixed_receipts(header, candidates, manifest):
    from musicsheet_transcription_eval.session import build_schedule

    assert header["evidence_kind"] == "execution_ledger"
    assert header["manifest"]["manifest_sha256"] == MANIFEST_SHA
    assert header["recording_ids"] == [e.recording_id for e in manifest.entries]
    assert len(candidates) == 2 and {c.id for c in candidates} == set(MODEL_SHAS)
    assert header["schedule"] == list(build_schedule(manifest, candidates))
    for candidate in candidates:
        assert candidate.checkpoint_sha256 == MODEL_SHAS[candidate.id]
        assert candidate.lock_sha256 == LOCK_SHAS[candidate.id]


@pytest.mark.parametrize("environ", [{}, {"MUSICSHEET_W05_LIVE": "0"},
                                      {"MUSICSHEET_W05_LIVE": "1"}])
def test_unconfigured_run_is_explicit_skip(environ):
    with pytest.raises(pytest.skip.Exception, match="W05"):
        configured_run(environ)


def test_relative_captured_run_is_rejected():
    with pytest.raises(ValueError, match="absolute"):
        configured_run({"MUSICSHEET_W05_LIVE": "1", "MUSICSHEET_W05_RUN_DIR": "relative"})


@pytest.mark.parametrize("case", ["valid", "manifest", "recording", "schedule", "model", "lock"])
def test_fixed_receipts_reject_other_comparisons(tmp_path, monkeypatch, case):
    from dataclasses import replace
    from musicsheet_transcription_eval.session import build_schedule
    from test_runner import session_fixture

    _, manifest, candidates, _ = session_fixture(tmp_path, monkeypatch)
    candidates = tuple(replace(c, checkpoint_sha256=MODEL_SHAS[c.id],
                               lock_sha256=LOCK_SHAS[c.id]) for c in candidates)
    header = dict(evidence_kind="execution_ledger", manifest=dict(manifest_sha256=MANIFEST_SHA),
                  recording_ids=[e.recording_id for e in manifest.entries],
                  schedule=list(build_schedule(manifest, candidates)))
    header = copy.deepcopy(header)
    if case == "manifest": header["manifest"]["manifest_sha256"] = "0" * 64
    if case == "recording": header["recording_ids"].reverse()
    if case == "schedule": header["schedule"].reverse()
    if case == "model": candidates = (replace(candidates[0], checkpoint_sha256="0" * 64), candidates[1])
    if case == "lock": candidates = (replace(candidates[0], lock_sha256="0" * 64), candidates[1])
    if case == "valid":
        check_fixed_receipts(header, candidates, manifest)
    else:
        with pytest.raises(AssertionError):
            check_fixed_receipts(header, candidates, manifest)


@pytest.mark.live_evaluation
def test_captured_first_cpu_session_integrity(record_property):
    run_dir = configured_run(os.environ)
    import threading
    from musicsheet_transcription_eval.contracts import Candidate
    from musicsheet_transcription_eval.determinism import events_hash
    from musicsheet_transcription_eval.manifest import digest_file, load_manifest
    from musicsheet_transcription_eval.report import load_verified_run
    from musicsheet_transcription_eval.results import normalize_output, read_json
    from musicsheet_transcription_eval.runner import REPO
    from musicsheet_transcription_eval.session import CC0_SHA, record_from_wire

    stop = threading.Event()
    manifest_path = REPO / "docs/evaluations/maestro-w05-manifest.json"
    assert digest_file(manifest_path) == MANIFEST_SHA
    manifest = load_manifest(manifest_path, run_root=REPO / "outputs/w05-evaluation/task2-20261006", stop=stop)
    summary, header, records, digest = load_verified_run(run_dir)
    candidates = tuple(Candidate(**{**c, **{k: Path(c[k]) for k in ("python", "checkpoint", "lock")}})
                       for c in header["candidates"])
    check_fixed_receipts(header, candidates, manifest)
    for candidate in candidates:
        assert digest_file(candidate.checkpoint) == candidate.checkpoint_sha256
        assert digest_file(candidate.lock) == candidate.lock_sha256
    by_candidate = {c.id: c for c in candidates}
    entries = {e.recording_id: e for e in manifest.entries}
    assert len([r for r in records if r.diagnostic_for is None]) == 72
    for kind, model in summary["models"].items():
        assert len(model["first_runs"]) == 12
        assert model["reliability"]["scheduled"] == 36
    preflight = [record_from_wire(read_json(run_dir / name, stop=stop), run_dir)
                 for name in summary["preflight"]]
    assert len(preflight) <= 4
    receipt_path = run_dir / "preflight-audio.json"
    receipt = read_json(receipt_path, stop=stop) if receipt_path.exists() else None
    if receipt is not None:
        assert receipt["kind"] == "cc0_repeat_then_crop30" and receipt["fixture_sha256"] == CC0_SHA
    if not summary["gates"]:
        assert len(preflight) == 4 and all(r.status == "success" for r in preflight)
    for record in records + preflight:
        if record.status != "success":
            continue
        kind = record.candidate_id
        if record in preflight:
            expected_input = receipt["basic_sha256" if kind == "basic_pitch" else "piano_sha256"]
        else:
            entry = entries[record.recording_id]
            expected_input = entry.basic_audio_sha256 if kind == "basic_pitch" else entry.piano_audio_sha256
        assert record.output_dir is not None
        for name in ("raw_transcription.json", "transcription.mid"):
            assert (record.output_dir / name).is_file()
        # Revalidate native provenance/default options/MIDI semantics, not just the ledger hashes.
        events = normalize_output(by_candidate[kind], record.output_dir, input_sha256=expected_input, stop=stop)
        assert events_hash(events) == record.events_sha256
    if summary["gates"]:
        assert summary["decision"]["status"] == "no_selection"
    record_property("summary_sha256", digest)
    record_property("evaluation_status", summary["decision"]["status"])
    record_property("integrity_only", True)
