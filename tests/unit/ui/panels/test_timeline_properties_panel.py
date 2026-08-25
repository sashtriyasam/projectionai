"""Regression tests for TimelinePropertiesPanel loop-range edits.

``TimelineModel.set_loop_range`` clamps to the timeline and silently
rejects ``in >= out`` without raising; the panel must not leave the
sheet showing values the model refused. Accepted edits stay as typed;
rejected or clamped edits restore the sheet from the model. Rendering
happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.panels.timeline_properties_panel import TimelinePropertiesPanel

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


class _FakeTimeline:
    """Duck-typed TimelineModel stand-in with the same clamp/reject contract."""

    def __init__(self) -> None:
        self.fps = 30.0
        self.playhead_frame = 0
        self.loop_enabled = True
        self.in_point = 0
        self.out_point = 3600
        self._duration = 3600

    def timecode(self, frame: int) -> str:
        return f"{frame:04d}"

    def set_loop_range(self, in_point: int, out_point: int) -> None:
        in_point = max(0, min(in_point, self._duration))
        out_point = max(0, min(out_point, self._duration))
        if in_point >= out_point:
            return
        self.in_point = in_point
        self.out_point = out_point

    def subscribe(self, handler: Any) -> None:
        """No-op: tests drive apply_row() directly."""

    def unsubscribe(self, handler: Any) -> None:
        """No-op."""


def _bound_panel(qapp: QApplication, model: _FakeTimeline) -> TimelinePropertiesPanel:
    panel = TimelinePropertiesPanel()
    panel.bind_viewmodel(model)
    return panel


def _row_value(panel: TimelinePropertiesPanel, row_id: str) -> Any:
    """Return the current value of a sheet row."""
    sheet = panel.editor.sheet
    assert sheet is not None
    row = sheet.row(row_id)
    assert row is not None
    return row.value


class TestLoopRangeEdits:
    def test_valid_edit_is_adopted(self, qapp: QApplication) -> None:
        panel = _bound_panel(qapp, _FakeTimeline())
        panel.apply_row("in_point", 500)
        assert _row_value(panel, "in_point") == 500
        vm = panel._viewmodel
        assert vm is not None
        assert vm.in_point == 500

    def test_reversed_range_restores_sheet(self, qapp: QApplication) -> None:
        model = _FakeTimeline()
        panel = _bound_panel(qapp, model)
        panel.apply_row("in_point", 3000)
        assert model.in_point == 3000
        # out (2000) < in (3000) is rejected by set_loop_range (in >= out):
        # the sheet must fall back to the model's still-valid range.
        panel.apply_row("out_point", 2000)
        assert model.out_point == 3600
        assert _row_value(panel, "out_point") == 3600
        assert _row_value(panel, "in_point") == 3000

    def test_clamped_edit_restores_sheet(self, qapp: QApplication) -> None:
        model = _FakeTimeline()
        model.out_point = 2000
        panel = _bound_panel(qapp, model)
        # in_point == out_point clamps to equal values, which is rejected
        # (in >= out); the model keeps (0, 2000).
        panel.apply_row("in_point", 2000)
        assert _row_value(panel, "in_point") == 0
        assert model.in_point == 0

    def test_rejected_edit_preserves_model(self, qapp: QApplication) -> None:
        model = _FakeTimeline()
        panel = _bound_panel(qapp, model)
        panel.apply_row("in_point", 3000)
        assert model.in_point == 3000
        panel.apply_row("out_point", 3000)
        # 3000 >= 3000 rejects: model keeps (3000, 3600) and the sheet
        # shows out_point 3600 again, not the rejected 3000.
        assert model.out_point == 3600
        assert _row_value(panel, "out_point") == 3600
