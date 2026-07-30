"""Project model — the top-level persistent unit.

A project contains scenes, assets, calibration data, settings, and history.
The on-disk representation uses the ``.projectai`` format (a structured
directory), but the API abstracts over that — consumers work with the
``Project`` object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from projectionai.domain.scene import Scene

# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------


@dataclass
class ProjectMetadata:
    """Immutable-like metadata about a project.

    Created once, updated on save. Not intended for per-edit changes.
    """

    author: str = ""
    company: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    thumbnail_path: Path | None = None

    # Software version that created this project
    application_version: str = "0.1.0"
    project_format_version: str = "1.0.0"

    # Custom metadata (extensible)
    custom: dict[str, object] = field(default_factory=dict)


@dataclass
class ProjectSettings:
    """Per-project settings overrides.

    These override global settings for the duration of the project.
    """

    resolution_width: int = 1920
    resolution_height: int = 1080
    framerate: float = 30.0
    color_space: str = "sRGB"

    # Project-specific AI settings
    default_ai_provider: str = ""
    default_generation_prompt: str = ""

    # Canvas / workspace
    grid_enabled: bool = True
    snap_to_grid: bool = False
    grid_size: float = 1.0

    # Custom overrides
    overrides: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Project history entry
# ---------------------------------------------------------------------------


class HistoryEntryType(Enum):
    """Category of a history entry."""

    PROJECT_CREATED = "project_created"
    SCENE_ADDED = "scene_added"
    SCENE_REMOVED = "scene_removed"
    ASSET_IMPORTED = "asset_imported"
    ASSET_REMOVED = "asset_removed"
    CALIBRATION_RAN = "calibration_ran"
    GENERATION_RAN = "generation_ran"
    EXPORT_RAN = "export_ran"
    SETTINGS_CHANGED = "settings_changed"
    NOTE = "note"


@dataclass
class HistoryEntry:
    """An audit-log entry recording a significant project event."""

    type: HistoryEntryType
    description: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    user: str = ""
    details: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Recent project
# ---------------------------------------------------------------------------


@dataclass
class RecentProject:
    """A recently opened project (for the recent-files list)."""

    path: Path
    name: str
    last_opened: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """A ProjectionAI project.

    This is the top-level unit of work. A project contains:
    - One or more scenes
    - Assets (images, meshes, materials, …)
    - Calibration data
    - Settings and metadata
    - History log

    The on-disk format is a ``.projectai`` directory. The class itself
    is the in-memory representation.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    name: str = "Untitled Project"

    # File info
    path: Path | None = None
    is_dirty: bool = False

    # Scenes
    scenes: dict[str, Scene] = field(default_factory=dict)
    active_scene_id: str | None = None

    # Settings
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    # Metadata
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)

    # History / audit log
    history: list[HistoryEntry] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # ------------------------------------------------------------------
    # Scene management
    # ------------------------------------------------------------------

    def add_scene(self, scene: Scene, make_active: bool = False) -> None:
        """Add a scene to the project.

        If *make_active* is ``True`` (or this is the first scene), it
        becomes the active scene.
        """
        self.scenes[scene.id] = scene
        if self.active_scene_id is None or make_active:
            self.active_scene_id = scene.id
        self.touch()

    def remove_scene(self, scene_id: str) -> None:
        """Remove a scene from the project."""
        _ = self.scenes.pop(scene_id, None)
        if self.active_scene_id == scene_id:
            # Switch to the first available scene
            self.active_scene_id = next(iter(self.scenes), None)
        self.touch()

    @property
    def active_scene(self) -> Scene | None:
        """Return the currently active scene, or ``None``."""
        if self.active_scene_id is None:
            return None
        return self.scenes.get(self.active_scene_id)

    @active_scene.setter
    def active_scene(self, scene: Scene) -> None:
        """Set the active scene."""
        if scene.id in self.scenes:
            self.active_scene_id = scene.id
        else:
            self.scenes[scene.id] = scene
            self.active_scene_id = scene.id

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def add_history_entry(
        self,
        entry_type: HistoryEntryType,
        description: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Append a history entry."""
        self.history.append(
            HistoryEntry(
                type=entry_type,
                description=description,
                details=details or {},
            )
        )

    # ------------------------------------------------------------------
    # Dirty tracking
    # ------------------------------------------------------------------

    def mark_saved(self) -> None:
        """Clear the dirty flag after a successful save."""
        self.is_dirty = False

    def mark_modified(self) -> None:
        """Mark the project as having unsaved changes."""
        if not self.is_dirty:
            self.is_dirty = True
        self.touch()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def touch(self) -> None:
        """Mark the project as recently modified."""
        self.updated_at = datetime.now(UTC)
        self.is_dirty = True
