"""Offline model boundary; prepare performs only explicitly requested data I/O."""

import argparse
import asyncio
from pathlib import Path
import json
import sys


async def _prepare(args):
    from musicsheet_pipeline.basic_pitch.io import run_owned_io
    from .dataset import ARCHIVE_URL, acquire_members, download_metadata
    from .manifest import load_manifest, prepare_manifest, regular_file, safe_path, write_manifest
    repo = Path(__file__).resolve().parents[4]
    output, target, ffmpeg = Path(args.output_root), Path(args.manifest), Path(args.ffmpeg)
    if any(not path.is_absolute() for path in (output, target, ffmpeg)): raise ValueError("absolute paths required")
    output = safe_path(repo / "outputs", output.relative_to(repo / "outputs").as_posix())
    target = safe_path(repo / "docs" / "evaluations", target.relative_to(repo / "docs" / "evaluations").as_posix())
    regular_file(ffmpeg)
    if target.exists(): raise ValueError("existing frozen manifest overwrite refused")
    output.mkdir(parents=True, exist_ok=True)
    cancellation = asyncio.Event()
    async with asyncio.timeout(1800):
        records, hashes = {}, {}
        for version, key in (("v3.0.0", "v3"), ("v2.0.0", "v2")):
            records[key], hashes[key], _ = await run_owned_io(lambda stop: download_metadata(version, destination=safe_path(output, f"metadata/{version}.json"), stop=stop), cancellation=cancellation)
        from .dataset import select_recordings
        selection = select_recordings(records["v3"], records["v2"])
        print("selected 12 fixed recordings before any model execution", flush=True)
        source = Path(args.local_source).absolute() if args.local_source else ARCHIVE_URL
        source_root = safe_path(output, "source")
        receipt = await run_owned_io(lambda stop: acquire_members(selection, source=source, destination=source_root, stop=stop), cancellation=cancellation)
    manifest = await prepare_manifest(selection, source_root=source_root, output_root=output, metadata_hashes=hashes, source_receipt=receipt, ffmpeg=ffmpeg, cancellation=cancellation)
    pending = safe_path(output, "prepared-manifest.json")
    digest = await run_owned_io(lambda stop: write_manifest(manifest, pending, stop=stop), cancellation=cancellation)
    await run_owned_io(lambda stop: load_manifest(pending, run_root=output, stop=stop), cancellation=cancellation)
    from .manifest import atomic_write
    def publish(stop):
        if target.exists(): raise ValueError("existing frozen manifest overwrite refused")
        atomic_write(target, pending.read_bytes(), stop=stop)
    await run_owned_io(publish, cancellation=cancellation)
    print(json.dumps({"status": "prepared", "recordings": 12, "manifest_sha256": digest}, sort_keys=True), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed W05 transcription evaluation preparation")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Prepare the fixed twelve MAESTRO inputs; no model inference")
    for field in ("output-root", "manifest", "ffmpeg"): prepare.add_argument("--" + field, required=True)
    prepare.add_argument("--local-source", help="Verified local archive or receipt-backed extracted directory")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_prepare(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print('{"status":"cancelled"}', file=sys.stderr)
        return 130
    except Exception:
        print('{"status":"preparation_failed"}', file=sys.stderr)
        return 4
    return 0
