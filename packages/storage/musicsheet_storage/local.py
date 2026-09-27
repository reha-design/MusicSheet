"""Local filesystem implementation of the artifact storage interface."""

import hashlib
import mimetypes
import os
import shutil
import tempfile
from contextlib import nullcontext
from pathlib import Path, PureWindowsPath
from typing import BinaryIO
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import uuid4

from musicsheet_common.schemas.artifacts import ArtifactRef, ArtifactRole

from musicsheet_storage.base import ArtifactStorage

_COPY_CHUNK_SIZE = 64 * 1024


class LocalStorage(ArtifactStorage):
    """Store each job's artifacts in a separate directory under ``base_dir``."""

    def __init__(self, base_dir: Path | str = "outputs") -> None:
        self.base_dir = Path(base_dir).expanduser().resolve()

    def _resolve_job_dir(self, job_id: str, *, create: bool = True) -> Path:
        job_id = _validate_path_segment(job_id, "job_id")
        job_dir = (self.base_dir / job_id).resolve()
        _require_within(job_dir, self.base_dir, "job_id")

        if create:
            job_dir.mkdir(parents=True, exist_ok=True)
            job_dir = job_dir.resolve()
            _require_within(job_dir, self.base_dir, "job_id")
        return job_dir

    def _resolve_file_path(
        self, job_id: str, filename: str, *, create_job_dir: bool = True
    ) -> Path:
        filename = _validate_path_segment(filename, "filename")
        job_dir = self._resolve_job_dir(job_id, create=create_job_dir)
        file_path = (job_dir / filename).resolve()
        _require_within(file_path, job_dir, "filename")
        return file_path

    def _resolve_write_file_path(self, job_id: str, filename: str) -> Path:
        filename = _validate_path_segment(filename, "filename")
        job_dir = self._resolve_job_dir(job_id)
        file_path = job_dir / filename
        if file_path.is_symlink():
            resolved_target = file_path.resolve()
            _require_within(resolved_target, job_dir, "filename")
        if file_path.is_dir():
            raise IsADirectoryError(file_path)
        return file_path

    def _resolve_artifact_path(self, artifact: ArtifactRef) -> Path:
        parsed_uri = urlparse(artifact.uri)
        if (
            parsed_uri.scheme != "file"
            or parsed_uri.netloc not in {"", "localhost"}
            or parsed_uri.params
            or parsed_uri.query
            or parsed_uri.fragment
        ):
            raise ValueError("artifact URI must be a local file URI")

        uri_path = Path(url2pathname(parsed_uri.path)).resolve()
        _require_within(uri_path, self.base_dir, "artifact URI")
        expected_path = self._resolve_file_path(
            artifact.job_id, artifact.filename, create_job_dir=False
        )
        if uri_path != expected_path:
            raise ValueError("artifact URI does not match artifact job_id and filename")
        return uri_path

    def put(
        self,
        job_id: str,
        filename: str,
        role: ArtifactRole,
        source: BinaryIO | Path,
        producer: str,
        producer_version: str,
    ) -> ArtifactRef:
        file_path = self._resolve_write_file_path(job_id, filename)
        source_context = (
            source.open("rb") if isinstance(source, Path) else nullcontext(source)
        )
        temporary_path: Path | None = None
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with source_context as input_stream:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{filename}.",
                    suffix=".tmp",
                    dir=file_path.parent,
                    delete=False,
                ) as output_stream:
                    temporary_path = Path(output_stream.name)
                    while True:
                        chunk = input_stream.read(_COPY_CHUNK_SIZE)
                        if not isinstance(chunk, bytes):
                            raise TypeError("source must be a binary stream")
                        if not chunk:
                            break
                        output_stream.write(chunk)
                        digest.update(chunk)
                        size_bytes += len(chunk)

            os.replace(temporary_path, file_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return ArtifactRef(
            id=str(uuid4()),
            job_id=job_id,
            role=role,
            filename=filename,
            uri=file_path.as_uri(),
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
            producer=producer,
            producer_version=producer_version,
        )

    def open_read(self, artifact: ArtifactRef) -> BinaryIO:
        return self._resolve_artifact_path(artifact).open("rb")

    def exists(self, artifact: ArtifactRef) -> bool:
        return self._resolve_artifact_path(artifact).is_file()

    def materialize(self, artifact: ArtifactRef, temp_dir: Path) -> Path:
        """Create a temporary local path for tools that require a filesystem file."""
        file_path = self._resolve_artifact_path(artifact)
        if not file_path.is_file():
            raise FileNotFoundError(file_path)

        temp_root = Path(temp_dir).expanduser().resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        materialized_dir = Path(tempfile.mkdtemp(prefix="artifact-", dir=temp_root))
        materialized_path = materialized_dir / artifact.filename
        try:
            try:
                materialized_path.symlink_to(file_path)
            except (NotImplementedError, OSError):
                shutil.copyfile(file_path, materialized_path)
            return materialized_path
        except Exception:
            shutil.rmtree(materialized_dir, ignore_errors=True)
            raise


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
