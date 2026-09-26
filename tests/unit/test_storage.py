from pathlib import Path

import pytest

from musicsheet_common.schemas.artifacts import ArtifactRole
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

