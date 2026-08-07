"""TimelinePropertiesPanel — timeline + transport settings (right dock).

Renders :class:`TimelineModel` configuration through a
:class:`PropertySheet`: frame rate, playhead position, loop region.
Edits commit back through the model's setters.
"""

from __future__ import annotations

from typing import Any

from projectionai.ui.panels.property_panel import PropertyPanel
from projectionai.ui.viewmodels.properties import PropertySheet


class TimelinePropertiesPanel(PropertyPanel):
    """Timeline Properties dock panel."""

    panel_id = "timeline_properties"

    def build_sheet(self) -> PropertySheet:
        """Build the timeline settings sheet."""
        sheet = PropertySheet("Timeline")

        transport = sheet.add_section("Transport")
        sheet.add_float(
            transport,
            "fps",
            "Frame rate",
            value=30.0,
            minimum=0.1,
            maximum=240.0,
            step=1.0,
            help="Playback frame rate",
        )
        sheet.add_int(
            transport,
            "playhead",
            "Playhead",
            value=0,
            minimum=0,
            step=1,
            help="Current playhead frame",
        )
        sheet.add_label(transport, "timecode", "Timecode")

        loop = sheet.add_section("Loop")
        sheet.add_bool(
            loop, "loop_enabled", "Loop enabled", value=False, help="Repeat the region"
        )
        sheet.add_int(
            loop, "in_point", "In point", value=0, minimum=0, step=1, help="Loop start"
        )
        sheet.add_int(
            loop,
            "out_point",
            "Out point",
            value=3600,
            minimum=1,
            step=1,
            help="Loop end (exclusive)",
        )
        return sheet

    def sync_sheet(self, sheet: PropertySheet) -> None:
        """Mirror timeline state into the sheet."""
        model = self._viewmodel
        if model is None:
            return
        sheet.set_value("fps", model.fps)
        sheet.set_value("playhead", model.playhead_frame)
        sheet.set_value("timecode", model.timecode(model.playhead_frame))
        sheet.set_value("loop_enabled", model.loop_enabled)
        sheet.set_value("in_point", model.in_point)
        sheet.set_value("out_point", model.out_point)

    def apply_row(self, row_id: str, value: Any) -> None:
        """Commit a timeline edit to the model."""
        model = self._viewmodel
        if model is None:
            return
        try:
            if row_id == "fps":
                model.fps = float(value)
            elif row_id == "playhead":
                model.playhead_frame = int(value)
            elif row_id == "loop_enabled":
                model.loop_enabled = bool(value)
            elif row_id in ("in_point", "out_point"):
                sheet = self.editor.sheet
                if sheet is not None:
                    sheet.set_value(row_id, value)
                    row_in = sheet.row("in_point")
                    row_out = sheet.row("out_point")
                    if row_in is not None and row_out is not None:
                        in_point = int(row_in.value)
                        out_point = int(row_out.value)
                        model.set_loop_range(in_point, out_point)
                        # set_loop_range clamps and rejects in >= out without
                        # raising; restore the sheet on non-adoption.
                        if (model.in_point, model.out_point) != (in_point, out_point):
                            self.sync_sheet(sheet)
                            self.editor.refresh()
        except (TypeError, ValueError):
            pass
