"""ProjectViewModel — project info + settings for the Project Properties panel.

Qt-free. Wraps :class:`ProjectManager` and exposes project metadata and
:class:`ProjectSettings` as editable snapshots. Setting mutations go
through the manager's ``mark_modified`` so dirty tracking and history
stay on the event bus.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from projectionai.domain.project import Project, RecentProject
from projectionai.managers.project_manager import ProjectManager
from projectionai.ui.viewmodels.observable import Observable

_logger = logging.getLogger(__name__)

#: Keys of :class:`ProjectSettings` surfaced by this viewmodel.
_SETTING_KEYS: tuple[str, ...] = (
    "resolution_width",
    "resolution_height",
    "framerate",
    "color_space",
    "default_ai_provider",
    "default_generation_prompt",
    "grid_enabled",
    "snap_to_grid",
    "grid_size",
)


class ProjectViewModel(Observable):
    """Observable project facade."""

    def __init__(self, project_manager: ProjectManager) -> None:
        super().__init__()
        self._projects = project_manager

    # -- Project state ---------------------------------------------------------

    def current(self) -> Project | None:
        """The currently open project, or ``None``."""
        return self._projects.current

    @property
    def is_open(self) -> bool:
        """True when a project is open."""
        return self._projects.is_open

    @property
    def is_dirty(self) -> bool:
        """True when the open project has unsaved changes."""
        return self._projects.is_dirty

    @property
    def name(self) -> str:
        """Name of the open project (``""`` when closed)."""
        project = self._projects.current
        return project.name if project is not None else ""

    @property
    def project_path(self) -> Path | None:
        """Path of the open project, or ``None``."""
        return self._projects.project_path

    def recent_projects(self) -> list[RecentProject]:
        """Recently opened projects."""
        return self._projects.recent_projects

    # -- Settings ----------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        """Snapshot of the open project's settings (empty dict when closed)."""
        project = self._projects.current
        if project is None:
            return {}
        return {key: getattr(project.settings, key) for key in _SETTING_KEYS}

    def update_setting(self, key: str, value: Any) -> bool:
        """Update one project setting; returns False when invalid/closed."""
        project = self._projects.current
        if project is None or key not in _SETTING_KEYS:
            return False
        try:
            setattr(project.settings, key, value)
        except (TypeError, ValueError):
            return False
        self._projects.mark_modified(description=f"Changed {key}")
        self._notify()
        return True

    # -- Lifecycle -----------------------------------------------------------------

    def create_project(self, name: str, path: Path) -> Project | None:
        """Create a new project; returns it, or ``None`` on failure."""
        try:
            project = self._projects.create_project(name, path)
        except ValueError as exc:
            _logger.warning("Failed to create project %r at %s: %s", name, path, exc)
            return None
        self._notify()
        return project

    async def open_project(self, path: Path) -> Project | None:
        """Open a project from disk; returns it, or ``None`` on failure."""
        try:
            project = await self._projects.open_project(path)
        except (FileNotFoundError, ValueError) as exc:
            _logger.warning("Failed to open project at %s: %s", path, exc)
            return None
        self._notify()
        return project

    async def save_project(self) -> bool:
        """Save the current project; returns True on success."""
        try:
            await self._projects.save_project()
        except ValueError as exc:
            _logger.warning("Failed to save project: %s", exc)
            return False
        self._notify()
        return True

    def close_project(self) -> bool:
        """Close the current project; returns False when dirty."""
        try:
            self._projects.close_project()
        except ValueError as exc:
            _logger.warning("Failed to close project: %s", exc)
            return False
        self._notify()
        return True

    def mark_modified(self, description: str = "") -> None:
        """Mark the project as modified (call after external changes)."""
        self._projects.mark_modified(description)
        self._notify()
