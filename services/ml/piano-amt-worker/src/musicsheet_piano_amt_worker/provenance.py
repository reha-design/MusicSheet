"""Pinned source and local checkpoint gates; no model or network imports."""

import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import stat

SOURCE_URL = "https://github.com/qiuqiangkong/piano_transcription_inference"
SOURCE_COMMIT = "0226e74cbc805660e34bbd6a8fed2083890ebb88"
PACKAGE_VERSION = "0.0.6"
CHECKPOINT_NAME = "CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
CHECKPOINT_BYTES = 171966578
CHECKPOINT_MD5 = "22b961b77c1878239fec963362097045"
OPTIONS = {"onset_threshold": .3, "offset_threshold": .3,
           "frame_threshold": .1, "pedal_offset_threshold": .2,
           "segment_samples": 160000, "sample_rate": 16000}


def safe_path(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute unlinked path required")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("linked path rejected")
    return path


def regular_file(path: Path, *, maximum: int) -> Path:
    path = safe_path(path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("invalid file or size")
    except OSError:
        raise ValueError("unavailable regular file") from None
    return path


def valid_sha256(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("invalid SHA256")
    return value.lower()


def validate_checkpoint(path: Path, *, expected_sha256: str | None = None) -> str:
    """Fixed official bytes/MD5 prevent the upstream automatic download branch."""
    path = regular_file(path, maximum=CHECKPOINT_BYTES)
    if expected_sha256 is not None:
        expected_sha256 = valid_sha256(expected_sha256)
    md5, sha256 = hashlib.md5(), hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                if size > CHECKPOINT_BYTES:
                    raise ValueError("checkpoint size mismatch")
                md5.update(chunk)
                sha256.update(chunk)
    except OSError:
        raise ValueError("checkpoint read failed") from None
    digest = sha256.hexdigest()
    if size != CHECKPOINT_BYTES or md5.hexdigest() != CHECKPOINT_MD5 or (
        expected_sha256 is not None and digest != expected_sha256
    ):
        raise ValueError("checkpoint integrity mismatch")
    return digest


def validate_installed_source() -> None:
    try:
        version = metadata.version("piano-transcription-inference")
        receipt = json.loads(metadata.distribution("piano-transcription-inference").read_text("direct_url.json") or "null")
        if (version != PACKAGE_VERSION or type(receipt) is not dict
            or receipt.get("url") != SOURCE_URL
            or receipt.get("vcs_info", {}).get("vcs") != "git"
            or receipt["vcs_info"].get("commit_id") != SOURCE_COMMIT):
            raise ValueError("pinned model source mismatch")
    except (metadata.PackageNotFoundError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        raise ValueError("pinned model source unavailable") from None
