"""Canonical receipts and bounded paths used by preparation and consumers."""

from dataclasses import asdict, fields, replace
import hashlib
import json
from pathlib import Path
import re
import stat
import threading
import unicodedata
import uuid

from musicsheet_pipeline.basic_pitch.io import check_stop, run_owned_io

from .contracts import AudioPreparationReceipt, Manifest, ManifestEntry

JSON_LIMIT = 8 * 1024 * 1024
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def relative_name(value: str) -> str:
    if type(value) is not str or not value or "\\" in value or unicodedata.normalize("NFC", value) != value:
        raise ValueError("invalid relative path")
    for part in value.split("/"):
        if part in {"", ".", ".."} or part.rstrip(" .") != part or part.split(".")[0].casefold() in RESERVED or any(ord(c) < 32 or c in '<>:"|?*' for c in part):
            raise ValueError("unsafe relative path")
    return value


def safe_path(root: Path, name: str) -> Path:
    relative_name(name)
    root = root.absolute()
    candidate = root / name
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("linked path")
    candidate.resolve().relative_to(root.resolve())
    return candidate


def regular_file(path: Path, *, maximum: int | None = None) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction(): raise ValueError("linked file")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or maximum is not None and info.st_size > maximum:
        raise ValueError("invalid regular file/size")


def canonical_json(value: object) -> bytes:
    try: return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError): raise ValueError("invalid canonical JSON") from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json(data: bytes):
    if len(data) > JSON_LIMIT: raise ValueError("JSON size limit")
    try: return json.loads(data, object_pairs_hook=_pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError): raise ValueError("invalid JSON") from None


def digest_file(path: Path, *, stop: threading.Event | None = None) -> str:
    regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            if stop is not None: check_stop(stop)
            chunk = source.read(1024 * 1024)
            if not chunk: break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes, *, stop: threading.Event | None = None) -> None:
    safe_path(path.parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with temporary.open("xb") as out:
            for offset in range(0, len(data), 65536):
                if stop is not None: check_stop(stop)
                out.write(data[offset:offset + 65536])
            out.flush()
        if stop is not None: check_stop(stop)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def receipt_from_dict(value: dict) -> AudioPreparationReceipt:
    if type(value) is not dict or set(value) != {field.name for field in fields(AudioPreparationReceipt)}:
        raise ValueError("missing/unknown audio receipt field")
    args = value["argv"]
    if type(args) is not list or any(type(command) is not list for command in args): raise ValueError("invalid argv")
    return AudioPreparationReceipt(**{**value, "argv": tuple(tuple(command) for command in args)})


def write_manifest(manifest: Manifest, path: Path, *, stop: threading.Event | None = None) -> str:
    payload = asdict(manifest)
    for entry in payload["entries"]:
        for field in ("basic_audio", "piano_audio", "reference_path"):
            entry[field] = relative_name(entry[field].as_posix())
        if hashlib.sha256(canonical_json(entry["audio_receipt"])).hexdigest() != entry["audio_receipt_sha256"]:
            raise ValueError("audio receipt hash mismatch")
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    atomic_write(path, canonical_json({"manifest": payload, "sha256": digest}), stop=stop)
    return digest


def verified_selection(run_root, metadata_hashes, *, stop=None):
    from .dataset import METADATA_LIMIT, metadata_rows, select_recordings
    if type(metadata_hashes) is not dict or set(metadata_hashes) != {"v3", "v2"}:
        raise ValueError("invalid metadata hashes")
    records = {}
    for key, version in (("v3", "v3.0.0"), ("v2", "v2.0.0")):
        path = safe_path(run_root, f"metadata/{version}.json")
        regular_file(path, maximum=METADATA_LIMIT)
        if digest_file(path, stop=stop) != metadata_hashes[key]: raise ValueError("metadata hash mismatch")
        records[key] = metadata_rows(path.read_bytes())
    return select_recordings(records["v3"], records["v2"])


def load_manifest(path: Path, *, run_root: Path, stop: threading.Event | None = None) -> Manifest:
    if stop is not None: check_stop(stop)
    regular_file(path, maximum=JSON_LIMIT)
    wrapper = strict_json(path.read_bytes())
    if type(wrapper) is not dict or set(wrapper) != {"manifest", "sha256"}: raise ValueError("invalid manifest wrapper")
    payload = wrapper["manifest"]
    if hashlib.sha256(canonical_json(payload)).hexdigest() != wrapper["sha256"]: raise ValueError("manifest hash mismatch")
    if type(payload) is not dict or set(payload) != {field.name for field in fields(Manifest)}: raise ValueError("invalid manifest fields")
    if type(payload["entries"]) is not list: raise ValueError("invalid entries")
    selected = verified_selection(run_root, payload["metadata_hashes"], stop=stop)
    if len(payload["entries"]) != len(selected): raise ValueError("selection length mismatch")
    source_receipt = payload["source_receipt"]
    if type(source_receipt) is not dict: raise ValueError("invalid source receipt")
    source_root = safe_path(run_root, source_receipt.get("source_root"))
    from .dataset import validate_source_receipt, MEMBER_LIMIT
    acquisition_receipt = {key: value for key, value in source_receipt.items() if key != "source_root"}
    validate_source_receipt(acquisition_receipt, selected)
    entries = []
    used = set()
    for value, row in zip(payload["entries"], selected, strict=True):
        if type(value) is not dict or set(value) != {field.name for field in fields(ManifestEntry)}: raise ValueError("invalid entry fields")
        relative_name(value["audio_filename"]); relative_name(value["midi_filename"])
        if any(value[field] != row[field] for field in ("recording_id", "audio_filename", "midi_filename", "start_sec")):
            raise ValueError("fixed selection/crop mismatch")
        for field, hash_field in (("audio_filename", "source_audio_sha256"), ("midi_filename", "source_midi_sha256")):
            original = safe_path(source_root, value[field])
            member = source_receipt["members"][value[field]]
            regular_file(original, maximum=MEMBER_LIMIT)
            if original.stat().st_size != member["bytes"] or digest_file(original, stop=stop) != value[hash_field] or member["sha256"] != value[hash_field]:
                raise ValueError("original source hash mismatch")
        if value["recording_id"] != hashlib.sha256(b"MusicSheet-W05-R1\n" + value["audio_filename"].encode()).hexdigest(): raise ValueError("recording ID mismatch")
        if hashlib.sha256(canonical_json(value["audio_receipt"])).hexdigest() != value["audio_receipt_sha256"]: raise ValueError("receipt hash mismatch")
        resolved = {}
        for field, hash_field in (("basic_audio", "basic_audio_sha256"), ("piano_audio", "piano_audio_sha256"), ("reference_path", "reference_sha256")):
            identity = relative_name(value[field]).casefold()
            if identity in used: raise ValueError("duplicate artifact path")
            used.add(identity)
            resolved[field] = safe_path(run_root, value[field])
            if digest_file(resolved[field], stop=stop) != value[hash_field]: raise ValueError("artifact hash mismatch")
        entries.append(ManifestEntry(**{**value, **resolved, "audio_receipt": receipt_from_dict(value["audio_receipt"])}))
    return Manifest(**{**payload, "entries": tuple(entries)})


async def prepare_manifest(selection, *, source_root, output_root, metadata_hashes, source_receipt, ffmpeg, cancellation) -> Manifest:
    from .audio import prepare_audio
    from .dataset import selection_digest
    from .reference import parse_reference
    from .metrics import scoring_events
    if len(selection) != 12: raise ValueError("expected twelve recordings")
    def verify_inputs(stop):
        from .dataset import validate_source_receipt
        expected = verified_selection(output_root, metadata_hashes, stop=stop)
        if tuple(selection) != expected: raise ValueError("fixed selection mismatch")
        validate_source_receipt(source_receipt, selection)
    await run_owned_io(verify_inputs, cancellation=cancellation)
    source_receipt = {**source_receipt, "source_root": relative_name(source_root.relative_to(output_root).as_posix())}
    entries = []
    for row in selection:
        identity, start = selection_digest(row["audio_filename"]), row["start_sec"]
        audio, midi = safe_path(source_root, row["audio_filename"]), safe_path(source_root, row["midi_filename"])
        member_hashes = source_receipt.get("members", {})
        def prepare_reference(stop):
            audio_hash, midi_hash = digest_file(audio, stop=stop), digest_file(midi, stop=stop)
            if member_hashes.get(row["audio_filename"], {}).get("sha256") != audio_hash or member_hashes.get(row["midi_filename"], {}).get("sha256") != midi_hash:
                raise ValueError("source receipt mismatch")
            ref = parse_reference(midi)
            scored = {name: asdict(scoring_events(getattr(ref, name), start_sec=start)) for name in ("key_release", "sustain")}
            return audio_hash, midi_hash, canonical_json(scored)
        audio_hash, midi_hash, reference = await run_owned_io(prepare_reference, cancellation=cancellation)
        prepared = await prepare_audio(audio, start_sec=start, destination=safe_path(output_root, f"inputs/{identity}"), ffmpeg=ffmpeg, cancellation=cancellation)
        ref_path = safe_path(output_root, f"inputs/{identity}/reference.json")
        def finish(stop):
            atomic_write(ref_path, reference, stop=stop)
            return digest_file(prepared.basic_audio, stop=stop), digest_file(prepared.piano_audio, stop=stop)
        basic_hash, piano_hash = await run_owned_io(finish, cancellation=cancellation)
        entries.append(ManifestEntry(identity, row["audio_filename"], row["midi_filename"], start, audio_hash, midi_hash, prepared.basic_audio.relative_to(output_root), prepared.piano_audio.relative_to(output_root), basic_hash, piano_hash, ref_path.relative_to(output_root), hashlib.sha256(reference).hexdigest(), prepared.receipt, hashlib.sha256(canonical_json(asdict(prepared.receipt))).hexdigest()))
        print(f"prepared {len(entries)}/12 {identity[:12]}", flush=True)
    return Manifest(1, "w05-r1-selection-r2-crop", tuple(entries), metadata_hashes, source_receipt)
