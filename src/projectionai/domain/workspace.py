"""Workspace / layout model for the desktop UI.

The workspace manager saves and restores the arrangement of dock
panels, window size/position, and panel visibility. This model
captures the serializable state.

Design decisions:
- The model is Qt-agnostic — it stores geometry as strings (e.g.,
  ``"left:100;top:100;width:1600;height:1000"``) rather than
  QRect objects.
- Panel visibility is stored separately from layout geometry so
  individual panels can be toggled without restoring an entire layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass
class PanelState:
    """Visibility and state of a single dock panel."""

    panel_id: str
    visible: bool = True
    floating: bool = False
    position: str = ""  # "left", "right", "bottom", "top", or geometry string
    width: int = 300
    height: int = 400


@dataclass
class WorkspaceLayout:
    """A named workspace layout capturing the full UI arrangement."""

    id: str = field(default_factory=lambda: uuid4().hex[:8])
    name: str = "Default"

    # Window geometry
    window_x: int = 100
    window_y: int = 100
    window_width: int = 1600
    window_height: int = 1000
    window_maximized: bool = False

    # Panel states
    panels: dict[str, PanelState] = field(default_factory=dict)

    # Central widget state (e.g., active tab)
    central_widget: str = "viewport"

    # Custom properties
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    modified_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class WorkspaceSettings:
    """Persistent workspace preferences (not per-layout)."""

    # The last active layout name (restored on startup)
    last_active_layout: str = "Default"

    # Whether to restore the last layout on startup
    restore_last_layout: bool = True

    # Auto-save layout on exit
    auto_save_layout: bool = True

    # List of saved layout names (for display)
    saved_layouts: list[str] = field(default_factory=lambda: ["Default"])
