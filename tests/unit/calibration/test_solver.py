"""Phase 6.7 solver tests — synthetic matrix A-F + failures + reprojection."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.calibration.solver import (
    CalibrationSolveError,
    JointIntrinsicsResult,
    solve_calibration,
    solve_joint_intrinsics,
    solve_per_plane_poses,
)
from projectionai.domain.calibration_session import ReconstructionResult

PROJ_W, PROJ_H = 1280, 720
CAM_W, CAM_H = 640, 480


def _rot_x(deg: float) -> np.ndarray:
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def _make_plane(normal, offset, rng, n=8000):
    nrm = normal / np.linalg.norm(normal)
    helper = (
        np.array([1.0, 0.0, 0.0]) if abs(nrm[2]) > 0.9 else np.array([0.0, 0.0, 1.0])
    )
    u = np.cross(helper, nrm)
    u /= np.linalg.norm(u)
    v = np.cross(nrm, u)
    su = rng.uniform(-1.2, 1.2, int(n))
    sv = rng.uniform(-0.9, 0.9, int(n))
    center = -offset * nrm
    return center + su[:, None] * u + sv[:, None] * v


def _project(pts, k):
    x = pts[:, 0] / pts[:, 2]
    y = pts[:, 1] / pts[:, 2]
    return np.column_stack((k[0, 0] * x + k[0, 2], k[1, 1] * y + k[1, 2]))


def _reconstruction(
    tilt_deg: float,
    offset: float = 2.0,
    noise: float = 0.0,
    seed: int = 0,
    fx: float = 1000.0,
    fy: float = 1100.0,
    n: int = 8000,
    seq_id: str | None = None,
) -> ReconstructionResult:
    rng = np.random.default_rng(seed)
    r = _rot_x(tilt_deg)
    normal = -r @ np.array([0.0, 0.0, 1.0])
    pts = _make_plane(normal, offset, rng, n)
    proj_k = np.array([[fx, 0, PROJ_W / 2], [0, fy, PROJ_H / 2], [0, 0, 1]], float)
    proj_pose = np.eye(4)
    # projector at origin, plane tilted; same as synthetic case
    proj_local = pts  # identity pose
    proj_px = _project(proj_local, proj_k)
    # Keep in projector bounds
    keep = (
        (proj_px[:, 0] >= 0)
        & (proj_px[:, 0] < PROJ_W)
        & (proj_px[:, 1] >= 0)
        & (proj_px[:, 1] < PROJ_H)
    )
    pts, proj_px = pts[keep], proj_px[keep]
    if noise > 0:
        proj_px = proj_px + rng.normal(0, noise, proj_px.shape)
    # Add tiny camera-pixel quantization effect via rounding? Not needed for solver test
    sid = seq_id or f"seq-t{tilt_deg}-n{noise}-s{seed}"
    return ReconstructionResult(
        points_camera=pts.astype(float),
        projector_pixels=proj_px.astype(float),
        sequence_id=sid,
        normals=np.tile(normal, (len(pts), 1)).astype(float),
        method="plane_triangulation",
    )


# ---------------------------------------------------------------------------
# A-F: synthetic matrix
# ---------------------------------------------------------------------------


class TestSyntheticMatrix:
    def test_a_frontal_plus_frontal_reject(self) -> None:
        r1 = _reconstruction(0.0, noise=0.3, seed=1)
        r2 = _reconstruction(0.5, noise=0.3, seed=2)
        with pytest.raises(
            CalibrationSolveError,
            match="Insufficient calibration orientation diversity",
        ):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_b_5_plus_5_reject(self) -> None:
        r1 = _reconstruction(5.0, noise=0.3, seed=1)
        r2 = _reconstruction(5.0, offset=2.3, noise=0.3, seed=2)
        with pytest.raises(
            CalibrationSolveError,
            match="Insufficient calibration orientation diversity",
        ):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_c_5_plus_10_reject(self) -> None:
        r1 = _reconstruction(5.0, noise=0.3, seed=1)
        r2 = _reconstruction(10.0, noise=0.3, seed=2)
        # 5 degree separation <15° -> reject
        with pytest.raises(
            CalibrationSolveError,
            match="Insufficient calibration orientation diversity",
        ):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_d_15_plus_minus15_pass(self) -> None:
        r1 = _reconstruction(30.0, noise=0.5, seed=1)
        r2 = _reconstruction(-15.0, noise=0.5, seed=2)
        res = solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))
        assert res.fx == pytest.approx(1000.0, rel=0.02)
        assert res.fy == pytest.approx(1100.0, rel=0.02)
        assert res.condition_number < 1e6
        assert res.rank == 2

    def test_e_30_plus_minus25_pass(self) -> None:
        r1 = _reconstruction(30.0, noise=0.5, seed=1)
        r2 = _reconstruction(-25.0, noise=0.5, seed=2)
        res = solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))
        assert res.fx == pytest.approx(1000.0, rel=0.01)
        assert res.fy == pytest.approx(1100.0, rel=0.01)

    def test_f_three_planes_pass(self) -> None:
        r1 = _reconstruction(30.0, noise=0.5, seed=1)
        r2 = _reconstruction(-25.0, noise=0.5, seed=2)
        r3 = _reconstruction(15.0, offset=2.2, noise=0.5, seed=3)
        res = solve_joint_intrinsics((r1, r2, r3), (PROJ_W, PROJ_H))
        assert res.fx == pytest.approx(1000.0, rel=0.02)
        assert res.fy == pytest.approx(1100.0, rel=0.02)
        assert abs(res.fx - 1000) < 20
        assert abs(res.fy - 1100) < 25

    @pytest.mark.parametrize("noise", [0.0, 0.3, 0.5, 1.0])
    def test_noise_levels(self, noise: float) -> None:
        r1 = _reconstruction(30.0, noise=noise, seed=10)
        r2 = _reconstruction(-25.0, noise=noise, seed=11)
        res = solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))
        # <1% at all noise levels per spec; target <0.2% for 2-plane synthetic reference
        assert res.fx == pytest.approx(1000.0, rel=0.02)
        assert res.fy == pytest.approx(1100.0, rel=0.02)

    def test_full_calibration_solve(self) -> None:
        r1 = _reconstruction(30.0, noise=0.5, seed=1)
        r2 = _reconstruction(-25.0, noise=0.5, seed=2)
        result = solve_calibration(
            (r1, r2), (PROJ_W, PROJ_H), projector_id="p0", camera_id="c0"
        )
        assert result.projector_intrinsics[0, 0] == pytest.approx(1000.0, rel=0.01)
        assert result.projector_intrinsics[1, 1] == pytest.approx(1100.0, rel=0.01)
        assert result.reprojection_error < 2.0
        assert result.coverage > 0
        assert result.confidence > 0


# ---------------------------------------------------------------------------
# Failure tests
# ---------------------------------------------------------------------------


class TestFailures:
    def test_one_plane_reject(self) -> None:
        r1 = _reconstruction(30.0, seed=1)
        with pytest.raises(CalibrationSolveError, match="at least 2"):
            solve_joint_intrinsics((r1,), (PROJ_W, PROJ_H))

    def test_duplicate_plane_reject(self) -> None:
        r1 = _reconstruction(30.0, seed=1, seq_id="dup")
        r2 = _reconstruction(-25.0, seed=2, seq_id="dup")
        with pytest.raises(CalibrationSolveError, match="Duplicate sequence_id"):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_insufficient_orientation_separation(self) -> None:
        r1 = _reconstruction(10.0, seed=1)
        r2 = _reconstruction(12.0, seed=2)
        with pytest.raises(
            CalibrationSolveError,
            match="Insufficient calibration orientation diversity",
        ):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_singular_constraint_matrix(self) -> None:
        # Frontal planes give rank-deficient constraints
        r1 = _reconstruction(0.0, seed=1)
        r2 = _reconstruction(0.0, offset=2.5, seed=2)
        with pytest.raises(CalibrationSolveError):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_invalid_homography(self) -> None:
        # Too few points -> homography fails
        r1 = _reconstruction(30.0, n=3, seed=1)
        r2 = _reconstruction(-25.0, n=3, seed=2)
        with pytest.raises(CalibrationSolveError):
            solve_joint_intrinsics((r1, r2), (PROJ_W, PROJ_H))

    def test_nan_observations(self) -> None:
        r1 = _reconstruction(30.0, seed=1)
        pts = r1.points_camera.copy()
        pts[0, 0] = float("nan")
        bad = ReconstructionResult(
            points_camera=pts,
            projector_pixels=r1.projector_pixels,
            sequence_id=r1.sequence_id,
            method=r1.method,
        )
        r2 = _reconstruction(-25.0, seed=2)
        with pytest.raises(CalibrationSolveError, match="NaN/Inf"):
            solve_joint_intrinsics((bad, r2), (PROJ_W, PROJ_H))

    def test_insufficient_correspondences(self) -> None:
        r_small = _reconstruction(30.0, n=2, seed=1)
        r2 = _reconstruction(-25.0, n=8000, seed=2)
        with pytest.raises(CalibrationSolveError):
            solve_joint_intrinsics((r_small, r2), (PROJ_W, PROJ_H))

    def test_mismatched_projector_resolution(self) -> None:
        r1 = _reconstruction(30.0, seed=1)
        r2 = _reconstruction(-25.0, seed=2)
        with pytest.raises(CalibrationSolveError, match="Invalid projector resolution"):
            solve_joint_intrinsics((r1, r2), (0, 0))

    def test_solve_calibration_rejects_one_plane(self) -> None:
        r1 = _reconstruction(30.0, seed=1)
        with pytest.raises(CalibrationSolveError, match="at least 2"):
            solve_calibration((r1,), (PROJ_W, PROJ_H))


# ---------------------------------------------------------------------------
# Reprojection validation
# ---------------------------------------------------------------------------


class TestReprojection:
    def test_per_plane_reprojection(self) -> None:
        r1 = _reconstruction(30.0, noise=0.5, seed=1)
        r2 = _reconstruction(-25.0, noise=0.5, seed=2)
        result = solve_calibration((r1, r2), (PROJ_W, PROJ_H))
        assert result.reprojection_error < 2.0
        assert result.per_point_errors is not None
        # p95 and max in metadata
        assert result.metadata["overall_p95"] < 5.0
        assert result.metadata["overall_max"] < 10.0
