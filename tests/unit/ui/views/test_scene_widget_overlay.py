"""Tests for SceneWidget calibration board overlay.

``set_calibration_overlay`` stores corners (pixel space) plus the frame
size used to scale them onto the widget; ``None`` clears. The paint
routine must not crash with or without an image size, and with an
empty corner list. Rendering happens offscreen
(``QT_QPA_PLATFORM=offscreen``); ``widget.grab()`` exercises the full
paint path without a display.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.views.scene_widget import SceneWidget

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


class TestCalibrationOverlay:
    def test_set_stores_corners_and_size(self, qapp: QApplication) -> None:
        widget = SceneWidget()
        widget.resize(320, 240)
        widget.set_calibration_overlay([(10, 20), (30, 40)], (640, 480))
        assert widget._calibration_corners == [(10, 20), (30, 40)]
        assert widget._calibration_image_size == (640, 480)
        widget.grab()  # paint path must not crash

    def test_clear_with_none(self, qapp: QApplication) -> None:
        widget = SceneWidget()
        widget.resize(320, 240)
        widget.set_calibration_overlay([(10, 20)], (640, 480))
        widget.set_calibration_overlay(None)
        assert widget._calibration_corners is None
        assert widget._calibration_image_size is None
        widget.grab()

    def test_paint_without_image_size_scales_1_to_1(self, qapp: QApplication) -> None:
        widget = SceneWidget()
        widget.resize(320, 240)
        widget.set_calibration_overlay([(10, 20), (30, 40)])
        widget.grab()  # sx=sy=1.0 path must not crash

    def test_paint_empty_corners_is_noop(self, qapp: QApplication) -> None:
        widget = SceneWidget()
        widget.resize(320, 240)
        widget.set_calibration_overlay([], (640, 480))
        widget.grab()

    def test_scaled_paint_scales_corner_position(self, qapp: QApplication) -> None:
        widget = SceneWidget()
        widget.resize(320, 240)
        # 640x480 source onto a 320x240 widget -> 0.5 scale on both axes.
        widget.set_calibration_overlay([(10, 20)], (640, 480))
        image = widget.grab().toImage()

        def greenish_near(x: int, y: int) -> bool:
            # The marker ring (OK_GREEN pen) renders within ~3 px of its
            # center; allow a small antialiasing window around it.
            for dx in range(-4, 5):
                for dy in range(-4, 5):
                    c = image.pixelColor(x + dx, y + dy)
                    if c.green() > 120 and c.green() - c.red() > 30:
                        return True
            return False

        # Corner (10, 20) scales to (5, 10) on the widget.
        assert greenish_near(5, 10)
        # ... and must not render at the unscaled position (10, 20).
        assert not greenish_near(10, 20)
