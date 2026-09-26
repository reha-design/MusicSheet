import hashlib
import io
import uuid
from pathlib import Path

import pytest

from musicsheet_common.schemas.artifacts import ArtifactRef, ArtifactRole
from musicsheet_storage import ArtifactStorage, LocalStorage


def test_storage_scaffold_and_base_interface() -> None:
    assert ArtifactStorage.__abstractmethods__ == {
        "put",
        "open_read",
        "exists",
        "materialize",
    }
    with pytest.raises(TypeError):
        ArtifactStorage()

    storage = LocalStorage()
    assert isinstance(storage, ArtifactStorage)
    assert ArtifactRole.MIDI.value == "MIDI"


def test_local_storage_path_resolution_creates_job_directory(tmp_path: Path) -> None:
    base_dir = tmp_path / "outputs"
    storage = LocalStorage(base_dir)

    job_dir = storage._resolve_job_dir("job-001")
    file_path = storage._resolve_file_path("job-001", "canonical.wav")

    assert job_dir == (base_dir / "job-001").resolve()
    assert job_dir.is_dir()
    assert file_path == job_dir / "canonical.wav"
    assert file_path.parent == job_dir


@pytest.mark.parametrize("job_id", ["../outside", "..\\outside", "nested/job", "nested\\job", ".", ""])
def test_local_storage_rejects_unsafe_job_ids(tmp_path: Path, job_id: str) -> None:
    storage = LocalStorage(tmp_path / "outputs")

    with pytest.raises(ValueError):
        storage._resolve_job_dir(job_id)


@pytest.mark.parametrize(
    "filename",
    ["../outside.wav", "..\\outside.wav", "nested/file.wav", "nested\\file.wav", ".", ""],
)
def test_local_storage_rejects_unsafe_filenames(tmp_path: Path, filename: str) -> None:
    storage = LocalStorage(tmp_path / "outputs")

    with pytest.raises(ValueError):
        storage._resolve_file_path("job-001", filename)


def test_local_storage_rejects_absolute_paths(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "outputs")

    with pytest.raises(ValueError):
        storage._resolve_job_dir(str(tmp_path.parent))
    with pytest.raises(ValueError):
        storage._resolve_file_path("job-001", str(tmp_path / "outside.wav"))


def test_local_storage_rejects_job_directory_symlink_escape(tmp_path: Path) -> None:
    base_dir = tmp_path / "outputs"
    base_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    job_link = base_dir / "job-001"

    try:
        job_link.symlink_to(outside_dir, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")

    storage = LocalStorage(base_dir)
    with pytest.raises(ValueError):
        storage._resolve_job_dir("job-001")


def test_local_storage_put_replaces_in_job_file_symlink_without_changing_target(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    job_dir = base_dir / "job-001"
    job_dir.mkdir(parents=True)
    canonical_file = job_dir / "canonical.wav"
    canonical_file.write_bytes(b"canonical audio")
    separated_file = job_dir / "separated_piano.wav"

    try:
        separated_file.symlink_to(canonical_file)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"file symlinks are unavailable: {error}")

    storage = LocalStorage(base_dir)
    artifact = storage.put(
        "job-001",
        "separated_piano.wav",
        ArtifactRole.SEPARATED_AUDIO,
        io.BytesIO(b"separated audio"),
        "separator",
        "1.0",
    )

    assert canonical_file.read_bytes() == b"canonical audio"
    assert separated_file.is_file()
    assert not separated_file.is_symlink()
    assert separated_file.read_bytes() == b"separated audio"
    assert artifact.uri == separated_file.as_uri()


def test_local_storage_put_rejects_file_symlink_escape(tmp_path: Path) -> None:
    base_dir = tmp_path / "outputs"
    job_dir = base_dir / "job-001"
    job_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.wav"
    outside_file.write_bytes(b"outside audio")
    link = job_dir / "external.wav"

    try:
        link.symlink_to(outside_file)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"file symlinks are unavailable: {error}")

    storage = LocalStorage(base_dir)
    with pytest.raises(ValueError):
        storage.put(
            "job-001",
            "external.wav",
            ArtifactRole.MODEL_INPUT,
            io.BytesIO(b"replacement"),
            "transcriber",
            "1.0",
        )

    assert outside_file.read_bytes() == b"outside audio"
    assert link.is_symlink()


def test_local_storage_put_writes_to_symlink_name_not_resolved_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "outputs"
    job_dir = base_dir / "job-001"
    job_dir.mkdir(parents=True)
    canonical_file = job_dir / "canonical.wav"
    canonical_file.write_bytes(b"canonical audio")
    separated_file = job_dir / "separated_piano.wav"
    separated_file.write_bytes(b"old alias content")
    storage = LocalStorage(base_dir)
    original_is_symlink = Path.is_symlink
    original_resolve = Path.resolve

    def fake_is_symlink(path: Path) -> bool:
        if path == separated_file:
            return True
        return original_is_symlink(path)

    def fake_resolve(path: Path, strict: bool = False) -> Path:
        if path == separated_file:
            return canonical_file
        return original_resolve(path, strict=strict)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "is_symlink", fake_is_symlink)
        patcher.setattr(Path, "resolve", fake_resolve)
        artifact = storage.put(
            "job-001",
            "separated_piano.wav",
            ArtifactRole.SEPARATED_AUDIO,
            io.BytesIO(b"separated audio"),
            "separator",
            "1.0",
        )

    assert canonical_file.read_bytes() == b"canonical audio"
    assert separated_file.read_bytes() == b"separated audio"
    assert artifact.uri == separated_file.as_uri()


def test_local_storage_put_from_path_copies_bytes_and_returns_metadata(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    source = tmp_path / "incoming" / "piano.wav"
    source.parent.mkdir()
    payload = b"RIFF\x00\x00\x00\x00WAVEtest audio"
    source.write_bytes(payload)
    storage = LocalStorage(base_dir)

    artifact = storage.put(
        "job-002",
        "canonical.wav",
        ArtifactRole.CANONICAL_AUDIO,
        source,
        "audio-normalizer",
        "2.1",
    )

    destination = base_dir / "job-002" / "canonical.wav"
    assert destination.read_bytes() == payload
    assert uuid.UUID(artifact.id).version == 4
    assert artifact.job_id == "job-002"
    assert artifact.role is ArtifactRole.CANONICAL_AUDIO
    assert artifact.filename == "canonical.wav"
    assert artifact.uri == destination.resolve().as_uri()
    assert artifact.mime_type == "audio/wav"
    assert artifact.size_bytes == len(payload)
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
    assert artifact.producer == "audio-normalizer"
    assert artifact.producer_version == "2.1"


def test_local_storage_put_reads_binary_stream_in_bounded_chunks(
    tmp_path: Path,
) -> None:
    class RecordingStream(io.BytesIO):
        def __init__(self, contents: bytes) -> None:
            super().__init__(contents)
            self.requested_sizes: list[int] = []

        def read(self, size: int = -1) -> bytes:
            self.requested_sizes.append(size)
            return super().read(size)

    payload = bytes(range(256)) * 700
    source = RecordingStream(payload)
    storage = LocalStorage(tmp_path / "outputs")

    artifact = storage.put(
        "job-003",
        "raw.bin",
        ArtifactRole.MODEL_INPUT,
        source,
        "transcriber",
        "0.4",
    )

    destination = tmp_path / "outputs" / "job-003" / "raw.bin"
    assert destination.read_bytes() == payload
    assert source.closed is False
    assert source.requested_sizes
    assert all(0 < size <= 64 * 1024 for size in source.requested_sizes)
    assert artifact.size_bytes == len(payload)
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()


def test_local_storage_put_removes_partial_file_after_source_failure(
    tmp_path: Path,
) -> None:
    class FailingStream:
        def __init__(self) -> None:
            self.read_count = 0

        def read(self, size: int = -1) -> bytes:
            self.read_count += 1
            if self.read_count == 1:
                return b"partial data"
            raise OSError("source read failed")

    base_dir = tmp_path / "outputs"
    storage = LocalStorage(base_dir)

    with pytest.raises(OSError, match="source read failed"):
        storage.put(
            "job-004",
            "broken.wav",
            ArtifactRole.MODEL_INPUT,
            FailingStream(),  # type: ignore[arg-type]
            "transcriber",
            "0.4",
        )

    assert list((base_dir / "job-004").iterdir()) == []


def test_local_storage_exists_and_open_read_use_artifact_uri(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "outputs")
    payload = b"stored artifact contents"
    artifact = storage.put(
        "job-005",
        "result.mid",
        ArtifactRole.MIDI,
        io.BytesIO(payload),
        "midi-writer",
        "1.0",
    )

    assert storage.exists(artifact) is True
    with storage.open_read(artifact) as stream:
        assert stream.read() == payload


def test_local_storage_missing_artifact_is_false_and_cannot_be_opened(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    storage = LocalStorage(base_dir)
    artifact = storage.put(
        "job-006",
        "result.mid",
        ArtifactRole.MIDI,
        io.BytesIO(b"contents"),
        "midi-writer",
        "1.0",
    )
    (base_dir / "job-006" / "result.mid").unlink()

    assert storage.exists(artifact) is False
    with pytest.raises(FileNotFoundError):
        storage.open_read(artifact)


def test_local_storage_rejects_artifact_uri_outside_base_directory(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(tmp_path / "outputs")
    artifact = storage.put(
        "job-007",
        "result.mid",
        ArtifactRole.MIDI,
        io.BytesIO(b"stored contents"),
        "midi-writer",
        "1.0",
    )
    outside_file = tmp_path / "outside.mid"
    outside_file.write_bytes(b"private contents")
    forged_artifact = artifact.model_copy(update={"uri": outside_file.as_uri()})

    with pytest.raises(ValueError, match="artifact URI"):
        storage.exists(forged_artifact)
    with pytest.raises(ValueError, match="artifact URI"):
        storage.open_read(forged_artifact)


def test_local_storage_rejects_uri_that_points_to_another_stored_artifact(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    storage = LocalStorage(base_dir)
    artifact = storage.put(
        "job-008",
        "result.mid",
        ArtifactRole.MIDI,
        io.BytesIO(b"public result"),
        "midi-writer",
        "1.0",
    )
    other_file = base_dir / "job-009" / "private.mid"
    other_file.parent.mkdir()
    other_file.write_bytes(b"private artifact")
    forged_artifact = artifact.model_copy(update={"uri": other_file.as_uri()})

    with pytest.raises(ValueError, match="does not match"):
        storage.exists(forged_artifact)


def test_local_storage_read_of_unknown_artifact_does_not_create_job_directory(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    missing_job_dir = base_dir / "missing-job"
    artifact = ArtifactRef(
        id="artifact-001",
        job_id="missing-job",
        role=ArtifactRole.MODEL_INPUT,
        filename="missing.wav",
        uri=(missing_job_dir / "missing.wav").as_uri(),
        mime_type="audio/wav",
        size_bytes=0,
        sha256="0" * 64,
        producer="transcriber",
        producer_version="1.0",
    )
    storage = LocalStorage(base_dir)

    assert storage.exists(artifact) is False
    with pytest.raises(FileNotFoundError):
        storage.open_read(artifact)
    assert not missing_job_dir.exists()


def test_local_storage_materialize_creates_path_under_temp_directory(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    temp_dir = tmp_path / "materialized"
    storage = LocalStorage(base_dir)
    artifact = storage.put(
        "job-010",
        "result.pdf",
        ArtifactRole.PDF,
        io.BytesIO(b"pdf data"),
        "score-renderer",
        "1.0",
    )

    materialized_path = storage.materialize(artifact, temp_dir)
    source_path = (base_dir / "job-010" / "result.pdf").resolve()

    assert materialized_path.is_relative_to(temp_dir.resolve())
    assert materialized_path != source_path
    assert materialized_path.is_file()
    assert materialized_path.read_bytes() == b"pdf data"
    if materialized_path.is_symlink():
        assert materialized_path.resolve() == source_path
    assert temp_dir.is_dir()
    assert list((base_dir / "job-010").iterdir()) == [source_path]


def test_local_storage_materialize_copies_when_symlinks_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "outputs"
    temp_dir = tmp_path / "materialized"
    storage = LocalStorage(base_dir)
    artifact = storage.put(
        "job-012",
        "result.pdf",
        ArtifactRole.PDF,
        io.BytesIO(b"pdf data"),
        "score-renderer",
        "1.0",
    )

    def reject_symlink(
        path: Path,
        target: Path,
        target_is_directory: bool = False,
    ) -> None:
        raise OSError("symlinks are unavailable")

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "symlink_to", reject_symlink)
        materialized_path = storage.materialize(artifact, temp_dir)

    assert materialized_path.is_relative_to(temp_dir.resolve())
    assert materialized_path.is_file()
    assert not materialized_path.is_symlink()
    assert materialized_path.read_bytes() == b"pdf data"


def test_local_storage_materialize_raises_for_missing_artifact(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "outputs"
    storage = LocalStorage(base_dir)
    artifact = storage.put(
        "job-011",
        "result.pdf",
        ArtifactRole.PDF,
        io.BytesIO(b"pdf data"),
        "score-renderer",
        "1.0",
    )
    (base_dir / "job-011" / "result.pdf").unlink()

    temp_dir = tmp_path / "materialized"
    with pytest.raises(FileNotFoundError):
        storage.materialize(artifact, temp_dir)
    assert not temp_dir.exists()


def test_local_storage_materialize_rejects_uri_outside_base_directory(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(tmp_path / "outputs")
    artifact = storage.put(
        "job-013",
        "result.pdf",
        ArtifactRole.PDF,
        io.BytesIO(b"pdf data"),
        "score-renderer",
        "1.0",
    )
    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(b"outside data")
    forged_artifact = artifact.model_copy(update={"uri": outside_file.as_uri()})

    with pytest.raises(ValueError, match="artifact URI"):
        storage.materialize(forged_artifact, tmp_path / "materialized")
