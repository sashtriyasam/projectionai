"""Tests for ViewportWidget calibration wiring.

The widget's calibration path is covered without a GL context: the widget
is constructed via ``__new__`` (skipping ``QOpenGLWidget.__init__``, which
requires a QApplication), the Qt-free :class:`ViewportController` is injected
directly, and the overlay pass is replaced with a recording fake. The widget's
``width()``/``height()`` are patched at class level to fixed viewport
dimensions.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from projectionai.core.events import (
    CalibrationComplete,
    CalibrationFailed,
    CalibrationProgress,
    CalibrationStarted,
)
from projectionai.editor.viewport_controller import ViewportController
from projectionai.editor.viewport_widget import ViewportWidget
from projectionai.infrastructure.renderer.camera import OrbitCamera
from projectionai.services.camera_calibration import BoardDetection

# Viewport dimensions used for the coordinate-conversion tests.
_VIEWPORT_SIZE = (800, 300)


class _RecordingOverlayPass:
    """Records every ``set_corner_lines`` payload (copies, never aliases)."""

    def __init__(self) -> None:
        self.calls: list[NDArray[np.float32] | None] = []

    def set_corner_lines(self, corners: NDArray[np.float32] | None) -> None:
        self.calls.append(None if corners is None else corners.copy())


@pytest.fixture
def widget_with_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ViewportWidget, _RecordingOverlayPass]:
    """A controller+pass wired widget of size ``_VIEWPORT_SIZE``."""
    controller = ViewportController(orbit_camera=OrbitCamera())
    overlay_pass = _RecordingOverlayPass()

    widget = ViewportWidget.__new__(ViewportWidget)
    widget._controller = controller
    widget._overlay_pass = overlay_pass
    widget._last_calibration_revision = -1

    monkeypatch.setattr(ViewportWidget, "width", lambda _self: _VIEWPORT_SIZE[0])
    monkeypatch.setattr(ViewportWidget, "height", lambda _self: _VIEWPORT_SIZE[1])
    return widget, overlay_pass


def _board_detection(
    corners: NDArray[np.float32], image_size: tuple[int, int]
) -> BoardDetection:
    return BoardDetection(corners=corners, image_size=image_size, frame_number=1)


# -- show_calibration_detection ----------------------------------------------


def test_show_calibration_detection_forwards_corners_and_image_size(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, _ = widget_with_pass
    corners = np.array([[10, 20], [30, 40], [50, 60]], dtype=np.float32)
    widget.show_calibration_detection(_board_detection(corners, (640, 480)))

    assert widget.controller is not None
    overlay = widget.controller.overlays.calibration
    assert overlay.has_detection
    assert overlay.corner_count == 3
    assert overlay.image_size == (640, 480)
    np.testing.assert_array_almost_equal(overlay.corners, corners)


def test_show_calibration_detection_none_clears_overlay(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, _ = widget_with_pass
    corners = np.array([[10, 20], [30, 40]], dtype=np.float32)
    widget.show_calibration_detection(_board_detection(corners, (640, 480)))
    widget.show_calibration_detection(None)

    assert widget.controller is not None
    assert not widget.controller.overlays.calibration.has_detection


def test_show_calibration_detection_without_controller_is_noop() -> None:
    widget = ViewportWidget.__new__(ViewportWidget)
    widget._controller = None
    widget.show_calibration_detection(
        _board_detection(np.array([[0, 0]], dtype=np.float32), (640, 480))
    )
    widget.show_calibration_detection(None)  # must not raise


# -- _sync_calibration_overlay -----------------------------------------------


def test_sync_converts_camera_pixels_to_viewport_pixels(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, overlay_pass = widget_with_pass
    # 4 corners in a 200x100 frame -> 3 segments -> 6 line vertices.
    corners = np.array([[0, 0], [100, 0], [100, 50], [0, 50]], dtype=np.float32)
    widget.show_calibration_detection(_board_detection(corners, (200, 100)))

    widget._sync_calibration_overlay()

    assert len(overlay_pass.calls) == 1
    pushed = overlay_pass.calls[0]
    assert pushed is not None
    # Camera (200, 100) -> viewport (800, 300): scale_x = 4, scale_y = 3.
    np.testing.assert_array_almost_equal(
        pushed,
        np.array(
            [
                [0.0, 0.0],
                [400.0, 0.0],
                [400.0, 0.0],
                [400.0, 150.0],
                [400.0, 150.0],
                [0.0, 150.0],
            ],
            dtype=np.float32,
        ),
    )


def test_sync_preserves_camera_space_corners(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    """The overlay keeps camera-space data; only the pushed copy is scaled."""
    widget, _ = widget_with_pass
    corners = np.array([[10, 20], [30, 40]], dtype=np.float32)
    widget.show_calibration_detection(_board_detection(corners, (640, 480)))

    widget._sync_calibration_overlay()

    assert widget.controller is not None
    np.testing.assert_array_almost_equal(
        widget.controller.overlays.calibration.corners, corners
    )


def test_sync_skips_unchanged_revision(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, overlay_pass = widget_with_pass
    widget.show_calibration_detection(
        _board_detection(np.array([[0, 0], [1, 1]], dtype=np.float32), (640, 480))
    )

    widget._sync_calibration_overlay()
    widget._sync_calibration_overlay()  # same revision -> no push
    assert len(overlay_pass.calls) == 1

    # Status changes do not bump the revision -> still no push.
    assert widget.controller is not None
    widget.controller.set_calibration_status(0.5, "Capturing")
    widget._sync_calibration_overlay()
    assert len(overlay_pass.calls) == 1

    # A new detection bumps the revision -> push again.
    widget.show_calibration_detection(
        _board_detection(np.array([[5, 5], [6, 6]], dtype=np.float32), (640, 480))
    )
    widget._sync_calibration_overlay()
    assert len(overlay_pass.calls) == 2


def test_sync_disabled_overlay_pushes_none(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, overlay_pass = widget_with_pass
    widget.show_calibration_detection(
        _board_detection(np.array([[0, 0], [1, 1]], dtype=np.float32), (640, 480))
    )
    widget._sync_calibration_overlay()
    assert len(overlay_pass.calls) == 1

    assert widget.controller is not None
    widget.controller.overlays.calibration.enabled = False
    widget._sync_calibration_overlay()
    assert len(overlay_pass.calls) == 2
    assert overlay_pass.calls[1] is None


def test_sync_cleared_detection_pushes_empty_geometry(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, overlay_pass = widget_with_pass
    widget.show_calibration_detection(
        _board_detection(np.array([[0, 0], [1, 1]], dtype=np.float32), (640, 480))
    )
    widget._sync_calibration_overlay()

    assert widget.controller is not None
    widget.controller.clear_calibration()
    widget._sync_calibration_overlay()

    assert len(overlay_pass.calls) == 2
    cleared = overlay_pass.calls[1]
    assert cleared is not None and cleared.shape == (0, 2)


def test_sync_without_pass_or_controller_is_noop() -> None:
    widget = ViewportWidget.__new__(ViewportWidget)
    widget._controller = None
    widget._overlay_pass = None
    widget._sync_calibration_overlay()  # must not raise


# -- _on_calibration_* handlers ----------------------------------------------


async def test_on_calibration_started_sets_status(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, _ = widget_with_pass
    await widget._on_calibration_started(CalibrationStarted(scene_id="scene-1"))
    assert widget.controller is not None
    overlay = widget.controller.overlays.calibration
    assert overlay.progress == 0.0
    assert overlay.status_text == "Calibration started"


async def test_on_calibration_progress_sets_status(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, _ = widget_with_pass
    await widget._on_calibration_progress(
        CalibrationProgress(scene_id="scene-1", progress=0.4, status="Capturing views")
    )
    assert widget.controller is not None
    overlay = widget.controller.overlays.calibration
    assert overlay.progress == 0.4
    assert overlay.status_text == "Capturing views"


async def test_on_calibration_complete_sets_status(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, _ = widget_with_pass
    await widget._on_calibration_complete(CalibrationComplete(scene_id="scene-1"))
    assert widget.controller is not None
    overlay = widget.controller.overlays.calibration
    assert overlay.progress == 1.0
    assert overlay.status_text == "Calibration complete"


async def test_on_calibration_failed_sets_status(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    widget, _ = widget_with_pass
    await widget._on_calibration_failed(
        CalibrationFailed(scene_id="scene-1", reason="board not found")
    )
    assert widget.controller is not None
    overlay = widget.controller.overlays.calibration
    assert overlay.progress == 0.0
    assert overlay.status_text == "Calibration failed: board not found"


async def test_handlers_without_controller_are_noop() -> None:
    widget = ViewportWidget.__new__(ViewportWidget)
    widget._controller = None
    await widget._on_calibration_started(CalibrationStarted(scene_id="scene-1"))
    await widget._on_calibration_progress(
        CalibrationProgress(scene_id="scene-1", progress=0.5, status="x")
    )
    await widget._on_calibration_complete(CalibrationComplete(scene_id="scene-1"))
    await widget._on_calibration_failed(
        CalibrationFailed(scene_id="scene-1", reason="x")
    )  # must not raise


# -- integration: event -> status + revision-gated push ----------------------


async def test_progress_event_then_sync_pushes_scaled_vertices(
    widget_with_pass: tuple[ViewportWidget, _RecordingOverlayPass],
) -> None:
    """A full wiring pass: detection -> sync -> event -> status -> sync."""
    widget, overlay_pass = widget_with_pass
    corners = np.array([[0, 0], [100, 0], [100, 50], [0, 50]], dtype=np.float32)
    widget.show_calibration_detection(_board_detection(corners, (200, 100)))
    widget._sync_calibration_overlay()

    await widget._on_calibration_progress(
        CalibrationProgress(scene_id="scene-1", progress=0.7, status="Refining")
    )
    widget._sync_calibration_overlay()  # status only -> no new push

    assert widget.controller is not None
    assert widget.controller.overlays.calibration.status_text == "Refining"
    assert len(overlay_pass.calls) == 1
    pushed = overlay_pass.calls[0]
    assert pushed is not None
    np.testing.assert_array_almost_equal(pushed[-1], [0.0, 150.0])
