"""Artifact storage interfaces and adapters for MusicSheet."""

from musicsheet_storage.base import ArtifactStorage
from musicsheet_storage.local import LocalStorage

__all__ = ["ArtifactStorage", "LocalStorage"]
