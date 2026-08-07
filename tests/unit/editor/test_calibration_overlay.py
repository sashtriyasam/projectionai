"""Tests for CalibrationOverlay — calibration board-detection overlay data."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.editor.calibration_overlay import CalibrationOverlay


def _corners(n: int = 4) -> np.ndarray:
    """Row-major corner positions (pixel space) for ``n`` corners."""
    return np.arange(n * 2, dtype=np.float32).reshape(n, 2) + 10.0


def test_default_state() -> None:
    overlay = CalibrationOverlay()
    assert overlay.enabled
    assert not overlay.has_detection
    assert overlay.corner_count == 0
    assert overlay.image_size == (0, 0)
    assert overlay.progress == 0.0
    assert overlay.status_text == ""
    assert overlay.line_count == 0
    assert overlay.revision == 0
    assert overlay.vertices.shape == (0, 2)
    assert overlay.colors.shape == (0, 4)


def test_set_detection() -> None:
    overlay = CalibrationOverlay()
    overlay.set_detection(_corners(4), (640, 480))
    assert overlay.has_detection
    assert overlay.corner_count == 4
    assert overlay.image_size == (640, 480)
    assert overlay.revision == 1


def test_set_detection_with_none_clears() -> None:
    overlay = CalibrationOverlay()
    overlay.set_detection(_corners(4), (640, 480))
    overlay.set_detection(None, (640, 480))
    assert not overlay.has_detection
    assert overlay.corner_count == 0
    assert overlay.vertices.shape == (0, 2)


def test_set_detection_invalid_shape_raises() -> None:
    overlay = CalibrationOverlay()
    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        overlay.set_detection(np.zeros((4, 3), dtype=np.float32), (640, 480))
    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        overlay.set_detection(np.zeros((4,), dtype=np.float32), (640, 480))


def test_vertices_shape_and_line_count() -> None:
    overlay = CalibrationOverlay()
    n = 6
    overlay.set_detection(_corners(n), (640, 480))
    # n-1 consecutive line segments -> 2*(n-1) vertices
    assert overlay.vertices.shape == (2 * (n - 1), 2)
    assert overlay.line_count == n - 1
    assert overlay.colors.shape == (2 * (n - 1), 4)


def test_vertices_connect_consecutive_corners() -> None:
    overlay = CalibrationOverlay()
    corners = _corners(4)
    overlay.set_detection(corners, (640, 480))
    verts = overlay.vertices
    # Segment i: corners[i] -> corners[i+1]
    for i in range(3):
        np.testing.assert_array_almost_equal(verts[2 * i], corners[i])
        np.testing.assert_array_almost_equal(verts[2 * i + 1], corners[i + 1])


def test_colors_match_corner_color() -> None:
    overlay = CalibrationOverlay()
    overlay.set_detection(_corners(4), (640, 480))
    colors = overlay.colors
    assert colors.shape == (6, 4)
    expected = np.tile(CalibrationOverlay.CORNER_COLOR, (6, 1))
    np.testing.assert_array_almost_equal(colors, expected)


def test_single_corner_yields_no_vertices() -> None:
    overlay = CalibrationOverlay()
    overlay.set_detection(_corners(1), (640, 480))
    assert overlay.has_detection
    assert overlay.vertices.shape == (0, 2)
    assert overlay.line_count == 0


def test_corners_returns_copy() -> None:
    overlay = CalibrationOverlay()
    corners = _corners(4)
    overlay.set_detection(corners, (640, 480))
    returned = overlay.corners
    assert returned is not None
    returned[0, 0] = 999.0
    # Internal copy unaffected
    np.testing.assert_array_almost_equal(overlay.corners, corners)


def test_set_status_and_progress_clamp() -> None:
    overlay = CalibrationOverlay()
    overlay.set_status(0.5, "Capturing views")
    assert overlay.progress == 0.5
    assert overlay.status_text == "Capturing views"

    overlay.set_status(-1.0, "clamp low")
    assert overlay.progress == 0.0
    overlay.set_status(2.0, "clamp high")
    assert overlay.progress == 1.0


def test_clear_keeps_status_and_enabled() -> None:
    overlay = CalibrationOverlay()
    overlay.set_detection(_corners(4), (640, 480))
    overlay.set_status(0.7, "Calibrating")
    overlay.clear()
    assert not overlay.has_detection
    assert overlay.corner_count == 0
    assert overlay.vertices.shape == (0, 2)
    # Status and enabled flag survive a detection clear
    assert overlay.progress == 0.7
    assert overlay.status_text == "Calibrating"
    assert overlay.enabled


def test_disabled_returns_empty_geometry() -> None:
    overlay = CalibrationOverlay()
    overlay.set_detection(_corners(4), (640, 480))
    overlay.enabled = False
    assert overlay.vertices.shape == (0, 2)
    assert overlay.colors.shape == (0, 4)
    # Re-enabling restores geometry
    overlay.enabled = True
    assert overlay.vertices.shape == (6, 2)


def test_revision_bumps_on_geometry_changes_only() -> None:
    overlay = CalibrationOverlay()
    assert overlay.revision == 0
    overlay.set_detection(_corners(4), (640, 480))
    assert overlay.revision == 1
    overlay.set_status(0.5, "status")  # no geometry change
    assert overlay.revision == 1
    overlay.enabled = False
    assert overlay.revision == 2
    overlay.enabled = False  # no-op toggle
    assert overlay.revision == 2
    overlay.clear()
    assert overlay.revision == 3
