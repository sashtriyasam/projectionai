"""Tests for OverlayPass calibration corner overlay (state only, no GL)."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.infrastructure.renderer.passes.overlay import OverlayPass


def test_corner_lines_default_none() -> None:
    overlay_pass = OverlayPass()
    assert overlay_pass._corner_lines is None
    assert not overlay_pass._corner_dirty


def test_set_corner_lines_stores_copy() -> None:
    overlay_pass = OverlayPass()
    corners = np.array([[0, 0], [100, 0], [100, 100]], dtype=np.float32)
    overlay_pass.set_corner_lines(corners)
    assert overlay_pass._corner_lines is not None
    assert overlay_pass._corner_dirty

    # Mutating the input must not affect the stored copy
    corners[0, 0] = 999.0
    assert overlay_pass._corner_lines[0, 0] == 0.0
    np.testing.assert_array_almost_equal(
        overlay_pass._corner_lines,
        np.array([[0, 0], [100, 0], [100, 100]], dtype=np.float32),
    )


def test_set_corner_lines_none_clears() -> None:
    overlay_pass = OverlayPass()
    overlay_pass.set_corner_lines(np.zeros((4, 2), dtype=np.float32))
    overlay_pass.set_corner_lines(None)
    assert overlay_pass._corner_lines is None
    assert overlay_pass._corner_dirty


def test_set_corner_lines_invalid_shape_raises() -> None:
    overlay_pass = OverlayPass()
    with pytest.raises(ValueError, match="(M, 2)"):
        overlay_pass.set_corner_lines(np.zeros((4, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="(M, 2)"):
        overlay_pass.set_corner_lines(np.zeros((4,), dtype=np.float32))
    assert overlay_pass._corner_lines is None
