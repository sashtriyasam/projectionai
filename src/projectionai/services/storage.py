"""Storage abstraction.

Abstracts persistence so the domain layer never depends on SQLite
or any specific database driver.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from projectionai.domain.project import Project

# ---------------------------------------------------------------------------
# Repository protocol (interface)
# ---------------------------------------------------------------------------


class ProjectRepository(Protocol):
    """Interface for project CRUD operations."""

    async def save(self, project: Project) -> None:
        """Persist a project — insert or update."""
        ...

    async def load(self, project_id: str) -> Project | None:
        """Load a project by ID."""
        ...

    async def delete(self, project_id: str) -> None:
        """Delete a project by ID."""
        ...

    async def list_projects(self) -> list[Project]:
        """Return all stored projects."""
        ...


# ---------------------------------------------------------------------------
# Storage service
# ---------------------------------------------------------------------------


class StorageService(ABC):
    """High-level storage service.

    Manages:
    - Project files (models, textures, generated content).
    - Metadata database (SQLite via repository).
    - Import / export.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Create data directories, open database connection."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Close database, flush buffers."""

    @property
    @abstractmethod
    def projects(self) -> ProjectRepository:
        """Return the project repository."""

    @abstractmethod
    async def import_project(self, path: Path) -> Project:
        """Import a project from a ``.projectionai`` archive file."""

    @abstractmethod
    async def export_project(self, project: Project, path: Path) -> None:
        """Export a project to a ``.projectionai`` archive file."""

    @abstractmethod
    async def get_asset_path(self, project_id: str, filename: str) -> Path:
        """Return the filesystem path for a project asset."""
