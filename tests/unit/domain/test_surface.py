"""Tests for surface, coordinates, and mesh domain models."""

from __future__ import annotations

import pytest

from projectionai.calibration.types import Mat4x4
from projectionai.domain.coordinates import (
    CoordinateSpace,
    UVConvention,
    projector_pixel_to_uv,
    projector_uv_to_pixel,
    projector_uv_to_surface_uv,
    surface_uv_to_projector_uv,
)
from projectionai.domain.geometry import Mesh
from projectionai.domain.surface import (
    ConfiguredSurface,
    DetectedSurface,
    PhysicalSurface,
    SurfaceDetectionResult,
    SurfaceMeshRef,
    SurfaceType,
    create_cylindrical_surface,
    create_planar_surface,
    create_spherical_surface,
)


class TestSurfaceType:
    """Tests for SurfaceType enum."""

    def test_values_match_projection_type(self) -> None:
        from projectionai.calibration.types import ProjectionType

        for pt in ProjectionType:
            st = SurfaceType.from_projection_type(pt)
            assert st.value == pt.value
            assert st.to_projection_type() == pt

    def test_str_enum_behavior(self) -> None:
        assert SurfaceType.FLAT == "flat"
        assert SurfaceType("cylindrical") == SurfaceType.CYLINDRICAL


class TestPhysicalSurface:
    """Tests for PhysicalSurface base class."""

    def test_default_values(self) -> None:
        surf = PhysicalSurface(id="test1")
        assert surf.id == "test1"
        assert surf.surface_type == SurfaceType.UNKNOWN
        assert surf.width_m == 0.0
        assert surf.height_m == 0.0
        assert surf.depth_m == 0.0
        assert surf.curvature_radius == 0.0
        assert surf.curvature_axis == "y"
        assert surf.material == "white"
        assert surf.reflectance == 0.8
        assert surf.color == (1.0, 1.0, 1.0)

    def test_validation_reflectance(self) -> None:
        with pytest.raises(ValueError, match="reflectance must be in"):
            PhysicalSurface(id="t", reflectance=1.5)
        with pytest.raises(ValueError, match="reflectance must be in"):
            PhysicalSurface(id="t", reflectance=-0.1)

    def test_validation_color(self) -> None:
        with pytest.raises(ValueError, match="color components must be in"):
            PhysicalSurface(id="t", color=(1.5, 0.0, 0.0))
        with pytest.raises(ValueError, match="color components must be in"):
            PhysicalSurface(id="t", color=(0.0, -0.1, 0.0))

    def test_is_planar_flat(self) -> None:
        surf = PhysicalSurface(id="t", surface_type=SurfaceType.FLAT)
        assert surf.is_planar

    def test_is_planar_zero_curvature(self) -> None:
        surf = PhysicalSurface(
            id="t", surface_type=SurfaceType.CYLINDRICAL, curvature_radius=0.0
        )
        assert surf.is_planar

    def test_is_planar_curved(self) -> None:
        surf = PhysicalSurface(
            id="t", surface_type=SurfaceType.CYLINDRICAL, curvature_radius=2.0
        )
        assert not surf.is_planar

    def test_area_planar(self) -> None:
        surf = PhysicalSurface(
            id="t", surface_type=SurfaceType.FLAT, width_m=2.0, height_m=3.0
        )
        assert surf.area_m2 == 6.0

    def test_area_cylindrical(self) -> None:
        surf = PhysicalSurface(
            id="t",
            surface_type=SurfaceType.CYLINDRICAL,
            width_m=2.0,
            height_m=3.0,
            curvature_radius=1.0,
        )
        # Cylindrical segment area: arc_length (width_m) * height_m
        expected = 2.0 * 3.0
        assert abs(surf.area_m2 - expected) < 1e-6


class TestDetectedSurface:
    """Tests for DetectedSurface."""

    def test_default_values(self) -> None:
        surf = DetectedSurface(id="det1")
        assert surf.confidence == 1.0
        assert surf.fully_visible is True
        assert surf.mesh is None
        assert surf.bounding_box is None
        assert surf.normal is None
        assert surf.center is None
        assert surf.homography is None
        assert surf.detection_method == ""
        assert surf.metadata == {}

    def test_equality(self) -> None:
        s1 = DetectedSurface(id="same", width_m=1.0, height_m=2.0, confidence=0.9)
        s2 = DetectedSurface(id="same", width_m=1.0, height_m=2.0, confidence=0.9)
        s3 = DetectedSurface(id="diff", width_m=1.0, height_m=2.0, confidence=0.9)
        assert s1 == s2
        assert s1 != s3

    def test_floating_point_tolerance(self) -> None:
        s1 = DetectedSurface(id="t", width_m=1.0, height_m=2.0)
        s2 = DetectedSurface(id="t", width_m=1.0 + 1e-7, height_m=2.0 + 1e-7)
        assert s1 == s2  # Within tolerance


class TestConfiguredSurface:
    """Tests for ConfiguredSurface."""

    def test_default_values(self) -> None:
        surf = ConfiguredSurface(id="cfg1")
        assert surf.transform == Mat4x4.identity()
        assert surf.uv_min == (0.0, 0.0)
        assert surf.uv_max == (1.0, 1.0)
        assert surf.mesh_vertices == []
        assert surf.mesh_indices == []
        assert surf.label == ""
        assert surf.enabled is True

    def test_validation_uv_bounds(self) -> None:
        with pytest.raises(ValueError, match="uv_min.u < uv_max.u"):
            ConfiguredSurface(id="t", uv_min=(0.5, 0.0), uv_max=(0.5, 1.0))
        with pytest.raises(ValueError, match="uv_min.v < uv_max.v"):
            ConfiguredSurface(id="t", uv_min=(0.0, 0.5), uv_max=(1.0, 0.5))
        with pytest.raises(ValueError, match="in \\[0,1\\]"):
            ConfiguredSurface(id="t", uv_min=(-0.1, 0.0), uv_max=(1.0, 1.0))

    def test_get_world_corners_planar(self) -> None:
        surf = create_planar_surface("test", 2.0, 1.0, label="Test Surface")
        corners = surf.get_world_corners()
        assert len(corners) == 4
        # Corners should form a 2x1 rectangle centered at origin
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        assert max(xs) - min(xs) == pytest.approx(2.0)
        assert max(ys) - min(ys) == pytest.approx(1.0)

    def test_get_world_corners_non_planar_raises(self) -> None:
        surf = create_cylindrical_surface("test", 2.0, 1.0, 1.0)
        with pytest.raises(ValueError, match="Only planar surfaces"):
            surf.get_world_corners()

    def test_equality(self) -> None:
        m44 = Mat4x4.identity()
        s1 = ConfiguredSurface(
            id="same", width_m=1.0, height_m=2.0, transform=m44, label="Test"
        )
        s2 = ConfiguredSurface(
            id="same", width_m=1.0, height_m=2.0, transform=m44, label="Test"
        )
        s3 = ConfiguredSurface(
            id="diff", width_m=1.0, height_m=2.0, transform=m44, label="Test"
        )
        assert s1 == s2
        assert s1 != s3


class TestSurfaceFactories:
    """Tests for surface factory functions."""

    def test_create_planar_surface(self) -> None:
        surf = create_planar_surface("plane1", 3.0, 2.0, label="Wall")
        assert surf.id == "plane1"
        assert surf.surface_type == SurfaceType.FLAT
        assert surf.width_m == 3.0
        assert surf.height_m == 2.0
        assert surf.depth_m == 0.0
        assert surf.label == "Wall"
        assert surf.is_planar

    def test_create_cylindrical_surface(self) -> None:
        surf = create_cylindrical_surface(
            "cyl1", 4.0, 3.0, 2.0, curvature_axis="x", label="Column"
        )
        assert surf.surface_type == SurfaceType.CYLINDRICAL
        assert surf.curvature_radius == 2.0
        assert surf.curvature_axis == "x"
        assert not surf.is_planar

    def test_create_spherical_surface(self) -> None:
        surf = create_spherical_surface("dome1", 5.0, 5.0, 3.0, label="Dome")
        assert surf.surface_type == SurfaceType.SPHERICAL
        assert surf.curvature_radius == 3.0
        assert not surf.is_planar


class TestSurfaceMeshRef:
    """Tests for SurfaceMeshRef."""

    def test_default_values(self) -> None:
        ref = SurfaceMeshRef(asset_id="asset123")
        assert ref.asset_id == "asset123"
        assert ref.uv_bounds == ((0.0, 0.0), (1.0, 1.0))

    def test_custom_uv_bounds(self) -> None:
        ref = SurfaceMeshRef(asset_id="asset123", uv_bounds=((0.1, 0.2), (0.8, 0.9)))
        assert ref.uv_bounds == ((0.1, 0.2), (0.8, 0.9))


class TestSurfaceDetectionResult:
    """Tests for SurfaceDetectionResult."""

    def test_default_values(self) -> None:
        result = SurfaceDetectionResult()
        assert result.surfaces == ()
        assert result.dominant_surface is None
        assert result.coverage == 0.0

    def test_with_surfaces(self) -> None:
        s1 = DetectedSurface(id="s1", width_m=1.0)
        s2 = DetectedSurface(id="s2", width_m=2.0)
        result = SurfaceDetectionResult(
            surfaces=(s1, s2), dominant_surface=s1, coverage=0.75
        )
        assert len(result.surfaces) == 2
        assert result.dominant_surface is s1
        assert result.coverage == 0.75


class TestCoordinates:
    """Tests for coordinate space definitions and conversions."""

    def test_coordinate_space_enum(self) -> None:
        assert CoordinateSpace.SURFACE_LOCAL == "surface_local"
        assert CoordinateSpace.WORLD == "world"
        assert CoordinateSpace.CAMERA == "camera"
        assert CoordinateSpace.PROJECTOR == "projector"
        assert CoordinateSpace.PROJECTOR_UV == "projector_uv"
        assert CoordinateSpace.PROJECTOR_PIXEL == "projector_pixel"

    def test_uv_convention_enum(self) -> None:
        assert UVConvention.OPENGL == "opengl"
        assert UVConvention.IMAGE == "image"
        assert UVConvention.PROJECTOR == "projector"

    def test_surface_uv_to_projector_uv(self) -> None:
        # Surface UV (0,0) bottom-left → Projector UV (0,1) top-left
        assert surface_uv_to_projector_uv((0.0, 0.0)) == (0.0, 1.0)
        # Surface UV (1,1) top-right → Projector UV (1,0) bottom-right
        assert surface_uv_to_projector_uv((1.0, 1.0)) == (1.0, 0.0)
        # Surface UV (0.5, 0.5) center → Projector UV (0.5, 0.5) center
        assert surface_uv_to_projector_uv((0.5, 0.5)) == (0.5, 0.5)
        # Self-inverse
        assert projector_uv_to_surface_uv(surface_uv_to_projector_uv((0.2, 0.7))) == (
            0.2,
            0.7,
        )

    def test_projector_uv_to_pixel(self) -> None:
        # 1920x1080 projector
        assert projector_uv_to_pixel((0.0, 0.0), 1920, 1080) == (0, 0)
        assert projector_uv_to_pixel((1.0, 1.0), 1920, 1080) == (1920, 1080)
        assert projector_uv_to_pixel((0.5, 0.5), 1920, 1080) == (960, 540)

    def test_projector_pixel_to_uv(self) -> None:
        assert projector_pixel_to_uv((0, 0), 1920, 1080) == (0.0, 0.0)
        assert projector_pixel_to_uv((1920, 1080), 1920, 1080) == (1.0, 1.0)
        assert projector_pixel_to_uv((960, 540), 1920, 1080) == pytest.approx(
            (0.5, 0.5)
        )

    def test_roundtrip_uv_pixel(self) -> None:
        uv = (0.3, 0.7)
        px = projector_uv_to_pixel(uv, 1920, 1080)
        uv2 = projector_pixel_to_uv(px, 1920, 1080)
        assert uv2 == pytest.approx(uv, abs=1e-3)


class TestGeometryMesh:
    """Tests for domain.geometry.Mesh."""

    def test_mesh_creation(self) -> None:
        import numpy as np

        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        mesh = Mesh(vertices=vertices, faces=faces)
        assert mesh.num_vertices == 3
        assert mesh.num_faces == 1

    def test_mesh_equality(self) -> None:
        import numpy as np

        v1 = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        f1 = np.array([[0, 1]], dtype=np.int32)
        m1 = Mesh(vertices=v1, faces=f1)
        m2 = Mesh(vertices=v1.copy(), faces=f1.copy())
        m3 = Mesh(vertices=v1 * 2, faces=f1)
        assert m1 == m2
        assert m1 != m3


class TestCoordinateSpaceConstants:
    """Tests that coordinate space constants are defined."""

    def test_constants_exist(self) -> None:
        from projectionai.domain.coordinates import (
            CAMERA_TO_PROJECTOR_PIXEL,
            PROJECTOR_UV_TO_PROJECTOR_PIXEL,
            SURFACE_LOCAL_TO_WORLD,
            SURFACE_UV_TO_PROJECTOR_UV,
            WORLD_TO_CAMERA,
            WORLD_TO_PROJECTOR,
        )

        assert SURFACE_LOCAL_TO_WORLD == "surface_local → world"
        assert WORLD_TO_CAMERA == "world → camera"
        assert WORLD_TO_PROJECTOR == "world → projector"
        assert CAMERA_TO_PROJECTOR_PIXEL == "camera → projector_pixel"
        assert PROJECTOR_UV_TO_PROJECTOR_PIXEL == "projector_uv → projector_pixel"
        assert SURFACE_UV_TO_PROJECTOR_UV == "surface_uv → projector_uv"
