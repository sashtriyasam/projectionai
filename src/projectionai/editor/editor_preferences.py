"""Editor preferences — serialisable settings for the editor subsystem."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

from projectionai.editor.events import EditorEventBus, EditorPreferenceChanged

_logger = logging.getLogger(__name__)


class EditorPreferences:
    """Persistent editor settings.

    Stores preferences in a JSON file. All values are readable/writable
    via string keys. Changes are broadcast on the editor event bus so
    UI components can react.

    Defaults are loaded from ``EditorViewState``-compatible values and
    can be overridden at construction time.
    """

    _DEFAULTS: ClassVar[dict[str, Any]] = {
        # Viewport
        "show_grid": True,
        "show_axes": True,
        "show_bounding_boxes": False,
        "show_selection_outlines": True,
        "show_statistics": False,
        # Snapping
        "snap_enabled": False,
        "snap_translation": 0.25,
        "snap_rotation": 15.0,
        "snap_scale": 0.1,
        # Interaction
        "transform_space": "world",
        "pivot_mode": "center",
        "orbit_speed": 1.0,
        "pan_speed": 1.0,
        "zoom_speed": 1.0,
        "damping_enabled": True,
        "damping_factor": 0.85,
        # Appearance
        "background_color": [0.1, 0.1, 0.1],
        "grid_size": 20,
        "grid_subdivisions": 10,
        "grid_color": [0.3, 0.3, 0.3],
        "axis_size": 1.0,
        "selection_color": [1.0, 0.65, 0.0],
        # Key bindings (stored as dict of action -> key)
        "key_bindings": {},
    }

    def __init__(
        self,
        path: Path | None = None,
        event_bus: EditorEventBus | None = None,
    ) -> None:
        self._path = path
        self._event_bus = event_bus
        self._data: dict[str, Any] = copy.deepcopy(self._DEFAULTS)
        self._loaded: bool = False

        if path is not None and path.exists():
            self._load()

    # -- Dict-like access ---------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return a preference value, or *default* if not set."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a preference value and persist.

        Emits ``EditorPreferenceChanged`` on the event bus.
        """
        old = self._data.get(key)
        if old == value:
            return
        self._data[key] = value
        if self._event_bus:
            self._event_bus.emit(EditorPreferenceChanged(key=key, value=value))
        self._save()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    # -- Persistence --------------------------------------------------------

    def _load(self) -> None:
        """Load preferences from the JSON file."""
        if self._path is None:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                stored = json.load(f)
            self._data.update(stored)
            self._loaded = True
            _logger.debug("Loaded editor preferences from %s", self._path)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load editor preferences: %s", exc)

    def _save(self) -> None:
        """Persist preferences to the JSON file."""
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as exc:
            _logger.warning("Failed to save editor preferences: %s", exc)

    def reset_to_defaults(self) -> None:
        """Reset all preferences to their default values."""
        self._data = copy.deepcopy(self._DEFAULTS)
        self._save()
        if self._event_bus:
            for key, value in self._data.items():
                self._event_bus.emit(EditorPreferenceChanged(key=key, value=value))
