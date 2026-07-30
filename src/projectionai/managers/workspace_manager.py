"""Workspace manager — UI layout and panel state persistence.

Manages workspace layouts, panel visibility, and workspace settings.
Emits events when the layout changes so the UI can react.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, override

from projectionai.core.events import (
    EventBus,
    WorkspaceLayoutChanged,
    WorkspaceSettingsChanged,
)
from projectionai.domain.workspace import (
    PanelState,
    WorkspaceLayout,
    WorkspaceSettings,
)
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class WorkspaceManager(Manager):
    """Manages workspace layouts and panel state.

    Supports multiple named layouts, switching between them, and
    persisting the workspace state to disk.
    """

    def __init__(
        self,
        event_bus: EventBus,
        workspace_path: Path | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._layouts: dict[str, WorkspaceLayout] = {}
        self._settings: WorkspaceSettings = WorkspaceSettings()
        self._active_layout_name: str = "Default"
        self._workspace_path: Path | None = workspace_path
        self._dirty: bool = False

    # -- Layout management --------------------------------------------------

    @property
    def active_layout(self) -> WorkspaceLayout | None:
        """Return the active layout, or ``None``."""
        return self._layouts.get(self._active_layout_name)

    @property
    def active_layout_name(self) -> str:
        """Return the name of the active layout."""
        return self._active_layout_name

    @property
    def layout_names(self) -> list[str]:
        """Return all available layout names."""
        return list(self._layouts.keys())

    @property
    def settings(self) -> WorkspaceSettings:
        """Return the workspace settings."""
        return self._settings

    def add_layout(self, layout: WorkspaceLayout) -> None:
        """Add or replace a workspace layout."""
        self._layouts[layout.name] = layout
        self._dirty = True

    def remove_layout(self, name: str) -> None:
        """Remove a workspace layout.

        Does nothing if the layout doesn't exist. Cannot remove the
        last remaining layout.
        """
        if name not in self._layouts:
            return
        if len(self._layouts) <= 1:
            _logger.warning("Cannot remove the last workspace layout")
            return
        del self._layouts[name]
        if name in self._settings.saved_layouts:
            self._settings.saved_layouts.remove(name)
        if self._active_layout_name == name:
            self._active_layout_name = next(iter(self._layouts))
        self._dirty = True
        self._emit_nowait(WorkspaceLayoutChanged())

    def activate_layout(self, name: str) -> None:
        """Switch to a named layout.

        Raises ``ValueError`` if the layout doesn't exist.
        """
        if name not in self._layouts:
            raise ValueError(f"Layout {name!r} not found")
        self._active_layout_name = name
        self._settings.last_active_layout = name
        self._settings_changed()
        self._emit_nowait(WorkspaceLayoutChanged())

    # -- Panel state --------------------------------------------------------

    def get_panel_state(self, panel_id: str) -> PanelState | None:
        """Return the state of a specific panel in the active layout."""
        layout = self.active_layout
        if layout is None:
            return None
        return layout.panels.get(panel_id)

    def set_panel_visible(self, panel_id: str, visible: bool) -> None:
        """Toggle a panel's visibility in the active layout."""
        layout = self.active_layout
        if layout is None:
            return
        panel = layout.panels.get(panel_id)
        if panel is not None:
            panel.visible = visible
        else:
            layout.panels[panel_id] = PanelState(panel_id=panel_id, visible=visible)
        self._dirty = True
        self._emit_nowait(WorkspaceLayoutChanged())

    def set_panel_floating(self, panel_id: str, floating: bool) -> None:
        """Set a panel's floating state."""
        layout = self.active_layout
        if layout is None:
            return
        panel = layout.panels.get(panel_id)
        if panel is None:
            return
        panel.floating = floating
        self._dirty = True
        self._emit_nowait(WorkspaceLayoutChanged())

    def update_panel_geometry(
        self,
        panel_id: str,
        position: str = "",
        width: int = 0,
        height: int = 0,
    ) -> None:
        """Update a panel's geometry in the active layout."""
        layout = self.active_layout
        if layout is None:
            return
        panel = layout.panels.get(panel_id)
        if panel is None:
            return
        if position:
            panel.position = position
        if width:
            panel.width = width
        if height:
            panel.height = height
        self._dirty = True
        self._emit_nowait(WorkspaceLayoutChanged())

    # -- Window state -------------------------------------------------------

    def update_window_geometry(
        self,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
        maximized: bool | None = None,
    ) -> None:
        """Update the main window geometry on the active layout.

        Only fields that are not ``None`` are applied, allowing callers
        to update a subset (including legitimate zero values).
        """
        layout = self.active_layout
        if layout is None:
            return
        if x is not None:
            layout.window_x = x
        if y is not None:
            layout.window_y = y
        if width is not None:
            layout.window_width = width
        if height is not None:
            layout.window_height = height
        if maximized is not None:
            layout.window_maximized = maximized
        self._dirty = True

    # -- Settings -----------------------------------------------------------

    def set_settings(self, **kwargs: Any) -> None:
        """Update workspace settings fields.

        Emits ``WorkspaceSettingsChanged`` only when at least one field
        actually changes.
        """
        changed = False
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                old = getattr(self._settings, key)
                if old != value:
                    setattr(self._settings, key, value)
                    self._dirty = True
                    changed = True
        if changed:
            self._settings_changed()

    def _settings_changed(self) -> None:
        """Emit a settings-changed event."""
        self._emit_nowait(WorkspaceSettingsChanged())

    # -- Persistence --------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        """Save workspace state to a JSON file."""
        target = path or self._workspace_path
        if target is None:
            return

        _layout_skip = {"id", "name", "metadata", "created_at", "modified_at"}
        data = {
            "settings": asdict(self._settings),
            "layouts": {
                name: {k: v for k, v in asdict(layout).items() if k not in _layout_skip}
                for name, layout in self._layouts.items()
            },
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
        _logger.info("Workspace saved to %s", target)

    def load(self, path: Path | None = None) -> None:
        """Load workspace state from a JSON file."""
        target = path or self._workspace_path
        if target is None or not target.exists():
            return

        try:
            data = json.loads(target.read_text(encoding="utf-8"))

            sd = data.get("settings", {})
            new_settings = WorkspaceSettings(
                last_active_layout=sd.get("last_active_layout", "Default"),
                restore_last_layout=sd.get("restore_last_layout", True),
                auto_save_layout=sd.get("auto_save_layout", True),
                saved_layouts=sd.get("saved_layouts", ["Default"]),
            )

            new_layouts: dict[str, WorkspaceLayout] = {}
            for name, ld in data.get("layouts", {}).items():
                panels: dict[str, PanelState] = {}
                for pid, pd in ld.get("panels", {}).items():
                    panels[pid] = PanelState(
                        panel_id=pd.get("panel_id", pid),
                        visible=pd.get("visible", True),
                        floating=pd.get("floating", False),
                        position=pd.get("position", ""),
                        width=pd.get("width", 300),
                        height=pd.get("height", 400),
                    )
                new_layouts[name] = WorkspaceLayout(
                    name=name,
                    window_x=ld.get("window_x", 100),
                    window_y=ld.get("window_y", 100),
                    window_width=ld.get("window_width", 1600),
                    window_height=ld.get("window_height", 1000),
                    window_maximized=ld.get("window_maximized", False),
                    central_widget=ld.get("central_widget", "viewport"),
                    panels=panels,
                )

            # Restore active layout
            active_layout_name = self._active_layout_name
            if new_settings.restore_last_layout:
                active_layout_name = new_settings.last_active_layout
            if active_layout_name not in new_layouts:
                if not new_layouts:
                    new_layouts["Default"] = WorkspaceLayout(
                        name="Default",
                        panels={
                            "scene_tree": PanelState(
                                panel_id="scene_tree", position="left"
                            ),
                            "asset_browser": PanelState(
                                panel_id="asset_browser", position="left"
                            ),
                            "properties": PanelState(
                                panel_id="properties", position="right"
                            ),
                            "job_monitor": PanelState(
                                panel_id="job_monitor", position="right"
                            ),
                            "timeline": PanelState(
                                panel_id="timeline", position="bottom", height=200
                            ),
                        },
                    )
                active_layout_name = next(iter(new_layouts))

            self._settings = new_settings
            self._layouts = new_layouts
            self._active_layout_name = active_layout_name
            self._dirty = False
            _logger.debug("Workspace loaded from %s", target)
        except Exception as exc:
            _logger.warning("Failed to load workspace: %s", exc)

    # -- Internal -----------------------------------------------------------

    def _ensure_default_layout(self) -> None:
        """Create a default layout if none exist."""
        if not self._layouts:
            default = WorkspaceLayout(name="Default")
            default.panels = {
                "scene_tree": PanelState(panel_id="scene_tree", position="left"),
                "asset_browser": PanelState(panel_id="asset_browser", position="left"),
                "properties": PanelState(panel_id="properties", position="right"),
                "job_monitor": PanelState(panel_id="job_monitor", position="right"),
                "timeline": PanelState(
                    panel_id="timeline", position="bottom", height=200
                ),
            }
            self._layouts["Default"] = default
            self._settings.saved_layouts = ["Default"]

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        if self._workspace_path is not None:
            self.load()
        self._ensure_default_layout()
        _logger.debug("WorkspaceManager initialized")

    @override
    async def _on_shutdown(self) -> None:
        if self._dirty and self._workspace_path is not None:
            self.save()
