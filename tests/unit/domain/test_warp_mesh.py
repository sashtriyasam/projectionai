"""Tests for WarpMesh domain type and planar grid generation.

Covers Section 2 (WarpMesh contract) and Section 4 (planar reference case).
"""


import numpy as np
import pytest

from projectionai.domain.warp_mesh import (
    WarpMesh,
    WarpMeshGeneration,
    create_identity_warp_mesh,
    create_planar_grid_warp_mesh,
)

# =============================================================================
# WarpMesh construction & properties
# =============================================================================


class TestWarpMeshConstruction:
    """Test WarpMesh dataclass construction and derived properties."""

    def test_empty_mesh(self) -> None:
        mesh = WarpMesh()
        assert mesh.num_vertices == 0
        assert mesh.num_faces == 0
        assert not mesh.has_content

    def test_populated_mesh(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        puvs = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float64)
        cuvs = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float64)
        idx = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = WarpMesh(
            surface_id="s1",
            projector_id="p1",
            vertices=verts,
            projector_uvs=puvs,
            content_uvs=cuvs,
            indices=idx,
        )
        assert mesh.num_vertices == 3
        assert mesh.num_faces == 1
        assert mesh.has_content
        assert mesh.surface_id == "s1"
        assert mesh.projector_id == "p1"

    def test_frozen(self) -> None:
        mesh = WarpMesh(surface_id="s1")
        with pytest.raises(AttributeError):
            mesh.surface_id = "s2"  # type: ignore[misc]


# =============================================================================
# Validation
# =============================================================================


class TestWarpMeshValidation:
    """Test WarpMesh.validate() catches all error conditions."""

    def test_valid_mesh(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        puvs = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float64)
        cuvs = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float64)
        idx = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = WarpMesh(
            surface_id="s1",
            projector_id="p1",
            vertices=verts,
            projector_uvs=puvs,
            content_uvs=cuvs,
            indices=idx,
        )
        errors = mesh.validate()
        assert errors == []

    def test_invalid_vertices_shape(self) -> None:
        verts = np.array([[0, 0], [1, 0]], dtype=np.float64)  # (2, 2) not (2, 3)
        mesh = WarpMesh(vertices=verts)
        errors = mesh.validate()
        assert any("vertices must be (V, 3)" in e for e in errors)

    def test_invalid_projector_uvs_shape(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        puvs = np.array([[0, 1, 0.5]], dtype=np.float64)  # (1, 3) not (2, 2)
        cuvs = np.zeros((2, 2), dtype=np.float64)
        idx = np.zeros((0, 3), dtype=np.int32)
        mesh = WarpMesh(
            vertices=verts, projector_uvs=puvs, content_uvs=cuvs, indices=idx
        )
        errors = mesh.validate()
        assert any("projector_uvs shape" in e for e in errors)

    def test_invalid_content_uvs_shape(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        puvs = np.zeros((2, 2), dtype=np.float64)
        cuvs = np.array([[0, 1, 0.5]], dtype=np.float64)  # wrong shape
        idx = np.zeros((0, 3), dtype=np.int32)
        mesh = WarpMesh(
            vertices=verts, projector_uvs=puvs, content_uvs=cuvs, indices=idx
        )
        errors = mesh.validate()
        assert any("content_uvs shape" in e for e in errors)

    def test_invalid_indices_shape(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        puvs = np.zeros((2, 2), dtype=np.float64)
        cuvs = np.zeros((2, 2), dtype=np.float64)
        idx = np.array([[0, 1]], dtype=np.int32)  # (1, 2) not (1, 3)
        mesh = WarpMesh(
            vertices=verts, projector_uvs=puvs, content_uvs=cuvs, indices=idx
        )
        errors = mesh.validate()
        assert any("indices must be (F, 3)" in e for e in errors)

    def test_projector_uvs_out_of_range(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        puvs = np.array([[0, 1], [1.5, 1], [0, 0]], dtype=np.float64)  # 1.5 > 1
        cuvs = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float64)
        idx = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = WarpMesh(
            vertices=verts, projector_uvs=puvs, content_uvs=cuvs, indices=idx
        )
        errors = mesh.validate()
        assert any("projector_uvs out of [0,1]" in e for e in errors)

    def test_content_uvs_out_of_range(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        puvs = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float64)
        cuvs = np.array([[0, -0.1], [1, 0], [0, 1]], dtype=np.float64)  # -0.1 < 0
        idx = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = WarpMesh(
            vertices=verts, projector_uvs=puvs, content_uvs=cuvs, indices=idx
        )
        errors = mesh.validate()
        assert any("content_uvs out of [0,1]" in e for e in errors)

    def test_index_out_of_bounds(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        puvs = np.zeros((2, 2), dtype=np.float64)
        cuvs = np.zeros((2, 2), dtype=np.float64)
        idx = np.array([[0, 1, 5]], dtype=np.int32)  # 5 >= 2 vertices
        mesh = WarpMesh(
            vertices=verts, projector_uvs=puvs, content_uvs=cuvs, indices=idx
        )
        errors = mesh.validate()
        assert any("indices range" in e for e in errors)


# =============================================================================
# Serialisation round-trip
# =============================================================================


class TestWarpMeshSerialisation:
    """Test to_dict / from_dict round-trip."""

    def test_round_trip(self) -> None:
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        puvs = np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float64)
        cuvs = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float64)
        idx = np.array([[0, 1, 2]], dtype=np.int32)
        original = WarpMesh(
            surface_id="s1",
            projector_id="p1",
            vertices=verts,
            projector_uvs=puvs,
            content_uvs=cuvs,
            indices=idx,
            grid_rows=2,
            grid_cols=3,
            generation_method=WarpMeshGeneration.CALIBRATION,
            metadata={"source": "test"},
        )
        data = original.to_dict()
        restored = WarpMesh.from_dict(data)
        assert restored == original
        assert restored.metadata == {"source": "test"}


# =============================================================================
# to_geometry_mesh conversion
# =============================================================================


class TestToGeometryMesh:
    """Test conversion to geometry.Mesh for GPU upload."""

    def test_conversion(self) -> None:
        mesh = create_identity_warp_mesh(100, 100, grid_rows=1, grid_cols=1)
        geom = mesh.to_geometry_mesh()
        assert geom.vertices.shape == (4, 3)
        assert geom.faces.shape == (2, 3)
        assert geom.uv_coords.shape == (4, 2)


# =============================================================================
# Planar grid generation
# =============================================================================


class TestPlanarGridGeneration:
    """Test create_planar_grid_warp_mesh factory."""

    def test_simple_grid(self) -> None:
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=2.0,
            height_m=1.0,
            grid_rows=2,
            grid_cols=3,
            projector_uv_corners=(
                (0.0, 1.0),  # BL
                (1.0, 1.0),  # BR
                (1.0, 0.0),  # TR
                (0.0, 0.0),  # TL
            ),
        )
        # Vertices = (rows+1) * (cols+1) = 3 * 4 = 12
        assert mesh.num_vertices == 12
        # Triangles = rows * cols * 2 = 2 * 3 * 2 = 12
        assert mesh.num_faces == 12
        assert mesh.grid_rows == 2
        assert mesh.grid_cols == 3

    def test_vertices_in_surface_local(self) -> None:
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=2.0,
            height_m=2.0,
            grid_rows=1,
            grid_cols=1,
            projector_uv_corners=(
                (0.0, 1.0),
                (1.0, 1.0),
                (1.0, 0.0),
                (0.0, 0.0),
            ),
        )
        # 4 vertices for 1x1 grid
        # BL: (-1, -1, 0), BR: (1, -1, 0), TR: (1, 1, 0), TL: (-1, 1, 0)
        verts = mesh.vertices
        assert verts.shape == (4, 3)
        # Z should be 0 (planar)
        np.testing.assert_allclose(verts[:, 2], 0.0)

    def test_content_uvs_cover_01(self) -> None:
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=1.0,
            height_m=1.0,
            grid_rows=4,
            grid_cols=4,
            projector_uv_corners=(
                (0.0, 1.0),
                (1.0, 1.0),
                (1.0, 0.0),
                (0.0, 0.0),
            ),
        )
        # Content UVs should span [0,1] x [0,1]
        assert float(mesh.content_uvs.min()) == pytest.approx(0.0, abs=1e-10)
        assert float(mesh.content_uvs.max()) == pytest.approx(1.0, abs=1e-10)

    def test_corner_content_uvs(self) -> None:
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=1.0,
            height_m=1.0,
            grid_rows=1,
            grid_cols=1,
            projector_uv_corners=(
                (0.0, 1.0),
                (1.0, 1.0),
                (1.0, 0.0),
                (0.0, 0.0),
            ),
        )
        # Row-major iteration order: BL, BR, TL, TR
        cuvs = mesh.content_uvs
        np.testing.assert_allclose(cuvs[0], [0.0, 0.0], atol=1e-10)  # BL
        np.testing.assert_allclose(cuvs[1], [1.0, 0.0], atol=1e-10)  # BR
        np.testing.assert_allclose(cuvs[2], [0.0, 1.0], atol=1e-10)  # TL
        np.testing.assert_allclose(cuvs[3], [1.0, 1.0], atol=1e-10)  # TR

    def test_validates_cleanly(self) -> None:
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=2.0,
            height_m=1.5,
            grid_rows=8,
            grid_cols=12,
            projector_uv_corners=(
                (0.1, 0.9),
                (0.9, 0.9),
                (0.9, 0.1),
                (0.1, 0.1),
            ),
        )
        errors = mesh.validate()
        assert errors == []

    def test_single_triangle_indices(self) -> None:
        """A 1x1 grid should have exactly 2 triangles (6 indices total)."""
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=1.0,
            height_m=1.0,
            grid_rows=1,
            grid_cols=1,
            projector_uv_corners=(
                (0.0, 1.0),
                (1.0, 1.0),
                (1.0, 0.0),
                (0.0, 0.0),
            ),
        )
        assert mesh.indices.shape == (2, 3)
        # All indices should be in [0, 3]
        assert mesh.indices.min() >= 0
        assert mesh.indices.max() <= 3


# =============================================================================
# Identity warp mesh
# =============================================================================


class TestIdentityWarpMesh:
    """Test create_identity_warp_mesh for Section 4 planar reference."""

    def test_identity_construction(self) -> None:
        mesh = create_identity_warp_mesh(100, 100)
        assert mesh.num_vertices == 4
        assert mesh.num_faces == 2
        assert mesh.surface_id == "identity_surface"
        assert mesh.projector_id == "identity_projector"

    def test_identity_uv_corners(self) -> None:
        mesh = create_identity_warp_mesh(100, 100)
        # Row-major iteration: BL, BR, TL, TR
        puvs = mesh.projector_uvs
        np.testing.assert_allclose(puvs[0], [0.0, 1.0], atol=1e-10)  # BL
        np.testing.assert_allclose(puvs[1], [1.0, 1.0], atol=1e-10)  # BR
        np.testing.assert_allclose(puvs[2], [0.0, 0.0], atol=1e-10)  # TL
        np.testing.assert_allclose(puvs[3], [1.0, 0.0], atol=1e-10)  # TR

    def test_identity_grid_subdivisions(self) -> None:
        mesh = create_identity_warp_mesh(100, 100, grid_rows=4, grid_cols=4)
        assert mesh.num_vertices == 25  # (4+1)^2
        assert mesh.num_faces == 32  # 4*4*2


# =============================================================================
# WarpMeshGeneration enum
# =============================================================================


class TestWarpMeshGeneration:
    def test_all_values(self) -> None:
        assert WarpMeshGeneration.GRID.value == "grid"
        assert WarpMeshGeneration.EXPLICIT.value == "explicit"
        assert WarpMeshGeneration.CALIBRATION.value == "calibration"
        assert WarpMeshGeneration.IMPORTED.value == "imported"
