"""Tests for projection transform model."""

from __future__ import annotations

import math

import pytest

from projectionai.calibration.types import Mat4x4
from projectionai.domain.geometry import Vec3 as GeoVec3
from projectionai.domain.transforms import (
    CameraToProjectorTransform,
    CameraToWorldTransform,
    PlanarHomography,
    ProjectorIntrinsics,
    ProjectorToCameraTransform,
    ProjectorToWorldTransform,
    SurfaceLocalToWorldTransform,
    SurfaceToProjectorChain,
    WorldToCameraTransform,
    WorldToProjectorTransform,
    create_camera_to_projector,
    create_projector_intrinsics,
    create_surface_to_world,
    create_world_to_camera,
)


class TestTransformBase:
    """Tests for base Transform class."""

    def test_identity(self) -> None:
        t = SurfaceLocalToWorldTransform()
        point = GeoVec3(1.0, 2.0, 3.0)
        result = t.apply_point(point)
        assert result == point

    def test_translation(self) -> None:
        # Create transform with translation
        mat = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                2.0,
                0.0,
                1.0,
                0.0,
                3.0,
                0.0,
                0.0,
                1.0,
                4.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )
        t = SurfaceLocalToWorldTransform(matrix=mat)
        point = GeoVec3(1.0, 1.0, 1.0)
        result = t.apply_point(point)
        assert result == GeoVec3(3.0, 4.0, 5.0)

    def test_vector_unchanged_by_translation(self) -> None:
        mat = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                2.0,
                0.0,
                1.0,
                0.0,
                3.0,
                0.0,
                0.0,
                1.0,
                4.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )
        t = SurfaceLocalToWorldTransform(matrix=mat)
        vec = GeoVec3(1.0, 2.0, 3.0)
        result = t.apply_vector(vec)
        assert result == vec  # Vectors don't get translated

    def test_inverse(self) -> None:
        mat = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                2.0,
                0.0,
                1.0,
                0.0,
                3.0,
                0.0,
                0.0,
                1.0,
                4.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )
        t = SurfaceLocalToWorldTransform(matrix=mat)
        t_inv = t.inverse()
        point = GeoVec3(5.0, 6.0, 7.0)
        forward = t.apply_point(point)
        backward = t_inv.apply_point(forward)
        assert backward.x == pytest.approx(point.x)
        assert backward.y == pytest.approx(point.y)
        assert backward.z == pytest.approx(point.z)

    def test_compose(self) -> None:
        t1 = SurfaceLocalToWorldTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    0.0,
                    2.0,
                    0.0,
                    0.0,
                    1.0,
                    3.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        t2 = WorldToCameraTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    4.0,
                    0.0,
                    1.0,
                    0.0,
                    5.0,
                    0.0,
                    0.0,
                    1.0,
                    6.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        composed = t1.compose(t2)
        point = GeoVec3(1.0, 1.0, 1.0)
        # t1: +1, +2, +3; t2: +4, +5, +6 -> total: +5, +7, +9
        result = composed.apply_point(point)
        assert result == GeoVec3(6.0, 8.0, 10.0)

    def test_to_numpy_roundtrip(self) -> None:
        t = SurfaceLocalToWorldTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    0.0,
                    2.0,
                    0.0,
                    0.0,
                    1.0,
                    3.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        arr = t.to_numpy()
        t2 = SurfaceLocalToWorldTransform.from_numpy(arr)
        assert t2.matrix == t.matrix


class TestProjectorIntrinsics:
    """Tests for ProjectorIntrinsics projection model."""

    def test_basic_projection(self) -> None:
        """Test basic pinhole projection."""
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        # Point at Z=10m, X=0, Y=0 should project to principal point
        point = GeoVec3(0.0, 0.0, 10.0)
        u, v = intr.project_point(point)
        assert u == pytest.approx(960.0)
        assert v == pytest.approx(540.0)

    def test_projection_with_offset(self) -> None:
        """Test projection with X/Y offset."""
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        # Point at X=1m, Y=0.5m, Z=10m
        point = GeoVec3(1.0, 0.5, 10.0)
        u, v = intr.project_point(point)
        # u = 1000 * (1/10) + 960 = 100 + 960 = 1060
        # v = 1000 * (0.5/10) + 540 = 50 + 540 = 590
        assert u == pytest.approx(1060.0)
        assert v == pytest.approx(590.0)

    def test_behind_projector_raises(self) -> None:
        """Points at or behind projector should raise."""
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        with pytest.raises(ValueError, match="behind or at projector plane"):
            intr.project_point(GeoVec3(0.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="behind or at projector plane"):
            intr.project_point(GeoVec3(0.0, 0.0, -1.0))

    def test_uv_pixel_conversion(self) -> None:
        """Test UV <-> pixel conversion."""
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        # Center pixel
        uv = intr.pixel_to_uv((960.0, 540.0))
        assert uv == pytest.approx((0.5, 0.5))
        # Back to pixel
        px = intr.uv_to_pixel(uv)
        assert px == pytest.approx((960.0, 540.0))

    def test_validation(self) -> None:
        """Test parameter validation."""
        with pytest.raises(ValueError, match="Focal lengths must be positive"):
            ProjectorIntrinsics(
                fx=0.0,
                fy=1000.0,
                cx=960.0,
                cy=540.0,
                resolution_x=1920,
                resolution_y=1080,
            )
        with pytest.raises(ValueError, match="Resolution must be positive"):
            ProjectorIntrinsics(
                fx=1000.0,
                fy=1000.0,
                cx=960.0,
                cy=540.0,
                resolution_x=0,
                resolution_y=1080,
            )


class TestCoordinateTransforms:
    """Tests for explicit coordinate space transforms."""

    def test_world_to_camera_from_extrinsics(self) -> None:
        """WorldToCameraTransform is inverse of CameraExtrinsics.transform."""
        # Camera at (10, 20, 30) in world
        cam_transform = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                10.0,
                0.0,
                1.0,
                0.0,
                20.0,
                0.0,
                0.0,
                1.0,
                30.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )

        # Mock camera extrinsics
        class MockExtrinsics:
            transform = cam_transform

        w2c = WorldToCameraTransform.from_camera_extrinsics(MockExtrinsics())
        # World point at camera position should map to origin
        point = GeoVec3(10.0, 20.0, 30.0)
        result = w2c.apply_point(point)
        assert result == GeoVec3(0.0, 0.0, 0.0)

    def test_camera_to_world_from_extrinsics(self) -> None:
        """CameraToWorldTransform equals CameraExtrinsics.transform."""
        cam_transform = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                10.0,
                0.0,
                1.0,
                0.0,
                20.0,
                0.0,
                0.0,
                1.0,
                30.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )

        class MockExtrinsics:
            transform = cam_transform

        c2w = CameraToWorldTransform.from_camera_extrinsics(MockExtrinsics)
        point = GeoVec3(0.0, 0.0, 0.0)  # Camera origin
        result = c2w.apply_point(point)
        assert result == GeoVec3(10.0, 20.0, 30.0)

    def test_projector_to_world_from_extrinsics(self) -> None:
        """ProjectorToWorldTransform equals ProjectorExtrinsics.transform."""
        proj_transform = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                5.0,
                0.0,
                1.0,
                0.0,
                6.0,
                0.0,
                0.0,
                1.0,
                7.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )

        class MockExtrinsics:
            transform = proj_transform

        p2w = ProjectorToWorldTransform.from_projector_extrinsics(MockExtrinsics)
        point = GeoVec3(0.0, 0.0, 0.0)
        result = p2w.apply_point(point)
        assert result == GeoVec3(5.0, 6.0, 7.0)

    def test_world_to_projector_from_extrinsics(self) -> None:
        """WorldToProjectorTransform is inverse of ProjectorExtrinsics.transform."""
        proj_transform = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                5.0,
                0.0,
                1.0,
                0.0,
                6.0,
                0.0,
                0.0,
                1.0,
                7.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )

        class MockExtrinsics:
            transform = proj_transform

        w2p = WorldToProjectorTransform.from_projector_extrinsics(MockExtrinsics)
        point = GeoVec3(5.0, 6.0, 7.0)  # Projector position in world
        result = w2p.apply_point(point)
        assert result == GeoVec3(0.0, 0.0, 0.0)

    def test_camera_to_projector_from_pose(self) -> None:
        """CameraToProjectorTransform is inverse of projector pose (projector_local -> camera)."""
        # Projector at (1, 2, 3) in camera frame
        pose = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                1.0,
                0.0,
                1.0,
                0.0,
                2.0,
                0.0,
                0.0,
                1.0,
                3.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )
        c2p = CameraToProjectorTransform.from_projector_pose(pose)
        # Camera origin in camera frame should be at projector position in projector frame
        # Wait: pose maps projector_local -> camera_frame
        # c2p = inverse(pose) maps camera_frame -> projector_local
        # Camera origin (0,0,0) in camera frame -> (-1, -2, -3) in projector frame
        result = c2p.apply_point(GeoVec3(0.0, 0.0, 0.0))
        assert result == GeoVec3(-1.0, -2.0, -3.0)

    def test_projector_to_camera_from_pose(self) -> None:
        """ProjectorToCameraTransform equals projector pose (projector_local -> camera_frame)."""
        pose = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                1.0,
                0.0,
                1.0,
                0.0,
                2.0,
                0.0,
                0.0,
                1.0,
                3.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )
        p2c = ProjectorToCameraTransform.from_projector_pose(pose)
        point = GeoVec3(0.0, 0.0, 0.0)  # Projector origin
        result = p2c.apply_point(point)
        assert result == GeoVec3(1.0, 2.0, 3.0)


class TestSurfaceToProjectorChain:
    """Tests for the complete surface-to-projector transform chain."""

    def test_identity_chain(self) -> None:
        """Test chain with all identity transforms."""
        surface_to_world = SurfaceLocalToWorldTransform()
        world_to_camera = WorldToCameraTransform()
        camera_to_projector = CameraToProjectorTransform()
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        chain = SurfaceToProjectorChain(
            surface_to_world=surface_to_world,
            world_to_camera=world_to_camera,
            camera_to_projector=camera_to_projector,
            projector_intrinsics=intr,
        )
        # Point at Z=10m should project to principal point
        point = GeoVec3(0.0, 0.0, 10.0)
        u, v = chain.project_surface_point(point)
        assert u == pytest.approx(960.0)
        assert v == pytest.approx(540.0)

    def test_with_translated_surface(self) -> None:
        """Test chain with surface translated in world."""
        # Surface at (1, 2, 0) in world
        surface_to_world = SurfaceLocalToWorldTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    0.0,
                    2.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        world_to_camera = WorldToCameraTransform()
        camera_to_projector = CameraToProjectorTransform()
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        chain = SurfaceToProjectorChain(
            surface_to_world=surface_to_world,
            world_to_camera=world_to_camera,
            camera_to_projector=camera_to_projector,
            projector_intrinsics=intr,
        )
        # Point at surface origin (0,0,0) -> world (1,2,0) -> camera (1,2,0) -> projector (1,2,0) -> pixels
        # At Z=0, this is problematic (division by zero), so use a point with Z>0
        point = GeoVec3(0.0, 0.0, 10.0)  # 10m in front of surface
        # Surface local (0,0,10) -> world (1,2,10) -> camera (1,2,10) -> projector (1,2,10)
        u, v = chain.project_surface_point(point)
        # X=1, Z=10 -> u = 1000*(1/10) + 960 = 1060
        # Y=2, Z=10 -> v = 1000*(2/10) + 540 = 740
        assert u == pytest.approx(1060.0)
        assert v == pytest.approx(740.0)

    def test_direct_path_bypasses_world(self) -> None:
        """Test direct surface->camera path bypasses world transform."""
        surface_to_world = SurfaceLocalToWorldTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    100.0,  # Large offset that should be ignored
                    0.0,
                    1.0,
                    0.0,
                    200.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        world_to_camera = WorldToCameraTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    50.0,  # Also large
                    0.0,
                    1.0,
                    0.0,
                    60.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        # Direct path: surface at identity in camera frame
        surface_to_camera = SurfaceLocalToWorldTransform()  # Reusing type for identity
        camera_to_projector = CameraToProjectorTransform()
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        chain = SurfaceToProjectorChain(
            surface_to_world=surface_to_world,
            world_to_camera=world_to_camera,
            camera_to_projector=camera_to_projector,
            projector_intrinsics=intr,
            surface_to_camera=surface_to_camera,
        )
        # With direct path, surface origin at Z=10 should project to principal point
        point = GeoVec3(0.0, 0.0, 10.0)
        u, v = chain.project_surface_point(point, use_direct_path=True)
        assert u == pytest.approx(960.0)
        assert v == pytest.approx(540.0)

        # Without direct path, world offset applies
        u2, v2 = chain.project_surface_point(point, use_direct_path=False)
        # surface_local(0,0,10) -> world(100,200,10) -> camera(150,260,10)
        assert u2 != 960.0
        assert v2 != 540.0


class TestPlanarHomography:
    """Tests for planar homography optimization."""

    def test_homography_with_realistic_transforms(self) -> None:
        """Homography with realistic transforms (surface in front of projector)."""
        # Surface at Z=5m in front of projector
        surface_to_world = SurfaceLocalToWorldTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    5.0,  # Surface at Z=5m in world
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        # Camera at world origin
        world_to_camera = WorldToCameraTransform()
        # Projector at world origin, looking along +Z
        camera_to_projector = CameraToProjectorTransform()
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        H = PlanarHomography.from_surface_to_projector(
            surface_to_world, world_to_camera, camera_to_projector, intr
        )
        # Surface center (0,0,0) at world Z=5 -> camera Z=5 -> projector Z=5
        # Point at surface center: X=0, Y=0, Z=5 in projector
        # u = 1000*(0/5) + 960 = 960, v = 1000*(0/5) + 540 = 540
        u, v = H.apply_local_point(GeoVec3(0.0, 0.0, 0.0))
        assert u == pytest.approx(960.0)
        assert v == pytest.approx(540.0)

    def test_homography_matches_chain(self) -> None:
        """Homography should produce same result as full chain for Z=0 points."""
        # Surface at Z=5m
        surface_to_world = SurfaceLocalToWorldTransform(
            matrix=Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                    5.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )
        )
        world_to_camera = WorldToCameraTransform()
        camera_to_projector = CameraToProjectorTransform()
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        H = PlanarHomography.from_surface_to_projector(
            surface_to_world, world_to_camera, camera_to_projector, intr
        )
        chain = SurfaceToProjectorChain(
            surface_to_world=surface_to_world,
            world_to_camera=world_to_camera,
            camera_to_projector=camera_to_projector,
            projector_intrinsics=intr,
        )
        # Test points on Z=0 plane (surface-local)
        for x, y in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (-1.0, -1.0)]:
            u_h, v_h = H.apply_local_point(GeoVec3(x, y, 0.0))
            u_c, v_c = chain.project_surface_point(GeoVec3(x, y, 0.0))
            assert u_h == pytest.approx(u_c, rel=1e-6)
            assert v_h == pytest.approx(v_c, rel=1e-6)

    def test_homography_infinity_handling(self) -> None:
        """Points where Z_p=0 should raise."""
        # Create homography where Z_p = 0 for some points
        # Use identity chain (degenerate - surface at projector lens)
        surface_to_world = SurfaceLocalToWorldTransform()
        world_to_camera = WorldToCameraTransform()
        camera_to_projector = CameraToProjectorTransform()
        intr = ProjectorIntrinsics(
            fx=1000.0,
            fy=1000.0,
            cx=960.0,
            cy=540.0,
            resolution_x=1920,
            resolution_y=1080,
        )
        H = PlanarHomography.from_surface_to_projector(
            surface_to_world, world_to_camera, camera_to_projector, intr
        )
        # Point at surface origin maps to Z=0 in projector frame -> infinity
        with pytest.raises(ValueError, match="infinity"):
            H.apply_local_point(GeoVec3(0.0, 0.0, 0.0))


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_surface_to_world(self) -> None:
        class MockSurface:
            transform = Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    5.0,
                    0.0,
                    1.0,
                    0.0,
                    6.0,
                    0.0,
                    0.0,
                    1.0,
                    7.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )

        t = create_surface_to_world(MockSurface())
        assert t.matrix == MockSurface.transform

    def test_create_world_to_camera(self) -> None:
        class MockExtrinsics:
            transform = Mat4x4(
                data=(
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    0.0,
                    1.0,
                    0.0,
                    2.0,
                    0.0,
                    0.0,
                    1.0,
                    3.0,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
            )

        t = create_world_to_camera(MockExtrinsics())
        point = GeoVec3(1.0, 2.0, 3.0)  # Camera position in world
        result = t.apply_point(point)
        assert result == GeoVec3(0.0, 0.0, 0.0)

    def test_create_camera_to_projector(self) -> None:
        pose = Mat4x4(
            data=(
                1.0,
                0.0,
                0.0,
                1.0,
                0.0,
                1.0,
                0.0,
                2.0,
                0.0,
                0.0,
                1.0,
                3.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )
        t = create_camera_to_projector(pose)
        # Camera origin -> projector frame
        result = t.apply_point(GeoVec3(0.0, 0.0, 0.0))
        assert result == GeoVec3(-1.0, -2.0, -3.0)

    def test_create_projector_intrinsics(self) -> None:
        intr = create_projector_intrinsics(1000.0, 1000.0, 960.0, 540.0, 1920, 1080)
        assert intr.fx == 1000.0
        assert intr.fy == 1000.0
        assert intr.cx == 960.0
        assert intr.cy == 540.0
        assert intr.resolution == (1920, 1080)
