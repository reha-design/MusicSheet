"""Local filesystem implementation of the artifact storage interface."""

from pathlib import Path, PureWindowsPath
from typing import BinaryIO

from musicsheet_common.schemas.artifacts import ArtifactRef, ArtifactRole

from musicsheet_storage.base import ArtifactStorage


class LocalStorage(ArtifactStorage):
    """Store each job's artifacts in a separate directory under ``base_dir``."""

    def __init__(self, base_dir: Path | str = "outputs") -> None:
        self.base_dir = Path(base_dir).expanduser().resolve()

    def _resolve_job_dir(self, job_id: str) -> Path:
        job_id = _validate_path_segment(job_id, "job_id")
        job_dir = (self.base_dir / job_id).resolve()
        _require_within(job_dir, self.base_dir, "job_id")

        job_dir.mkdir(parents=True, exist_ok=True)
        job_dir = job_dir.resolve()
        _require_within(job_dir, self.base_dir, "job_id")
        return job_dir

    def _resolve_file_path(self, job_id: str, filename: str) -> Path:
        filename = _validate_path_segment(filename, "filename")
        job_dir = self._resolve_job_dir(job_id)
        file_path = (job_dir / filename).resolve()
        _require_within(file_path, job_dir, "filename")
        return file_path

    def put(
        self,
        job_id: str,
        filename: str,
        role: ArtifactRole,
        source: BinaryIO | Path,
        producer: str,
        producer_version: str,
    ) -> ArtifactRef:
        raise NotImplementedError("LocalStorage.put is implemented in Step 2 of the plan")

    def open_read(self, artifact: ArtifactRef) -> BinaryIO:
        raise NotImplementedError(
            "LocalStorage.open_read is implemented in Step 3 of the plan"
        )

    def exists(self, artifact: ArtifactRef) -> bool:
        raise NotImplementedError("LocalStorage.exists is implemented in Step 3 of the plan")

    def materialize(self, artifact: ArtifactRef, temp_dir: Path) -> Path:
        raise NotImplementedError(
            "LocalStorage.materialize is implemented in Step 4 of the plan"
        )


def _validate_path_segment(value: str, name: str) -> str:
    """Require one safe filesystem path segment, independent of host syntax."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError(f"{name} must be a non-empty path segment")
    if "\x00" in value:
        raise ValueError(f"{name} cannot contain a null byte")

    windows_path = PureWindowsPath(value)
    if (
        "/" in value
        or "\\" in value
        or windows_path.drive
        or windows_path.root
        or Path(value).is_absolute()
    ):
        raise ValueError(f"{name} must not contain a path or drive component")
    return value


def _require_within(path: Path, parent: Path, name: str) -> None:
    """Reject resolved paths that leave their intended storage directory."""
    try:
        path.relative_to(parent)
    except ValueError as error:
        raise ValueError(f"{name} resolves outside the storage directory") from error
