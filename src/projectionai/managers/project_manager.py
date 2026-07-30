"""Project manager — project lifecycle management.

Handles project creation, opening, saving, closing, and recent-file tracking.
Delegates serialization to the persistence layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast, override

from projectionai.core.events import (
    EventBus,
    ProjectClosed,
    ProjectCreated,
    ProjectModified,
    ProjectOpened,
    ProjectSaved,
)
from projectionai.domain.project import (
    HistoryEntryType,
    Project,
    ProjectMetadata,
    ProjectSettings,
    RecentProject,
)
from projectionai.domain.scene import Scene
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class ProjectManager(Manager):
    """Manages the current project lifecycle.

    Supports one active project at a time. Provides save/load/open/close
    operations and tracks a recent-projects list.
    """

    def __init__(
        self,
        event_bus: EventBus,
        recent_projects_path: Path | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._project: Project | None = None
        self._recent_projects: list[RecentProject] = []
        self._recent_projects_path: Path | None = recent_projects_path
        self._project_dir: Path | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def current(self) -> Project | None:
        """Return the currently open project, or ``None``."""
        return self._project

    @property
    def is_open(self) -> bool:
        """Return ``True`` if a project is currently open."""
        return self._project is not None

    @property
    def is_dirty(self) -> bool:
        """Return ``True`` if the current project has unsaved changes."""
        return self._project is not None and self._project.is_dirty

    @property
    def project_path(self) -> Path | None:
        """Return the path to the current project, or ``None``."""
        if self._project is None:
            return None
        return self._project.path

    @property
    def recent_projects(self) -> list[RecentProject]:
        """Return the list of recently opened projects."""
        return list(self._recent_projects)

    # -- Project lifecycle --------------------------------------------------

    def create_project(
        self,
        name: str,
        path: Path,
        metadata: ProjectMetadata | None = None,
        settings: ProjectSettings | None = None,
        *,
        force: bool = False,
    ) -> Project:
        """Create a new project.

        If a project is currently open, it is closed first (without saving).

        Args:
            name: The project name.
            path: The directory path where the project will be stored.
            metadata: Optional project metadata.
            settings: Optional project settings.
            force: Discard unsaved changes without raising.

        Returns:
            The newly created Project.

        Raises:
            ValueError: If a dirty project is open and ``force`` is not set.
        """
        self._require_initialized()

        if self._project is not None:
            self.close_project(force=force)

        project = Project(
            name=name,
            path=path,
            metadata=metadata or ProjectMetadata(),
            settings=settings or ProjectSettings(),
        )

        # Create a default scene
        scene = Scene(name="Default Scene")
        project.add_scene(scene, make_active=True)

        project.add_history_entry(
            HistoryEntryType.PROJECT_CREATED,
            f"Project '{name}' created",
        )

        self._project = project
        self._project_dir = path
        self._add_recent(path, name)

        _logger.info("Created project: %s at %s", name, path)
        self._emit_nowait(ProjectCreated(project_id=project.id, name=name))
        self._emit_nowait(ProjectOpened(project_id=project.id, path=str(path)))
        return project

    async def open_project(self, path: Path, *, force: bool = False) -> Project:
        """Open an existing project from disk.

        Args:
            path: Path to the ``.projectai`` directory.
            force: Discard unsaved changes in the current project without
                raising.

        Returns:
            The loaded Project.

        Raises:
            FileNotFoundError: If the project path does not exist.
            ValueError: If the project format is invalid, or if the current
                project has unsaved changes and ``force`` is not set.
        """
        self._require_initialized()

        if not path.exists():
            raise FileNotFoundError(f"Project not found: {path}")

        if self._project is not None:
            self.close_project(force=force)

        # Load project data
        project_data = await self._load_from_disk(path)
        project = Project(
            id=project_data.get("id", ""),
            name=project_data.get("name", path.stem),
            path=path,
        )

        # Restore scenes
        for scene_data in project_data.get("scenes", []):
            scene = Scene.from_dict(scene_data)
            project.add_scene(scene)

        active_id = project_data.get("active_scene_id")
        if active_id and active_id in project.scenes:
            project.active_scene_id = str(active_id)

        if "settings" in project_data:
            known = {
                k: v
                for k, v in project_data["settings"].items()
                if k in ProjectSettings.__dataclass_fields__
            }
            try:
                project.settings = ProjectSettings(**known)
            except TypeError as e:
                raise ValueError(f"Invalid project settings: {e}") from e
        if "metadata" in project_data:
            known = {
                k: v
                for k, v in project_data["metadata"].items()
                if k in ProjectMetadata.__dataclass_fields__
            }
            try:
                project.metadata = ProjectMetadata(**known)
            except TypeError as e:
                raise ValueError(f"Invalid project metadata: {e}") from e

        project.mark_saved()

        self._project = project
        self._project_dir = path
        self._add_recent(path, project.name)

        _logger.info("Opened project: %s", path)
        await self._event_bus.emit(ProjectOpened(project_id=project.id, path=str(path)))
        return project

    async def save_project(self, path: Path | None = None) -> None:
        """Save the current project to disk.

        Args:
            path: Optional path override. If omitted, uses the existing path.

        Raises:
            ValueError: If no project is open.
        """
        self._require_initialized()
        if self._project is None:
            raise ValueError("No project is open")

        target = path or self._project.path
        if target is None:
            raise ValueError("No save path specified")

        await self._save_to_disk(self._project, target)
        self._project.path = target
        self._project.mark_saved()

        _logger.info("Saved project to: %s", target)
        self._emit_nowait(ProjectSaved(project_id=self._project.id, path=str(target)))

    def close_project(self, *, force: bool = False) -> None:
        """Close the current project without saving.

        Args:
            force: Discard unsaved changes without raising.

        Raises:
            ValueError: If the project has unsaved changes and ``force`` is
                not set.
        """
        self._require_initialized()
        if self._project is None:
            return
        if self._project.is_dirty and not force:
            raise ValueError("Project has unsaved changes. Use force=True to discard.")
        project_id = self._project.id
        self._close_current()
        _logger.info("Closed project: %s", project_id)
        self._emit_nowait(ProjectClosed(project_id=project_id))

    # -- Dirty tracking -----------------------------------------------------

    def mark_modified(self, description: str = "") -> None:
        """Mark the current project as having unsaved changes.

        Args:
            description: Optional description of the change.
        """
        if self._project is None:
            return
        self._project.mark_modified()
        if description:
            self._project.add_history_entry(
                HistoryEntryType.NOTE,
                description,
            )
        self._emit_nowait(ProjectModified(project_id=self._project.id))

    # -- Recent projects ----------------------------------------------------

    def _add_recent(self, path: Path, name: str) -> None:
        """Add or update a recent-project entry."""
        # Remove existing entry for this path
        self._recent_projects = [rp for rp in self._recent_projects if rp.path != path]
        self._recent_projects.insert(0, RecentProject(path=path, name=name))

        # Keep only the 10 most recent
        if len(self._recent_projects) > 10:
            self._recent_projects = self._recent_projects[:10]

        self._save_recent_projects()

    def _save_recent_projects(self) -> None:
        """Persist the recent-projects list to disk."""
        if self._recent_projects_path is None:
            return
        try:
            data = [
                {
                    "path": str(rp.path),
                    "name": rp.name,
                    "last_opened": rp.last_opened.isoformat(),
                }
                for rp in self._recent_projects
            ]
            self._recent_projects_path.parent.mkdir(parents=True, exist_ok=True)
            self._recent_projects_path.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",  # pyright: ignore[reportUnusedCallResult]
            )
        except Exception as exc:
            _logger.warning("Failed to save recent projects: %s", exc)

    def _load_recent_projects(self) -> None:
        """Load the recent-projects list from disk."""
        if self._recent_projects_path is None:
            return
        if not self._recent_projects_path.exists():
            return
        try:
            data = json.loads(self._recent_projects_path.read_text(encoding="utf-8"))
            self._recent_projects = []
            for item in data:
                kw: dict[str, Any] = {
                    "path": Path(item["path"]),
                    "name": item.get("name", "Unknown"),
                }
                if "last_opened" in item:
                    kw["last_opened"] = datetime.fromisoformat(item["last_opened"])
                self._recent_projects.append(RecentProject(**kw))
        except Exception as exc:
            _logger.warning("Failed to load recent projects: %s", exc)

    # -- Persistence (simple JSON-based, replaced by project_format.py later) -

    async def _load_from_disk(self, path: Path) -> dict[str, Any]:
        """Load project data from a directory.

        Current implementation reads ``project.json`` from the project
        directory. This will be replaced by the proper ``.projectai``
        format reader.
        """
        manifest = path / "project.json"
        exists = await asyncio.to_thread(manifest.exists)
        if not exists:
            raise ValueError(f"Invalid project: missing project.json in {path}")
        raw = await asyncio.to_thread(manifest.read_text, encoding="utf-8")
        return cast("dict[str, Any]", json.loads(raw))

    async def _save_to_disk(self, project: Project, path: Path) -> None:
        """Save project data to disk.

        Current implementation writes ``project.json``. This will be
        replaced by the proper ``.projectai`` format writer.
        """
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        manifest = path / "project.json"

        scenes_data: list[Any] = []
        for scene in project.scenes.values():
            scenes_data.append(scene.to_dict())

        data = {
            "id": project.id,
            "name": project.name,
            "scenes": scenes_data,
            "active_scene_id": project.active_scene_id,
            "settings": {
                "resolution_width": project.settings.resolution_width,
                "resolution_height": project.settings.resolution_height,
                "framerate": project.settings.framerate,
                "color_space": project.settings.color_space,
            },
            "metadata": {
                "author": project.metadata.author,
                "description": project.metadata.description,
                "application_version": project.metadata.application_version,
                "project_format_version": project.metadata.project_format_version,
            },
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        }

        # Atomic write: temp file → os.replace to prevent corruption
        tmp = manifest.with_suffix(".json.tmp")
        await asyncio.to_thread(
            tmp.write_text,
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        await asyncio.to_thread(os.replace, tmp, manifest)

    # -- Internal -----------------------------------------------------------

    def _close_current(self) -> None:
        """Close the current project without saving or emitting events."""
        self._project = None
        self._project_dir = None

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        self._load_recent_projects()
        _logger.debug("ProjectManager initialized")

    @override
    async def _on_shutdown(self) -> None:
        self._save_recent_projects()
        self._project = None
        self._project_dir = None
