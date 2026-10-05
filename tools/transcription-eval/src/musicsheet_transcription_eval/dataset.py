"""Deterministic selection and receipt-backed member acquisition."""

import hashlib
import math
from pathlib import Path
import shutil
import stat
import threading
import time
import uuid
import zipfile
import zlib

import httpx
from musicsheet_pipeline.basic_pitch.io import check_stop

from .manifest import atomic_write, canonical_json, digest_file, regular_file, relative_name, safe_path, strict_json
from .range_io import BoundedLocalReader, RangeReader
from .contracts import hash_value

ARCHIVE_URL = "https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0.zip"
ARCHIVE_SHA256 = "6680fea5be2339ea15091a249fbd70e49551246ddbd5ca50f1b2352c08c95291"
PREFIX = "maestro-v3.0.0/"
MEMBER_LIMIT = 2 * 1024 ** 3
DECODED_LIMIT = 8 * 1024 ** 3
MIN_FREE = 10 * 1024 ** 3
METADATA_LIMIT = 4 * 1024 * 1024


def selection_digest(audio_filename: str) -> str:
    relative_name(audio_filename)
    return hashlib.sha256(b"MusicSheet-W05-R1\n" + audio_filename.encode("utf-8")).hexdigest()


def crop_start(duration: float, audio_filename: str) -> int:
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 90: raise ValueError("invalid duration")
    relative_name(audio_filename)
    digest = hashlib.sha256(b"MusicSheet-W05-R2-CROP\n" + audio_filename.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % (math.floor(duration) - 30 + 1)


def _index(rows):
    indexed, audio_names, midi_names = {}, set(), set()
    for row in rows:
        if type(row) is not dict or not {"audio_filename", "midi_filename", "duration", "split"} <= row.keys(): raise ValueError("invalid metadata row")
        audio, midi = relative_name(row["audio_filename"]), relative_name(row["midi_filename"])
        if not audio.endswith(".wav") or not midi.endswith((".midi", ".mid")): raise ValueError("invalid filename extension")
        if audio.casefold() in audio_names or midi.casefold() in midi_names: raise ValueError("duplicate metadata path")
        duration = row["duration"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0 or row["split"] not in {"train", "validation", "test"}: raise ValueError("invalid duration/split")
        audio_names.add(audio.casefold()); midi_names.add(midi.casefold()); indexed[audio] = dict(row)
    return indexed


def select_recordings(v3, v2):
    current, previous = _index(v3), _index(v2)
    eligible = [row for name, row in current.items() if row["split"] == "test" and row["duration"] >= 90 and name in previous and previous[name]["split"] == "test" and row["midi_filename"] == previous[name]["midi_filename"]]
    eligible.sort(key=lambda row: (selection_digest(row["audio_filename"]), row["audio_filename"]))
    if len(eligible) < 12: raise ValueError("insufficient eligible recordings")
    return tuple({**row, "recording_id": selection_digest(row["audio_filename"]), "start_sec": crop_start(row["duration"], row["audio_filename"])} for row in eligible[:12])


def metadata_rows(data: bytes):
    if len(data) > METADATA_LIMIT: raise ValueError("metadata size limit")
    value = strict_json(data)
    if type(value) is list: return value
    if type(value) is not dict or not value or any(type(column) is not dict for column in value.values()): raise ValueError("invalid metadata columns")
    keys = tuple(next(iter(value.values())))
    if any(set(column) != set(keys) for column in value.values()): raise ValueError("metadata column index mismatch")
    return [{name: column[key] for name, column in value.items()} for key in keys]


def download_metadata(version: str, *, destination: Path, stop: threading.Event):
    if version not in {"v3.0.0", "v2.0.0"}: raise ValueError("invalid metadata version")
    url = f"https://storage.googleapis.com/magentadata/datasets/maestro/{version}/maestro-{version}.json"
    check_stop(stop)
    with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200 or response.headers.get("Content-Encoding", "identity") != "identity": raise ValueError("metadata response rejected")
            if int(response.headers.get("Content-Length", "0")) > METADATA_LIMIT: raise ValueError("metadata declared size limit")
            body = bytearray()
            for chunk in response.iter_bytes():
                check_stop(stop)
                if len(body) + len(chunk) > METADATA_LIMIT: raise ValueError("metadata size limit")
                body.extend(chunk)
    rows = metadata_rows(bytes(body))
    atomic_write(destination, bytes(body), stop=stop)
    return rows, hashlib.sha256(body).hexdigest(), url


def validate_source_receipt(receipt, selection):
    fields = {"schema_version", "source_url", "license", "integrity", "archive_sha256", "archive_bytes", "archive_etag", "transferred_bytes", "decoded_bytes", "members"}
    if type(receipt) is not dict or set(receipt) != fields:
        raise ValueError("invalid source receipt fields")
    names = {row[field] for row in selection for field in ("audio_filename", "midi_filename")}
    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1 or receipt["source_url"] != ARCHIVE_URL or receipt["license"] != "CC-BY-NC-SA-4.0" or receipt["integrity"] not in {"full_archive_sha256", "partial_zip_crc_sha256"}:
        raise ValueError("invalid source receipt identity")
    for field, maximum in (("archive_bytes", 2 ** 63 - 1), ("transferred_bytes", 6 * 1024 ** 3), ("decoded_bytes", DECODED_LIMIT)):
        if type(receipt[field]) is not int or not 0 <= receipt[field] <= maximum:
            raise ValueError("invalid source receipt byte count")
    if receipt["archive_bytes"] == 0: raise ValueError("empty archive")
    if receipt["integrity"] == "full_archive_sha256":
        if receipt["archive_sha256"] != ARCHIVE_SHA256 or receipt["archive_etag"] is not None: raise ValueError("invalid archive SHA256 claim")
    elif receipt["archive_sha256"] is not None or type(receipt["archive_etag"]) is not str or not receipt["archive_etag"] or receipt["archive_etag"].startswith("W/"):
        raise ValueError("invalid partial archive receipt")
    if type(receipt["members"]) is not dict or set(receipt["members"]) != names: raise ValueError("incomplete source receipt")
    total = 0
    for member in receipt["members"].values():
        if type(member) is not dict or set(member) != {"bytes", "sha256", "crc32"}: raise ValueError("invalid member receipt")
        hash_value(member["sha256"])
        if type(member["bytes"]) is not int or not 0 <= member["bytes"] <= MEMBER_LIMIT or type(member["crc32"]) is not int or not 0 <= member["crc32"] <= 0xffffffff: raise ValueError("invalid member count/CRC")
        total += member["bytes"]
    if total != receipt["decoded_bytes"] or total > DECODED_LIMIT: raise ValueError("decoded receipt size mismatch")


def _receipt(source_root: Path, selection, stop):
    path = safe_path(source_root, "source-receipt.json")
    if not path.exists(): return None
    regular_file(path, maximum=8 * 1024 * 1024)
    wrapper = strict_json(path.read_bytes())
    if type(wrapper) is not dict or set(wrapper) != {"receipt", "sha256"} or hashlib.sha256(canonical_json(wrapper["receipt"])).hexdigest() != wrapper["sha256"]: raise ValueError("source receipt hash mismatch")
    receipt = wrapper["receipt"]
    validate_source_receipt(receipt, selection)
    for name, member in receipt["members"].items():
        file = safe_path(source_root, name)
        regular_file(file, maximum=MEMBER_LIMIT)
        if file.stat().st_size != member["bytes"] or digest_file(file, stop=stop) != member["sha256"]: raise ValueError("cached member hash mismatch")
    return receipt


def acquire_members(selection, *, source, destination: Path, stop: threading.Event):
    check_stop(stop)
    destination = destination.absolute()
    safe_path(destination.parent, destination.name)
    destination.mkdir(parents=True, exist_ok=True)
    cached = _receipt(destination, selection, stop)
    if cached is not None: return cached
    started = time.monotonic()
    def guard():
        check_stop(stop)
        if time.monotonic() - started >= 1800: raise ValueError("acquisition time limit")
        if shutil.disk_usage(destination).free < MIN_FREE: raise ValueError("insufficient free diskspace")
    guard()
    local = isinstance(source, Path) or not str(source).startswith("https://")
    if local and Path(source).is_dir():
        receipt = _receipt(Path(source), selection, stop)
        if receipt is None: raise ValueError("local extraction lacks trusted receipt")
        decoded = 0
        for name, member in receipt["members"].items():
            guard()
            original, target = safe_path(Path(source), name), safe_path(destination, name)
            if target.exists(): raise ValueError("unverified completed member exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + "." + uuid.uuid4().hex + ".part")
            try:
                digest, count, crc = hashlib.sha256(), 0, 0
                with original.open("rb") as incoming, part.open("xb") as out:
                    for chunk in iter(lambda: incoming.read(65536), b""):
                        guard(); count += len(chunk); decoded += len(chunk)
                        if count > MEMBER_LIMIT or count > member["bytes"] or decoded > DECODED_LIMIT: raise ValueError("local copy size limit")
                        digest.update(chunk); crc = zlib.crc32(chunk, crc); out.write(chunk)
                if count != member["bytes"] or digest.hexdigest() != member["sha256"] or crc != member["crc32"]: raise ValueError("local copy integrity mismatch")
                guard(); part.replace(target)
            finally:
                part.unlink(missing_ok=True)
        atomic_write(safe_path(destination, "source-receipt.json"), canonical_json({"receipt": receipt, "sha256": hashlib.sha256(canonical_json(receipt)).hexdigest()}), stop=stop)
        return receipt
    client, reader, temporary_files = None, None, []
    try:
        if local:
            source = Path(source)
            regular_file(source)
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    guard(); digest.update(chunk)
            if digest.hexdigest() != ARCHIVE_SHA256: raise ValueError("local archive official SHA256 mismatch")
            reader = BoundedLocalReader(source, stop=stop)
        else:
            if str(source) != ARCHIVE_URL: raise ValueError("unapproved archive URL")
            client = httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
            reader = RangeReader(source, client=client, stop=stop)
        members, decoded = {}, 0
        with zipfile.ZipFile(reader, "r", allowZip64=True) as archive:
            indexed = {}
            for info in archive.infolist():
                name = relative_name(info.filename.rstrip("/")).casefold()
                if name in indexed or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}: raise ValueError("unsafe/duplicate/encrypted ZIP member")
                indexed[name] = info
            chosen = []
            for row in selection:
                for field in ("audio_filename", "midi_filename"):
                    name = relative_name(row[field])
                    info = indexed.get((PREFIX + name).casefold())
                    if info is None or info.filename != PREFIX + name or info.is_dir() or info.file_size > MEMBER_LIMIT: raise ValueError("missing/oversize selected member")
                    chosen.append((name, info))
            if sum(info.file_size for _, info in chosen) > DECODED_LIMIT: raise ValueError("decoded total size limit")
            for name, info in chosen:
                guard()
                target = safe_path(destination, name)
                if target.exists(): raise ValueError("unverified completed member exists")
                target.parent.mkdir(parents=True, exist_ok=True)
                part = target.with_name(target.name + "." + uuid.uuid4().hex + ".part")
                temporary_files.append(part)
                digest, count, crc = hashlib.sha256(), 0, 0
                with archive.open(info) as incoming, part.open("xb") as out:
                    while True:
                        guard()
                        chunk = incoming.read(65536)
                        if not chunk: break
                        count += len(chunk); decoded += len(chunk)
                        if count > MEMBER_LIMIT or count > info.file_size or decoded > DECODED_LIMIT: raise ValueError("decoded stream size limit")
                        digest.update(chunk); crc = zlib.crc32(chunk, crc); out.write(chunk)
                if count != info.file_size or crc != info.CRC: raise ValueError("member CRC/size mismatch")
                guard(); part.replace(target)
                members[name] = {"bytes": count, "sha256": digest.hexdigest(), "crc32": info.CRC}
                print(f"acquired {len(members)}/24 {name}", flush=True)
        receipt = {"schema_version": 1, "source_url": ARCHIVE_URL, "license": "CC-BY-NC-SA-4.0", "integrity": "full_archive_sha256" if local else "partial_zip_crc_sha256", "archive_sha256": ARCHIVE_SHA256 if local else None, "archive_bytes": source.stat().st_size if local else reader.archive_size, "archive_etag": None if local else reader.etag, "transferred_bytes": 0 if local else reader.transferred_bytes, "decoded_bytes": decoded, "members": members}
        atomic_write(safe_path(destination, "source-receipt.json"), canonical_json({"receipt": receipt, "sha256": hashlib.sha256(canonical_json(receipt)).hexdigest()}), stop=stop)
        return receipt
    except zipfile.BadZipFile:
        raise ValueError("ZIP integrity/library acquisition unavailable") from None
    finally:
        for path in temporary_files: path.unlink(missing_ok=True)
        if reader is not None: reader.close()
        if client is not None: client.close()
