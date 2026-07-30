"""Overlay renderer — orchestrates 2D/3D overlay drawing in the viewport."""

from __future__ import annotations

from projectionai.editor.axis_renderer import AxisRenderer
from projectionai.editor.grid_renderer import GridRenderer
from projectionai.editor.types import EditorViewState


class OverlayRenderer:
    """Orchestrates all overlay rendering in the viewport.

    Owns the :class:`GridRenderer` and :class:`AxisRenderer`, and
    provides a single entry point for drawing all overlays during
    the render pipeline's overlay pass.

    Future overlays (bounding boxes, selection outlines, camera
    frustums, statistics, safe area, projection guides) can be
    added here as properties.
    """

    def __init__(self) -> None:
        self._grid = GridRenderer()
        self._axes = AxisRenderer()

        # Future overlay components
        self._show_bounding_boxes: bool = False
        self._show_selection_outlines: bool = True
        self._show_statistics: bool = False

    # -- Sub-overlays -------------------------------------------------------

    @property
    def grid(self) -> GridRenderer:
        """The grid overlay."""
        return self._grid

    @property
    def axes(self) -> AxisRenderer:
        """The world-axis overlay."""
        return self._axes

    # -- Toggles ------------------------------------------------------------

    @property
    def show_bounding_boxes(self) -> bool:
        return self._show_bounding_boxes

    @show_bounding_boxes.setter
    def show_bounding_boxes(self, value: bool) -> None:
        self._show_bounding_boxes = value

    @property
    def show_selection_outlines(self) -> bool:
        return self._show_selection_outlines

    @show_selection_outlines.setter
    def show_selection_outlines(self, value: bool) -> None:
        self._show_selection_outlines = value

    @property
    def show_statistics(self) -> bool:
        return self._show_statistics

    @show_statistics.setter
    def show_statistics(self, value: bool) -> None:
        self._show_statistics = value

    # -- Sync from view state -----------------------------------------------

    def apply_view_state(self, state: EditorViewState) -> None:
        """Apply editor view state toggles to all overlays.

        Args:
            state: Current editor view state.
        """
        self._grid.enabled = state.show_grid
        self._axes.enabled = state.show_axes
        self._show_bounding_boxes = state.show_bounding_boxes
        self._show_selection_outlines = state.show_selection_outlines
        self._show_statistics = state.show_statistics
