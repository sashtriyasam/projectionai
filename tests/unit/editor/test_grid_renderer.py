"""Tests for GridRenderer — verifies grid vertex generation."""

from __future__ import annotations

import numpy as np

from projectionai.editor.grid_renderer import GridRenderer


def test_default_grid() -> None:
    grid = GridRenderer()
    assert grid.enabled
    assert grid.size == 20
    assert grid.subdivisions == 10


def test_grid_vertices_shape() -> None:
    grid = GridRenderer()
    verts = grid.vertices
    # Each line segment is 2 vertices
    assert verts.shape[1] == 3
    assert verts.shape[0] > 0
    # All vertices should be on the Y=0 plane
    assert np.allclose(verts[:, 1], 0.0)


def test_grid_vertex_colors() -> None:
    grid = GridRenderer()
    colors = grid.vertex_colors
    assert colors.shape == grid.vertices.shape
    assert np.all(colors >= 0.0) and np.all(colors <= 1.0)


def test_grid_line_count() -> None:
    grid = GridRenderer()
    # (subdivisions+1) lines along X + (subdivisions+1) lines along Z
    expected_lines = 2 * (grid.subdivisions + 1)
    assert grid.line_count == expected_lines


def test_grid_size_change() -> None:
    grid = GridRenderer()
    grid.size = 10
    assert grid.size == 10

    # Should not go below 1
    grid.size = 0
    assert grid.size == 1


def test_grid_subdivisions_change() -> None:
    grid = GridRenderer()
    grid.subdivisions = 5
    assert grid.subdivisions == 5

    # Should trigger rebuild
    grid.rebuild()
    assert grid.line_count == 2 * (5 + 1)


def test_opacity_clamp() -> None:
    grid = GridRenderer()
    grid.opacity = 1.5
    assert grid.opacity == 1.0
    grid.opacity = -0.5
    assert grid.opacity == 0.0


def test_color_mutation() -> None:
    grid = GridRenderer()
    grid.color = (0.5, 0.5, 0.5)
    assert grid.color == (0.5, 0.5, 0.5)


def test_disable() -> None:
    grid = GridRenderer()
    assert grid.enabled
    grid.enabled = False
    assert not grid.enabled


def test_vertices_all_on_y_plane() -> None:
    """All grid vertices must lie on the XZ plane."""
    grid = GridRenderer()
    verts = grid.vertices
    assert np.allclose(verts[:, 1], 0.0)
