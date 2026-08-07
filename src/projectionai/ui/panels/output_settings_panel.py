"""OutputSettingsPanel — output device + canvas settings (right dock).

Renders :class:`OutputSettingsViewModel` through a
:class:`PropertySheet`: canvas resolution/color space, grid, and the
live output state label. Canvas edits go through the project manager so
dirty tracking stays consistent.
"""

from __future__ import annotations

import logging
from typing import Any

from projectionai.ui.panels.property_panel import PropertyPanel
from projectionai.ui.viewmodels.properties import PropertySheet

_logger = logging.getLogger(__name__)

_COLOR_SPACES: list[tuple[str, str]] = [
    ("sRGB", "sRGB"),
    ("Rec.709", "Rec.709"),
    ("DCI-P3", "DCI-P3"),
    ("Display P3", "Display P3"),
]


class OutputSettingsPanel(PropertyPanel):
    """Output Settings dock panel."""

    panel_id = "output_settings"

    def build_sheet(self) -> PropertySheet:
        """Build the output settings sheet."""
        sheet = PropertySheet("Output")

        canvas = sheet.add_section("Canvas")
        sheet.add_int(
            canvas,
            "resolution_width",
            "Width",
            value=1920,
            minimum=64,
            maximum=16384,
            step=8,
        )
        sheet.add_int(
            canvas,
            "resolution_height",
            "Height",
            value=1080,
            minimum=64,
            maximum=16384,
            step=8,
        )
        sheet.add_float(
            canvas,
            "framerate",
            "Frame rate",
            value=30.0,
            minimum=0.1,
            maximum=240.0,
            step=1.0,
        )
        sheet.add_choice(
            canvas,
            "color_space",
            "Color space",
            value="sRGB",
            choices=_COLOR_SPACES,
        )

        grid = sheet.add_section("Grid")
        sheet.add_bool(grid, "grid_enabled", "Grid", value=True)
        sheet.add_bool(grid, "snap_to_grid", "Snap to grid", value=False)
        sheet.add_float(
            grid,
            "grid_size",
            "Grid size",
            value=1.0,
            minimum=0.01,
            maximum=100.0,
            step=0.1,
        )

        state = sheet.add_section("Output State")
        sheet.add_label(state, "output_label", "State")
        sheet.add_label(state, "is_live", "Live")
        return sheet

    def sync_sheet(self, sheet: PropertySheet) -> None:
        """Mirror output state into the sheet."""
        vm = self._viewmodel
        if vm is None:
            return
        width, height = vm.resolution
        sheet.set_value("resolution_width", width)
        sheet.set_value("resolution_height", height)
        sheet.set_value("framerate", vm.framerate)
        sheet.set_value("color_space", vm.color_space)
        sheet.set_value("grid_enabled", vm.grid_enabled)
        sheet.set_value("snap_to_grid", vm.snap_to_grid)
        sheet.set_value("grid_size", vm.grid_size)
        sheet.set_value("output_label", vm.output_label)
        sheet.set_value("is_live", "Yes" if vm.is_live else "No")

    def apply_row(self, row_id: str, value: Any) -> None:
        """Commit an output edit to the view model."""
        vm = self._viewmodel
        if vm is None:
            return
        try:
            if row_id == "resolution_width":
                vm.set_resolution(int(value), vm.resolution[1])
            elif row_id == "resolution_height":
                vm.set_resolution(vm.resolution[0], int(value))
            elif row_id == "framerate":
                vm.set_framerate(float(value))
            elif row_id == "color_space":
                vm.set_color_space(str(value))
            elif row_id == "grid_enabled":
                vm.set_grid_enabled(bool(value))
            elif row_id == "snap_to_grid":
                vm.set_snap_to_grid(bool(value))
            elif row_id == "grid_size":
                vm.set_grid_size(float(value))
        except (TypeError, ValueError) as exc:
            _logger.warning("Rejected invalid value for output row %r: %s", row_id, exc)
            self.refresh()
