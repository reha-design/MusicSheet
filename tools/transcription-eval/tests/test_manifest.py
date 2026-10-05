from dataclasses import asdict
import json

import pytest

from musicsheet_transcription_eval.contracts import AudioPreparationReceipt
from musicsheet_transcription_eval.manifest import canonical_json, load_manifest, prepare_manifest, receipt_from_dict, safe_path, write_manifest


def receipt():
    return AudioPreparationReceipt("a" * 64, "b" * 64, 48000, 1440000, 48000, 661500, 480000, "ffmpeg version fixture", (("ffmpeg", "arg1"), ("ffmpeg", "arg2")), "w05-pcm-r2", .5)


@pytest.mark.parametrize("field", ["source_frames", "basic_frames", "piano_frames", "ffmpeg_version", "argv", "pcm_revision", "elapsed_sec"])
def test_missing_audio_receipt_refuses_freeze(field):
    value = json.loads(canonical_json(asdict(receipt())))
    del value[field]
    with pytest.raises(ValueError): receipt_from_dict(value)


def test_receipt_roundtrip_and_invalid_frames():
    value = json.loads(canonical_json(asdict(receipt())))
    assert receipt_from_dict(value) == receipt()
    value["basic_frames"] = True
    with pytest.raises(ValueError): receipt_from_dict(value)


@pytest.mark.parametrize("path", ["../escape", "C:/drive", "/root", "dir\\escape", "dir/../escape", "a:stream", "CON/file", "dir/file."])
def test_manifest_path_escape_or_windows_alias_rejected(tmp_path, path):
    with pytest.raises(ValueError): safe_path(tmp_path, path)


def test_canonical_json_nonfinite_and_duplicate_keys():
    with pytest.raises(ValueError): canonical_json({"x": float("nan")})
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_manifest_full_prepare_roundtrip_and_tamper(tmp_path):
    import asyncio
    import hashlib
    import shutil
    from pathlib import Path
    import mido
    import numpy as np
    import soundfile as sf
    from musicsheet_transcription_eval.dataset import select_recordings
    executable = shutil.which("ffmpeg")
    if not executable: pytest.skip("FFmpeg not installed")
    rows = [dict(audio_filename=f"2018/fixture-{i:02}.wav", midi_filename=f"2018/fixture-{i:02}.midi", duration=90., split="test") for i in range(13)]
    selected = select_recordings(rows, rows)
    root, members = tmp_path / "run", {}
    source = root / "source"
    source.joinpath("2018").mkdir(parents=True)
    root.joinpath("metadata").mkdir()
    metadata = canonical_json(rows)
    for version in ("v3.0.0", "v2.0.0"): root.joinpath(f"metadata/{version}.json").write_bytes(metadata)
    metadata_hash = hashlib.sha256(metadata).hexdigest()
    for row in selected:
        audio, midi = source / row["audio_filename"], source / row["midi_filename"]
        sf.write(audio, np.zeros((90000, 2), dtype=np.int16), 1000, subtype="PCM_16")
        file = mido.MidiFile(ticks_per_beat=1000)
        track, previous = mido.MidiTrack(), 0
        for second in range(1, 89, 2):
            onset, offset = second * 2000, second * 2000 + 1000
            track.append(mido.Message("note_on", note=60, velocity=80, time=onset - previous))
            track.append(mido.Message("note_off", note=60, time=offset - onset)); previous = offset
        file.tracks.append(track); file.save(midi)
        for path, name in ((audio, row["audio_filename"]), (midi, row["midi_filename"])):
            members[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size, "crc32": __import__("zlib").crc32(path.read_bytes())}
    source_receipt = {"schema_version": 1, "source_url": "https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0.zip", "license": "CC-BY-NC-SA-4.0", "integrity": "partial_zip_crc_sha256", "archive_sha256": None, "archive_bytes": 9999999, "archive_etag": '"fixture"', "transferred_bytes": 100, "decoded_bytes": sum(member["bytes"] for member in members.values()), "members": members}
    manifest = asyncio.run(prepare_manifest(selected, source_root=source, output_root=root, metadata_hashes={"v3": metadata_hash, "v2": metadata_hash}, source_receipt=source_receipt, ffmpeg=Path(executable), cancellation=asyncio.Event()))
    target = tmp_path / "manifest.json"
    digest = write_manifest(manifest, target)
    assert len(digest) == 64
    loaded = load_manifest(target, run_root=root)
    assert len(loaded.entries) == 12
    assert loaded.entries[0].basic_audio.is_absolute()
    import threading
    stopped = threading.Event(); stopped.set()
    with pytest.raises(InterruptedError): load_manifest(target, run_root=root, stop=stopped)
    wrapper = json.loads(target.read_bytes())
    assert "notes" not in target.read_text()
    wrapper["manifest"]["entries"][0]["start_sec"] += 1
    target.write_bytes(canonical_json(wrapper))
    with pytest.raises(ValueError): load_manifest(target, run_root=root)
    write_manifest(manifest, target)
    wrapper = json.loads(target.read_bytes())
    wrapper["manifest"]["entries"][0]["audio_receipt"]["mono_sha256"] = "0" * 64
    wrapper["sha256"] = hashlib.sha256(canonical_json(wrapper["manifest"])).hexdigest()
    target.write_bytes(canonical_json(wrapper))
    with pytest.raises(ValueError): load_manifest(target, run_root=root)
    write_manifest(manifest, target)
    source_midi = source / selected[0]["midi_filename"]
    original_midi = source_midi.read_bytes()
    source_midi.write_bytes(b"tampered original")
    with pytest.raises(ValueError): load_manifest(target, run_root=root)
    source_midi.write_bytes(original_midi)
    root.joinpath("metadata/v2.0.0.json").write_bytes(b"changed metadata")
    with pytest.raises(ValueError): load_manifest(target, run_root=root)
    root.joinpath("metadata/v2.0.0.json").write_bytes(metadata)
    loaded.entries[0].basic_audio.write_bytes(b"tampered")
    with pytest.raises(ValueError): load_manifest(target, run_root=root)
