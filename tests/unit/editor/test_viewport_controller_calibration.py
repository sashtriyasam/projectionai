"""Tests for ViewportController calibration overlay API."""

from __future__ import annotations

import numpy as np

from projectionai.editor.events import ViewportDirty
from projectionai.editor.viewport_controller import ViewportController
from projectionai.infrastructure.renderer.camera import OrbitCamera


def _controller() -> tuple[ViewportController, list[object]]:
    controller = ViewportController(orbit_camera=OrbitCamera())
    redraws: list[object] = []
    controller.editor_bus.subscribe(ViewportDirty, redraws.append)
    return controller, redraws


def test_set_calibration_status_updates_overlay_and_requests_redraw() -> None:
    controller, redraws = _controller()
    controller.set_calibration_status(0.4, "Capturing views")
    overlay = controller.overlays.calibration
    assert overlay.progress == 0.4
    assert overlay.status_text == "Capturing views"
    assert len(redraws) == 1


def test_set_calibration_detection_updates_overlay_and_requests_redraw() -> None:
    controller, redraws = _controller()
    corners = np.array([[10, 20], [30, 40], [50, 60]], dtype=np.float32)
    controller.set_calibration_detection(corners, (640, 480))
    overlay = controller.overlays.calibration
    assert overlay.has_detection
    assert overlay.corner_count == 3
    assert overlay.image_size == (640, 480)
    assert len(redraws) == 1


def test_set_calibration_detection_none_clears_overlay() -> None:
    controller, redraws = _controller()
    corners = np.array([[10, 20], [30, 40]], dtype=np.float32)
    controller.set_calibration_detection(corners, (640, 480))
    controller.set_calibration_detection(None, (640, 480))
    assert not controller.overlays.calibration.has_detection
    assert len(redraws) == 2


def test_clear_calibration_clears_overlay_and_requests_redraw() -> None:
    controller, redraws = _controller()
    controller.set_calibration_status(0.9, "Finishing")
    corners = np.array([[10, 20], [30, 40]], dtype=np.float32)
    controller.set_calibration_detection(corners, (640, 480))
    controller.clear_calibration()
    overlay = controller.overlays.calibration
    assert not overlay.has_detection
    assert overlay.corner_count == 0
    assert len(redraws) == 3
