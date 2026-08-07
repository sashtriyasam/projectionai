"""OutputSettingsViewModel — output device + canvas settings.

Qt-free. Aggregates the output canvas settings (:class:`ProjectSettings`
via :class:`ProjectManager`) with the live output state
(:class:`OutputViewModel`) for the Output Settings panel. Canvas
mutations go through the project manager so dirty tracking stays
consistent.
"""

from __future__ import annotations

from projectionai.domain.project import ProjectSettings
from projectionai.managers.project_manager import ProjectManager
from projectionai.ui.viewmodels.observable import Observable
from projectionai.ui.viewmodels.output import OutputViewModel
from projectionai.ui.viewmodels.project import _SETTING_KEYS

_DEFAULT_SETTINGS = ProjectSettings()


def _current_settings(projects: ProjectManager) -> ProjectSettings:
    """Active project settings, or the table defaults when no project is open."""
    project = projects.current
    if project is None:
        return _DEFAULT_SETTINGS
    return project.settings


class OutputSettingsViewModel(Observable):
    """Observable output-canvas facade."""

    def __init__(
        self,
        project_manager: ProjectManager,
        output: OutputViewModel | None = None,
    ) -> None:
        super().__init__()
        self._projects = project_manager
        self._output = output

    # -- Canvas (project settings) ------------------------------------------------

    @property
    def resolution(self) -> tuple[int, int]:
        """Canvas resolution as ``(width, height)`` (project defaults when closed)."""
        settings = _current_settings(self._projects)
        return (settings.resolution_width, settings.resolution_height)

    @property
    def framerate(self) -> float:
        """Canvas frame rate."""
        return _current_settings(self._projects).framerate

    @property
    def color_space(self) -> str:
        """Active color space name."""
        return _current_settings(self._projects).color_space

    @property
    def grid_enabled(self) -> bool:
        """True when the preview grid is enabled."""
        return _current_settings(self._projects).grid_enabled

    @property
    def snap_to_grid(self) -> bool:
        """True when snapping to the grid is enabled."""
        return _current_settings(self._projects).snap_to_grid

    @property
    def grid_size(self) -> float:
        """Grid size in world units."""
        return _current_settings(self._projects).grid_size

    # -- Canvas mutations --------------------------------------------------------

    def set_resolution(self, width: int, height: int) -> None:
        """Set the canvas resolution."""
        self._set("resolution_width", max(width, 1))
        self._set("resolution_height", max(height, 1))

    def set_framerate(self, framerate: float) -> None:
        """Set the canvas frame rate."""
        self._set("framerate", max(float(framerate), 0.1))

    def set_color_space(self, color_space: str) -> None:
        """Set the active color space."""
        self._set("color_space", color_space)

    def set_grid_enabled(self, enabled: bool) -> None:
        """Toggle the preview grid."""
        self._set("grid_enabled", bool(enabled))

    def set_snap_to_grid(self, enabled: bool) -> None:
        """Toggle grid snapping."""
        self._set("snap_to_grid", bool(enabled))

    def set_grid_size(self, size: float) -> None:
        """Set the grid cell size."""
        self._set("grid_size", max(float(size), 0.01))

    def _set(self, key: str, value: object) -> None:
        project = self._projects.current
        if project is None or key not in _SETTING_KEYS:
            return
        setattr(project.settings, key, value)
        self._projects.mark_modified(description=f"Changed output {key}")
        self._notify()

    # -- Output state (delegated) ----------------------------------------------------

    @property
    def output_label(self) -> str:
        """Human-readable output state label."""
        if self._output is None:
            return "Output"
        return self._output.label

    @property
    def output_color(self) -> str:
        """Hex color for the output state label."""
        if self._output is None:
            return "#FF9E00"
        return self._output.color

    @property
    def is_live(self) -> bool:
        """True when program content is visible (not blackout/freeze)."""
        if self._output is None:
            return False
        return self._output.is_live

    def refresh(self) -> None:
        """Force a revision bump (call on a poll timer)."""
        self._notify()
