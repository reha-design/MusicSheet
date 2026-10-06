import copy
import hashlib
import threading
import zipfile

import pytest

from musicsheet_transcription_eval.dataset import acquire_members, crop_start, select_recordings, selection_digest


def rows():
    return [dict(audio_filename=f"2018/fixture-{i:02}.wav", midi_filename=f"2018/fixture-{i:02}.midi", duration=90., split="test") for i in range(13)]


def test_selection_crop_golden_lf_bytes():
    assert (b"MusicSheet-W05-R1\n" + b"2018/fixture.wav").hex() == "4d7573696353686565742d5730352d52310a323031382f666978747572652e776176"
    assert selection_digest("2018/fixture.wav") == "1cc318bdabf2cfde64049eff51d0cb790c6885259d05886a7a0cbe7bd2044165"
    assert hashlib.sha256(b"MusicSheet-W05-R2-CROP\n2018/fixture.wav").hexdigest() == "98d21397be159b5f8a3bed1b994573b99b91d23c1b99450767ea33742f643046"
    assert crop_start(90., "2018/fixture.wav") == 3


def test_selection_order_golden():
    data = rows()
    selected = select_recordings(data, data)
    assert [row["audio_filename"] for row in selected] == [f"2018/fixture-{i:02}.wav" for i in (3, 10, 11, 12, 5, 9, 7, 4, 8, 0, 1, 2)]
    assert select_recordings(list(reversed(data)), list(reversed(data))) == selected


def test_split_mismatch_ineligible_before_selection():
    v3, v2 = rows(), rows()
    v2[3]["split"] = "train"
    assert "2018/fixture-03.wav" not in [r["audio_filename"] for r in select_recordings(v3, v2)]
    with pytest.raises(ValueError): select_recordings(v3[:12], v2[:12])


@pytest.mark.parametrize("mutation", ["duplicate", "case", "escape", "drive", "nan", "bool"])
def test_invalid_metadata_rejected(mutation):
    data = rows()
    if mutation == "duplicate": data.append(copy.deepcopy(data[0]))
    elif mutation == "case": data[1]["audio_filename"] = data[0]["audio_filename"].upper()
    elif mutation == "escape": data[0]["audio_filename"] = "../outside.wav"
    elif mutation == "drive": data[0]["audio_filename"] = "C:/outside.wav"
    elif mutation == "nan": data[0]["duration"] = float("nan")
    else: data[0]["duration"] = True
    with pytest.raises(ValueError): select_recordings(data, data)


def archive(tmp_path, *, compression=zipfile.ZIP_DEFLATED, extra=None):
    path = tmp_path / "source.zip"
    selected = select_recordings(rows(), rows())
    with zipfile.ZipFile(path, "w", compression=compression) as z:
        for row in selected:
            for field in ("audio_filename", "midi_filename"):
                z.writestr("maestro-v3.0.0/" + row[field], row[field].encode())
        if extra: z.writestr(extra[0], extra[1])
    return path, selected


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_verified_local_archive_and_cached_receipt_no_network(tmp_path, monkeypatch, compression):
    from musicsheet_transcription_eval import dataset
    path, selected = archive(tmp_path, compression=compression)
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 0)
    dest = tmp_path / "stage"
    receipt = acquire_members(selected, source=path, destination=dest, stop=threading.Event())
    assert receipt["integrity"] == "full_archive_sha256"
    assert len(receipt["members"]) == 24
    assert (dest / selected[0]["audio_filename"]).read_bytes() == selected[0]["audio_filename"].encode()
    def forbidden(*args, **kwargs): pytest.fail("cached data used network")
    monkeypatch.setattr(dataset, "RangeReader", forbidden)
    reused = acquire_members(selected, source=dataset.ARCHIVE_URL, destination=dest, stop=threading.Event())
    assert reused["members"] == receipt["members"]
    (dest / selected[0]["midi_filename"]).write_bytes(b"changed")
    with pytest.raises(ValueError): acquire_members(selected, source=dataset.ARCHIVE_URL, destination=dest, stop=threading.Event())


@pytest.mark.parametrize("bad", ["../outside", "maestro-v3.0.0/2018/FIXTURE-03.wav"])
def test_member_case_collision_and_traversal(tmp_path, monkeypatch, bad):
    from musicsheet_transcription_eval import dataset
    path, selected = archive(tmp_path, extra=(bad, b"bad"))
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 0)
    with pytest.raises(ValueError): acquire_members(selected, source=path, destination=tmp_path / "stage", stop=threading.Event())


def test_diskspace_and_cancellation_preserve_completed_files(tmp_path, monkeypatch):
    from musicsheet_transcription_eval import dataset
    path, selected = archive(tmp_path)
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 1 << 100)
    dest = tmp_path / "stage"
    dest.mkdir()
    (dest / "keep").write_bytes(b"keep")
    with pytest.raises(ValueError): acquire_members(selected, source=path, destination=dest, stop=threading.Event())
    stop = threading.Event(); stop.set()
    with pytest.raises(InterruptedError): acquire_members(selected, source=path, destination=dest, stop=stop)
    assert (dest / "keep").read_bytes() == b"keep"
    assert not list(dest.rglob("*.part"))


def test_verified_extracted_directory_can_copy_to_new_destination(tmp_path, monkeypatch):
    from musicsheet_transcription_eval import dataset
    path, selected = archive(tmp_path)
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 0)
    source = tmp_path / "source"
    receipt = acquire_members(selected, source=path, destination=source, stop=threading.Event())
    copied = acquire_members(selected, source=source, destination=tmp_path / "copy", stop=threading.Event())
    assert copied["members"] == receipt["members"]


@pytest.mark.parametrize("kind", ["symlink", "encrypted", "crc", "compression", "member_size", "total_size"])
def test_archive_boundary_rejection_preserves_no_part(tmp_path, monkeypatch, kind):
    import stat
    from musicsheet_transcription_eval import dataset
    path, selected = archive(tmp_path, compression=zipfile.ZIP_STORED)
    if kind in {"symlink", "compression"}:
        with zipfile.ZipFile(path, "a") as z:
            info = zipfile.ZipInfo("maestro-v3.0.0/unsafe")
            if kind == "symlink": info.create_system, info.external_attr = 3, (stat.S_IFLNK | 0o777) << 16
            else: info.compress_type = zipfile.ZIP_BZIP2
            z.writestr(info, b"x")
    elif kind in {"encrypted", "crc"}:
        data = bytearray(path.read_bytes())
        if kind == "encrypted":
            center = data.index(b"PK\x01\x02")
            data[6] |= 1; data[center + 8] |= 1
        else:
            filename_len = int.from_bytes(data[26:28], "little")
            extra_len = int.from_bytes(data[28:30], "little")
            data[30 + filename_len + extra_len] ^= 1
        path.write_bytes(data)
    elif kind == "member_size": monkeypatch.setattr(dataset, "MEMBER_LIMIT", 1)
    else: monkeypatch.setattr(dataset, "DECODED_LIMIT", 1)
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 0)
    dest = tmp_path / "stage"
    with pytest.raises(ValueError): acquire_members(selected, source=path, destination=dest, stop=threading.Event())
    assert not list(dest.rglob("*.part"))


def test_cancel_during_acquisition_preserves_verified_member(tmp_path, monkeypatch):
    from musicsheet_transcription_eval import dataset
    path, selected = archive(tmp_path)
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 0)
    stop = threading.Event()
    original = dataset.shutil.disk_usage
    dest = tmp_path / "stage"
    def usage(root):
        if (dest / selected[0]["audio_filename"]).exists(): stop.set()
        return original(root)
    monkeypatch.setattr(dataset.shutil, "disk_usage", usage)
    with pytest.raises(InterruptedError): acquire_members(selected, source=path, destination=dest, stop=stop)
    assert (dest / selected[0]["audio_filename"]).read_bytes() == selected[0]["audio_filename"].encode()
    assert not list(dest.rglob("*.part"))


def test_column_metadata_and_receipt_missing_field(tmp_path, monkeypatch):
    from musicsheet_transcription_eval import dataset
    from musicsheet_transcription_eval.manifest import canonical_json
    data = rows()
    columns = {field: {str(i): row[field] for i, row in enumerate(data)} for field in data[0]}
    assert select_recordings(dataset.metadata_rows(canonical_json(columns)), data) == select_recordings(data, data)
    columns["split"].pop("0")
    with pytest.raises(ValueError): dataset.metadata_rows(canonical_json(columns))
    path, selected = archive(tmp_path)
    monkeypatch.setattr(dataset, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(dataset, "MIN_FREE", 0)
    receipt = acquire_members(selected, source=path, destination=tmp_path / "source", stop=threading.Event())
    del receipt["license"]
    with pytest.raises(ValueError): dataset.validate_source_receipt(receipt, selected)
