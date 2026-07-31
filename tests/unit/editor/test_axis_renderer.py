"""Tests for AxisRenderer — verifies axis vertex generation."""

from __future__ import annotations

import numpy as np

from projectionai.editor.axis_renderer import AxisRenderer


def test_default_state() -> None:
    axes = AxisRenderer()
    assert axes.enabled
    assert axes.size == 1.0


def test_axis_vertices() -> None:
    axes = AxisRenderer()
    verts = axes.vertices
    assert verts.shape == (6, 3)  # 3 axes x 2 vertices each


def test_axis_colors() -> None:
    axes = AxisRenderer()
    colors = axes.colors
    assert colors.shape == (6, 3)
    # X axis should be red
    np.testing.assert_array_almost_equal(colors[0], [1.0, 0.2, 0.2])
    np.testing.assert_array_almost_equal(colors[1], [1.0, 0.2, 0.2])
    # Y axis should be green
    np.testing.assert_array_almost_equal(colors[2], [0.2, 1.0, 0.2])
    np.testing.assert_array_almost_equal(colors[3], [0.2, 1.0, 0.2])
    # Z axis should be blue
    np.testing.assert_array_almost_equal(colors[4], [0.2, 0.4, 1.0])
    np.testing.assert_array_almost_equal(colors[5], [0.2, 0.4, 1.0])


def test_origin_at_zero() -> None:
    axes = AxisRenderer()
    verts = axes.vertices
    # First vertex of each axis pair is at the origin
    assert np.allclose(verts[0], [0.0, 0.0, 0.0])
    assert np.allclose(verts[2], [0.0, 0.0, 0.0])
    assert np.allclose(verts[4], [0.0, 0.0, 0.0])


def test_axis_lengths() -> None:
    axes = AxisRenderer()
    verts = axes.vertices
    # Each axis tip should be at size distance from origin
    assert np.allclose(verts[1], [1.0, 0.0, 0.0])  # X tip
    assert np.allclose(verts[3], [0.0, 1.0, 0.0])  # Y tip
    assert np.allclose(verts[5], [0.0, 0.0, 1.0])  # Z tip


def test_size_change() -> None:
    axes = AxisRenderer()
    axes.size = 2.5
    assert axes.size == 2.5
    verts = axes.vertices
    assert np.allclose(verts[1], [2.5, 0.0, 0.0])
    assert np.allclose(verts[3], [0.0, 2.5, 0.0])
    assert np.allclose(verts[5], [0.0, 0.0, 2.5])


def test_custom_origin() -> None:
    axes = AxisRenderer()
    axes.origin = (10.0, 20.0, 30.0)
    verts = axes.vertices
    assert np.allclose(verts[0], [10.0, 20.0, 30.0])
    assert np.allclose(verts[1], [11.0, 20.0, 30.0])  # +X


def test_clamp_size() -> None:
    axes = AxisRenderer()
    axes.size = -1.0
    assert axes.size == 0.01  # clamped


def test_disable() -> None:
    axes = AxisRenderer()
    assert axes.enabled
    axes.enabled = False
    assert not axes.enabled


def test_axis_colors_consistent_after_rebuild() -> None:
    """Changing size should keep colours consistent (triggers rebuild)."""
    axes = AxisRenderer()
    axes.size = 5.0
    colors = axes.colors
    assert colors.shape == (6, 3)
    # X is still red
    np.testing.assert_array_almost_equal(colors[0], [1.0, 0.2, 0.2])
