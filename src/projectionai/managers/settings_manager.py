"""Settings manager — strongly-typed application settings with persistence.

Wraps the Pydantic-based ``AppConfig`` and adds:
- Per-category settings (scene, rendering, calibration, workspace, jobs)
- File-based persistence (JSON/YAML) for user-modified settings
- Change event emission via the event bus
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, override

from pydantic import BaseModel, ConfigDict

from projectionai.core.config import AppConfig, load_config
from projectionai.core.events import EventBus, SettingsChanged
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings sub-models (extend AppConfig with manager-specific settings)
# ---------------------------------------------------------------------------


class SceneSettings(BaseModel):
    """Settings for scene graph behaviour."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    default_node_name: str = "Node"
    max_undo_states: int = 256
    auto_backup_interval_seconds: int = 300


class RenderingSettings(BaseModel):
    """Settings for the rendering pipeline."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    target_fps: int = 60
    resolution_width: int = 1920
    resolution_height: int = 1080
    vsync: bool = True
    msaa_samples: int = 4


class CalibrationSettings(BaseModel):
    """Settings for calibration processes."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    default_pattern: str = "checkerboard"
    pattern_width: int = 9
    pattern_height: int = 6
    square_size_mm: float = 30.0
    min_images: int = 10


class WorkspaceSettingsModel(BaseModel):
    """Settings for workspace layout and behaviour."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    autosave_enabled: bool = True
    autosave_interval_seconds: int = 120
    show_grid: bool = True
    snap_to_grid: bool = False
    grid_size: float = 1.0


class JobSettings(BaseModel):
    """Settings for the background job system."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    max_concurrent_jobs: int = 4
    queue_capacity: int = 100
    default_timeout_seconds: int = 300


# ---------------------------------------------------------------------------
# SettingsManager
# ---------------------------------------------------------------------------


class SettingsManager(Manager):
    """Manages strongly-typed application settings with persistence.

    Combines the environment-based ``AppConfig`` with Pydantic sub-models
    for each manager category. Supports change notification and optional
    JSON persistence for user-modified settings.
    """

    def __init__(
        self,
        event_bus: EventBus,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._app_config: AppConfig = load_config()
        self._settings_path: Path | None = settings_path
        self._dirty: bool = False

        # Per-category settings
        self._scene: SceneSettings = SceneSettings()
        self._rendering: RenderingSettings = RenderingSettings()
        self._calibration: CalibrationSettings = CalibrationSettings()
        self._workspace: WorkspaceSettingsModel = WorkspaceSettingsModel()
        self._jobs: JobSettings = JobSettings()

    # -- Accessors ----------------------------------------------------------

    @property
    def app(self) -> AppConfig:
        """Return the core application config (env-based)."""
        return self._app_config

    @property
    def scene(self) -> SceneSettings:
        """Return scene-related settings."""
        return self._scene

    @property
    def rendering(self) -> RenderingSettings:
        """Return rendering settings."""
        return self._rendering

    @property
    def calibration(self) -> CalibrationSettings:
        """Return calibration settings."""
        return self._calibration

    @property
    def workspace(self) -> WorkspaceSettingsModel:
        """Return workspace settings."""
        return self._workspace

    @property
    def jobs(self) -> JobSettings:
        """Return job system settings."""
        return self._jobs

    @property
    def is_dirty(self) -> bool:
        """Return ``True`` if settings have been modified since last save."""
        return self._dirty

    # -- Mutation -----------------------------------------------------------

    def _apply(self, category: str, **kwargs: Any) -> None:
        """Validate, apply, and emit changes for *category* settings.

        Raises ``ValidationError`` if any key is unknown or any value
        fails type validation.  Unchanged values are skipped — no event
        is emitted and *dirty* is not set unless at least one field
        actually changes.
        """
        attr = f"_{category}"
        old: BaseModel = getattr(self, attr)
        merged = {**old.model_dump(), **kwargs}
        updated = old.__class__.model_validate(merged)
        setattr(self, attr, updated)
        changed = False
        for key in kwargs:
            old_val = getattr(old, key)
            new_val = getattr(updated, key)
            if old_val != new_val:
                self._emit_change(category, key, old_val, new_val)
                changed = True
        if changed:
            self._dirty = True

    def set_scene(self, **kwargs: Any) -> None:
        """Update scene settings fields and emit change events.

        Raises ``ValidationError`` if any key is unknown or any value
        fails type validation.
        """
        self._apply("scene", **kwargs)

    def set_rendering(self, **kwargs: Any) -> None:
        """Update rendering settings fields and emit change events.

        Raises ``ValidationError`` if any key is unknown or any value
        fails type validation.
        """
        self._apply("rendering", **kwargs)

    def set_calibration(self, **kwargs: Any) -> None:
        """Update calibration settings fields and emit change events.

        Raises ``ValidationError`` if any key is unknown or any value
        fails type validation.
        """
        self._apply("calibration", **kwargs)

    def set_workspace(self, **kwargs: Any) -> None:
        """Update workspace settings fields and emit change events.

        Raises ``ValidationError`` if any key is unknown or any value
        fails type validation.
        """
        self._apply("workspace", **kwargs)

    def set_jobs(self, **kwargs: Any) -> None:
        """Update job settings fields and emit change events.

        Raises ``ValidationError`` if any key is unknown or any value
        fails type validation.
        """
        self._apply("jobs", **kwargs)

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        """Save user-modifiable settings to a JSON file."""
        target = path or self._settings_path
        if target is None:
            _logger.warning("No settings path configured — cannot save")
            return

        data = {
            "scene": self._scene.model_dump(),
            "rendering": self._rendering.model_dump(),
            "calibration": self._calibration.model_dump(),
            "workspace": self._workspace.model_dump(),
            "jobs": self._jobs.model_dump(),
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(target))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        self._dirty = False
        _logger.info("Settings saved to %s", target)

    def load(self, path: Path | None = None) -> None:
        """Load user-modifiable settings from a JSON file."""
        target = path or self._settings_path
        if target is None or not target.exists():
            return

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            self._scene = SceneSettings(**data.get("scene", {}))
            self._rendering = RenderingSettings(**data.get("rendering", {}))
            self._calibration = CalibrationSettings(**data.get("calibration", {}))
            self._workspace = WorkspaceSettingsModel(**data.get("workspace", {}))
            self._jobs = JobSettings(**data.get("jobs", {}))
            self._dirty = False
            _logger.info("Settings loaded from %s", target)
        except Exception as exc:
            _logger.warning("Failed to load settings from %s: %s", target, exc)

    # -- Internal -----------------------------------------------------------

    def _emit_change(self, category: str, key: str, old: Any, new: Any) -> None:
        event = SettingsChanged(
            category=category,
            key=key,
            old_value=old,
            new_value=new,
        )
        self._emit_nowait(event)

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        if self._settings_path is not None:
            self.load()

    @override
    async def _on_shutdown(self) -> None:
        if self._dirty and self._settings_path is not None:
            self.save()
