"""Phase 6.8 warp pipeline tests — synthetic golden + homography + persistence."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.domain.calibration_session import CalibrationMethod, CalibrationResult
from projectionai.domain.geometry import Pose, Vec3
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.transforms import (
    PlanarHomography,
    ProjectorIntrinsics,
    Transform,
)
from projectionai.domain.warp_mesh import WarpMesh
from projectionai.services.calibration import (
    CalibrationToWarpMeshError,
    calibration_to_warp_mesh,
    create_projection_mapping,
)


def _cal(
    fx: float = 1280.0,
    fy: float = 1280.0,
    pose: np.ndarray | None = None,
    obj_z: float = 2.0,
    res: tuple[int, int] = (1280, 720),
    seq_ids: tuple[str, ...] = ("seq-1", "seq-2"),
) -> CalibrationResult:
    if pose is None:
        pose = np.eye(4)
    K = np.array([[fx, 0, 640.0], [0, fy, 360.0], [0, 0, 1.0]], float)
    obj_pose = Pose(position=Vec3(0, 0, obj_z))
    return CalibrationResult(
        calibration_id="cal-1",
        sequence_id=seq_ids[0],
        method=CalibrationMethod.GRAY_CODE,
        projector_id="p0",
        camera_id="c0",
        surface_id="s0",
        projector_intrinsics=K,
        projector_pose=pose,
        projector_resolution=res,
        reprojection_error=0.5,
        coverage=0.8,
        num_correspondences=8000,
        confidence=0.9,
        calibration_sequence_ids=seq_ids,
        object_pose=obj_pose,
    )


# ---------------------------------------------------------------------------
# Golden synthetic
# ---------------------------------------------------------------------------


class TestGoldenSynthetic:
    def test_identity(self) -> None:
        cal = _cal(obj_z=2.0)
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=8, grid_cols=8)
        assert mesh.validate() == []
        # Center should map near (0.5, 0.5) projector UV
        # Find center vertex (s=0.5, t=0.5) at index for 8x8 grid: row 4, col 4
        idx = 4 * 9 + 4
        u, v = mesh.projector_uvs[idx]
        assert 0.49 < u < 0.51
        assert 0.49 < v < 0.51

    def test_translated_projector(self) -> None:
        pose = np.eye(4)
        pose[0, 3] = 0.5
        cal = _cal(pose=pose, obj_z=2.0)
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=4, grid_cols=4)
        assert mesh.validate() == []

    def test_rotated_projector(self) -> None:
        angle = np.radians(15)
        pose = np.eye(4)
        pose[:3, :3] = np.array(
            [
                [np.cos(angle), 0, np.sin(angle)],
                [0, 1, 0],
                [-np.sin(angle), 0, np.cos(angle)],
            ]
        )
        cal = CalibrationResult(
            calibration_id="cal-1",
            sequence_id="seq-1",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="p0",
            camera_id="c0",
            surface_id="s0",
            projector_intrinsics=np.array(
                [[1280, 0, 640], [0, 1280, 360], [0, 0, 1]], float
            ),
            projector_pose=pose,
            projector_resolution=(1280, 720),
            reprojection_error=0.5,
            coverage=0.8,
            num_correspondences=8000,
            confidence=0.9,
            calibration_sequence_ids=("seq-1", "seq-2"),
            object_pose=Pose(position=Vec3(0, 0, 2.0)),
        )
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=4, grid_cols=4)
        assert mesh.validate() == []

    def test_uv_corners(self) -> None:
        cal = _cal(obj_z=2.0)
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0, grid_rows=1, grid_cols=1)
        assert mesh.projector_uvs.shape == (4, 2)
        assert np.all(mesh.projector_uvs >= -1e-6) and np.all(
            mesh.projector_uvs <= 1 + 1e-6
        )
        # Content UVs: bottom-left origin, V up (0 bottom, 1 top) — 1x1 grid has 4 corners
        assert mesh.content_uvs.shape == (4, 2)
        assert set(map(tuple, np.round(mesh.content_uvs, 6).tolist())) == {
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
        }
        # Projector UVs: bottom-left origin, V up — bottom vertices have smaller V than top (matches actual NDC mapping)
        assert mesh.projector_uvs[0, 1] < mesh.projector_uvs[2, 1]
        assert mesh.projector_uvs[1, 1] < mesh.projector_uvs[3, 1]

    def test_high_res_grid(self) -> None:
        cal = _cal(obj_z=2.0)
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=32, grid_cols=32)
        assert mesh.num_vertices == 1089
        assert mesh.validate() == []


# ---------------------------------------------------------------------------
# Invalid geometry
# ---------------------------------------------------------------------------


class TestInvalidGeometry:
    def test_behind_projector(self) -> None:
        # Surface behind projector (obj_z negative with projector at origin)
        cal = _cal(obj_z=-2.0)
        with pytest.raises(CalibrationToWarpMeshError, match="behind projector"):
            calibration_to_warp_mesh(cal, 0.5, 0.3)

    def test_invalid_surface_dims(self) -> None:
        cal = _cal()
        with pytest.raises(
            CalibrationToWarpMeshError, match="Surface dimensions must be positive"
        ):
            calibration_to_warp_mesh(cal, 0, 0.3)
        with pytest.raises(
            CalibrationToWarpMeshError, match="Surface dimensions must be positive"
        ):
            calibration_to_warp_mesh(cal, 0.5, -1)

    def test_invalid_resolution(self) -> None:
        K = np.array([[0, 0, 640], [0, 1280, 360], [0, 0, 1]], float)
        pose = np.eye(4)
        cal = CalibrationResult(
            calibration_id="cal-1",
            sequence_id="seq-1",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="p0",
            camera_id="c0",
            surface_id="s0",
            projector_intrinsics=K,
            projector_pose=pose,
            projector_resolution=(1280, 720),
            reprojection_error=0.5,
            coverage=0.8,
            num_correspondences=8000,
            confidence=0.9,
            calibration_sequence_ids=("seq-1", "seq-2"),
            object_pose=Pose(position=Vec3(0, 0, 2.0)),
        )
        with pytest.raises((CalibrationToWarpMeshError, ValueError)):
            calibration_to_warp_mesh(cal, 0.5, 0.3)

    def test_singular_pose(self) -> None:
        K = np.array([[1280, 0, 640], [0, 1280, 360], [0, 0, 1]], float)
        pose = np.zeros((4, 4))
        cal = CalibrationResult(
            calibration_id="cal-1",
            sequence_id="seq-1",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="p0",
            camera_id="c0",
            surface_id="s0",
            projector_intrinsics=K,
            projector_pose=pose,
            projector_resolution=(1280, 720),
            reprojection_error=0.5,
            coverage=0.8,
            num_correspondences=8000,
            confidence=0.9,
            calibration_sequence_ids=("seq-1", "seq-2"),
            object_pose=Pose(position=Vec3(0, 0, 2.0)),
        )
        with pytest.raises(CalibrationToWarpMeshError, match="Projector pose invalid"):
            calibration_to_warp_mesh(cal, 0.5, 0.3)

    def test_surface_id_mismatch(self) -> None:
        cal = _cal()
        with pytest.raises(CalibrationToWarpMeshError, match="Surface ID mismatch"):
            calibration_to_warp_mesh(cal, 0.5, 0.3, surface_id="other-surface")

    def test_uv_outside_bounds_fails(self) -> None:
        pose = np.eye(4)
        K = np.array([[2000, 0, 640], [0, 2000, 360], [0, 0, 1]], float)
        cal = CalibrationResult(
            calibration_id="cal-1",
            sequence_id="seq-1",
            method=CalibrationMethod.GRAY_CODE,
            projector_id="p0",
            camera_id="c0",
            surface_id="s0",
            projector_intrinsics=K,
            projector_pose=pose,
            projector_resolution=(1280, 720),
            reprojection_error=0.5,
            coverage=0.8,
            num_correspondences=8000,
            confidence=0.9,
            calibration_sequence_ids=("seq-1", "seq-2"),
            object_pose=Pose(position=Vec3(10, 0, 2.0)),
        )
        with pytest.raises(
            CalibrationToWarpMeshError, match="Generated warp mesh invalid"
        ):
            calibration_to_warp_mesh(cal, 1.0, 1.0, grid_rows=4, grid_cols=4)


# ---------------------------------------------------------------------------
# Mesh topology
# ---------------------------------------------------------------------------


class TestMeshTopology:
    def test_grid_topology(self) -> None:
        cal = _cal()
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=4, grid_cols=4)
        assert mesh.grid_rows == 4
        assert mesh.grid_cols == 4
        assert mesh.num_vertices == 25
        assert mesh.num_faces == 32
        assert mesh.indices.shape == (32, 3)
        assert mesh.indices.min() >= 0
        assert mesh.indices.max() < mesh.num_vertices
        assert mesh.validate() == []

    def test_non_degenerate_triangles(self) -> None:
        cal = _cal()
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=8, grid_cols=8)
        # Check no zero-area triangles in projector UV space
        for tri in mesh.indices:
            a, b, c = (
                mesh.projector_uvs[tri[0]],
                mesh.projector_uvs[tri[1]],
                mesh.projector_uvs[tri[2]],
            )
            area = (
                abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) * 0.5
            )
            assert area > 1e-9

    def test_content_uv_convention(self) -> None:
        cal = _cal()
        mesh = calibration_to_warp_mesh(cal, 1.0, 1.0, grid_rows=1, grid_cols=1)
        # Content UVs: bottom-left origin, V up
        assert mesh.content_uvs.min() >= -1e-9
        assert mesh.content_uvs.max() <= 1 + 1e-9
        assert set(map(tuple, np.round(mesh.content_uvs, 6).tolist())) == {
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
        }


# ---------------------------------------------------------------------------
# ProjectionMapping & persistence
# ---------------------------------------------------------------------------


class TestProjectionMapping:
    def test_create_mapping(self) -> None:
        cal = _cal()
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=4, grid_cols=4)
        mapping = create_projection_mapping(cal, mesh, "asset-123")
        assert mapping.projector_id == "p0"
        assert mapping.surface_id == "s0"
        assert mapping.calibration_id == "cal-1"
        assert mapping.warp_mesh_asset_id == "asset-123"
        assert mapping.metadata["calibration_sequence_ids"] == ["seq-1", "seq-2"]

    def test_mapping_id_mismatch(self) -> None:
        cal = _cal()
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=4, grid_cols=4)
        with pytest.raises(ValueError, match="Surface ID mismatch"):
            create_projection_mapping(cal, mesh, "asset-123", surface_id="other")

    def test_persistence(self) -> None:
        cal = _cal()
        d = cal.to_dict()
        cal2 = CalibrationResult.from_dict(d)
        assert cal == cal2
        # Old project without calibration_sequence_ids should load
        d_old = {k: v for k, v in d.items() if k != "calibration_sequence_ids"}
        cal_old = CalibrationResult.from_dict(d_old)
        assert cal_old.calibration_sequence_ids == ()
        # WarpMesh
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3)
        md = mesh.to_dict()
        mesh2 = WarpMesh.from_dict(md)
        assert mesh == mesh2
        # ProjectionMapping
        mapping = create_projection_mapping(cal, mesh, "asset-123")
        md2 = mapping.to_dict()
        mapping2 = ProjectionMapping.from_dict(md2)
        assert mapping == mapping2


# ---------------------------------------------------------------------------
# Homography cross-check
# ---------------------------------------------------------------------------


class TestHomographyCrossCheck:
    def test_dense_vs_homography(self) -> None:
        cal = _cal(obj_z=2.0)
        mesh = calibration_to_warp_mesh(cal, 0.5, 0.3, grid_rows=8, grid_cols=8)
        # Build PlanarHomography from same calibration
        K = cal.projector_intrinsics
        intr = ProjectorIntrinsics(
            fx=float(K[0, 0]),
            fy=float(K[1, 1]),
            cx=float(K[0, 2]),
            cy=float(K[1, 2]),
            resolution_x=1280,
            resolution_y=720,
        )
        # Use TRANSFORMS homography: need surface→world etc.
        # Simplify: use mesh's projector UVs as ground truth, compare homography prediction
        # For planar surface, homography should match dense per-vertex projection within tolerance
        from projectionai.domain.transforms import Transform

        # Build transforms from calibration
        surf_to_world = (
            Transform.from_numpy(cal.object_pose.as_matrix())
            if cal.object_pose
            else Transform()
        )
        world_to_proj = Transform.from_numpy(np.linalg.inv(cal.projector_pose))
        # Create surface_local→projector chain via homography
        # For planar Z=0, homography is K @ M' where M' is 3x3 from 4x4 chain
        chain = Transform(matrix=surf_to_world.matrix).compose(
            Transform(matrix=world_to_proj.matrix)
        )
        m = chain.to_numpy()
        k_mat = intr.camera_matrix()
        m_prime = m[:3, [0, 1, 3]]
        h_mat = k_mat @ m_prime
        hom = PlanarHomography(matrix=h_mat)
        # Compare for each vertex
        for i, v in enumerate(mesh.vertices):
            pt = Vec3(float(v[0]), float(v[1]), float(v[2]))
            u1, v1 = hom.apply_local_point(pt)
            # hom gives pixel, convert to UV
            uv_h = (u1 / 1280, v1 / 720)
            uv_m = tuple(mesh.projector_uvs[i])
            assert abs(uv_h[0] - uv_m[0]) < 1e-6
            assert abs(uv_h[1] - uv_m[1]) < 1e-6
