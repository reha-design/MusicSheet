"""Prepare the pinned official weights once; inference never uses this module."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import unquote, urlsplit
import uuid

import httpx

from .manifest import regular_file, strict_json

CHECKPOINT_NAME = "CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
CHECKPOINT_BYTES = 171966578
CHECKPOINT_MD5 = "22b961b77c1878239fec963362097045"
METADATA_URL = "https://zenodo.org/api/records/4034264"
METADATA_LIMIT = 4 * 1024 * 1024
TRANSFER_LIMIT = 180 * 1024 * 1024
TOTAL_SECONDS = 600


def _directory(destination: Path) -> Path:
    destination = Path(destination)
    if not destination.is_absolute() or ".." in destination.parts:
        raise ValueError("absolute checkpoint destination required")
    for path in (destination, *destination.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError("linked checkpoint destination")
    if destination.exists() and not destination.is_dir():
        raise ValueError("invalid checkpoint destination")
    return destination


def _hash_file(path: Path) -> tuple[str, str]:
    regular_file(path, maximum=CHECKPOINT_BYTES)
    md5, sha256, size = hashlib.md5(), hashlib.sha256(), 0
    with path.open("rb") as handle:
        while data := handle.read(1024 * 1024):
            size += len(data)
            if size > CHECKPOINT_BYTES:
                raise ValueError("checkpoint size limit")
            md5.update(data)
            sha256.update(data)
    if size != CHECKPOINT_BYTES or md5.hexdigest() != CHECKPOINT_MD5:
        raise ValueError("checkpoint integrity mismatch")
    return md5.hexdigest(), sha256.hexdigest()


def _receipt(target: Path, md5: str, sha256: str) -> dict[str, object]:
    return {"schema_version": 1, "record_id": 4034264, "filename": CHECKPOINT_NAME,
        "path": str(target), "size_bytes": CHECKPOINT_BYTES, "md5": md5, "sha256": sha256,
        "license": "CC-BY-4.0", "metadata_url": METADATA_URL}


def _deadline(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("checkpoint preparation deadline")
    return min(60, remaining)


async def _chunks(client, url, *, maximum, deadline, transfer):
    async with client.stream("GET", url, timeout=_deadline(deadline)) as response:
        if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("invalid checkpoint HTTP response")
        length = response.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > maximum):
            raise ValueError("checkpoint HTTP size limit")
        size = 0
        async for chunk in response.aiter_raw():
            _deadline(deadline)
            size += len(chunk)
            transfer[0] += len(chunk)
            if size > maximum or transfer[0] > TRANSFER_LIMIT:
                raise ValueError("checkpoint transfer limit")
            yield chunk
        if length is not None and size != int(length):
            raise ValueError("incomplete checkpoint HTTP body")
    _deadline(deadline)


def _download_url(metadata: object) -> str:
    if type(metadata) is not dict or type(metadata.get("id")) is not int or metadata["id"] != 4034264:
        raise ValueError("checkpoint metadata record mismatch")
    try:
        if metadata["metadata"]["license"]["id"] != "cc-by-4.0":
            raise ValueError("checkpoint license mismatch")
        files = metadata["files"]
        if type(files) is not list:
            raise ValueError("checkpoint metadata files invalid")
        matches = [item for item in files if type(item) is dict and item.get("key") == CHECKPOINT_NAME]
        if len(matches) != 1:
            raise ValueError("checkpoint metadata file mismatch")
        item = matches[0]
        if type(item.get("size")) is not int or item["size"] != CHECKPOINT_BYTES or item.get("checksum") != "md5:" + CHECKPOINT_MD5:
            raise ValueError("checkpoint metadata integrity mismatch")
        url = item["links"]["self"]
        if type(url) is not str:
            raise ValueError("checkpoint metadata URL invalid")
        parts = urlsplit(url)
        expected_path = "/api/records/4034264/files/" + CHECKPOINT_NAME + "/content"
        if parts.scheme != "https" or parts.netloc != "zenodo.org" or unquote(parts.path) != expected_path or parts.query or parts.fragment:
            raise ValueError("checkpoint metadata URL rejected")
        return url
    except (KeyError, TypeError, AttributeError):
        raise ValueError("checkpoint metadata invalid") from None


def prepare_checkpoint(destination: Path) -> dict[str, object]:
    destination = _directory(destination)
    target = destination / CHECKPOINT_NAME
    if target.exists() or target.is_symlink():
        try:
            md5, sha256 = _hash_file(target)
            return _receipt(target, md5, sha256)
        except OSError:
            raise ValueError("cached checkpoint unavailable") from None
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise ValueError("synchronous preparation required")
    return asyncio.run(_prepare_download(destination, target))


async def _prepare_download(destination: Path, target: Path) -> dict[str, object]:
    deadline, transfer = time.monotonic() + TOTAL_SECONDS, [0]
    part = destination / (CHECKPOINT_NAME + "." + uuid.uuid4().hex + ".part")
    owned_part = False
    try:
        # trust_env=False excludes environment credentials/proxies; no redirects/cookies.
        async with asyncio.timeout(TOTAL_SECONDS), httpx.AsyncClient(headers={"accept-encoding":"identity"}, follow_redirects=False,
                          trust_env=False, timeout=60) as client:
            metadata_bytes = b"".join([chunk async for chunk in _chunks(client, METADATA_URL,
                maximum=METADATA_LIMIT, deadline=deadline, transfer=transfer)])
            url = _download_url(strict_json(metadata_bytes))
            client.cookies.clear()
            destination.mkdir(parents=True, exist_ok=True)
            with part.open("xb") as handle:
                owned_part = True
                async for chunk in _chunks(client, url, maximum=CHECKPOINT_BYTES, deadline=deadline, transfer=transfer):
                    handle.write(chunk)
            md5, sha256 = _hash_file(part)
            _deadline(deadline)
            # Link publishes without replacing a pre-existing target (including races).
            os.link(part, target)
            part.unlink()
            owned_part = False
            receipt = _receipt(target, md5, sha256)
            return receipt
    except (OSError, httpx.HTTPError, TimeoutError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("checkpoint preparation failed") from None
    finally:
        if owned_part:
            part.unlink(missing_ok=True)
