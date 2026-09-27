"""Storage interface shared by local and remote artifact backends."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from musicsheet_common.schemas.artifacts import ArtifactRef, ArtifactRole


class ArtifactStorage(ABC):
    """Common interface for storing and reading job artifacts."""

    @abstractmethod
    def put(
        self,
        job_id: str,
        filename: str,
        role: ArtifactRole,
        source: BinaryIO | Path,
        producer: str,
        producer_version: str,
    ) -> ArtifactRef:
        """Store an artifact and return its metadata reference."""

    @abstractmethod
    def open_read(self, artifact: ArtifactRef) -> BinaryIO:
        """Open an artifact as a read-only binary stream."""

    @abstractmethod
    def exists(self, artifact: ArtifactRef) -> bool:
        """Return whether the referenced artifact exists."""

    @abstractmethod
    def materialize(self, artifact: ArtifactRef, temp_dir: Path) -> Path:
        """Return a local filesystem path usable by external tools."""
