"""Calibration solver — joint Zhang intrinsics + per-plane solvePnP."""

# ruff: noqa: N806, F401, RUF059, ARG001, N817, RUF100

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.core.errors import ProjectionAIError
from projectionai.domain.calibration_session import (
    CalibrationMethod,
    CalibrationResult,
    ReconstructionResult,
)
from projectionai.domain.geometry import Pose, Vec3
from projectionai.infrastructure.projector_calibration.estimators import (
    ProjectorExtrinsicsEstimator,
    plane_basis,
    project_points,
)
from projectionai.services.projector_calibration import ProjectorCalibrationError


class CalibrationSolveError(ProjectionAIError):
    """Typed failure for the calibration solve stage."""


@dataclass(frozen=True)
class JointIntrinsicsResult:
    intrinsics: NDArray[np.float64]  # 3x3
    fx: float
    fy: float
    cx: float
    cy: float
    condition_number: float
    rank: int
    num_planes: int
    residuals: tuple[float, ...]  # per-row residuals of A x - b


@dataclass(frozen=True)
class PerPlanePose:
    sequence_id: str
    pose: NDArray[np.float64]  # 4x4 projector→camera
    reprojection_rms: float
    reprojection_median: float
    reprojection_p95: float
    reprojection_max: float
    num_points: int


_MIN_PLANES = 2
_MIN_TILT_DEG = 15.0
_MAX_COND = 1e6
_CONSISTENCY_TOL = 0.05  # 5% relative tolerance for per-plane intrinsics vs joint


def _homography_for_plane(
    plane_points: NDArray[np.float64],
    projector_pixels: NDArray[np.float64],
    cx: float,
    cy: float,
) -> NDArray[np.float64] | None:
    centroid, u_axis, v_axis = plane_basis(plane_points)
    centered_3d = plane_points - centroid
    plane_2d = np.column_stack((centered_3d @ u_axis, centered_3d @ v_axis))
    centered_pixels = projector_pixels - np.array([cx, cy])
    result = cv2.findHomography(plane_2d, centered_pixels, 0)
    if result is None:
        return None
    h, _ = result
    if h is None:
        return None
    return np.asarray(h, dtype=np.float64)


def _zhang_rows(
    h: NDArray[np.float64],
) -> tuple[list[float], list[float], float, float]:
    h1, h2 = h[:, 0], h[:, 1]
    row1 = [float(h1[0] * h2[0]), float(h1[1] * h2[1])]
    rhs1 = float(-h1[2] * h2[2])
    row2 = [float(h1[0] ** 2 - h2[0] ** 2), float(h1[1] ** 2 - h2[1] ** 2)]
    rhs2 = float(-(h1[2] ** 2 - h2[2] ** 2))
    return row1, row2, rhs1, rhs2


def solve_joint_intrinsics(
    reconstructions: tuple[ReconstructionResult, ...] | list[ReconstructionResult],
    projector_resolution: tuple[int, int],
) -> JointIntrinsicsResult:
    if len(reconstructions) < _MIN_PLANES:
        raise CalibrationSolveError(
            f"Insufficient calibration orientation diversity: need at least {_MIN_PLANES} plane orientations, got {len(reconstructions)}"
        )
    # Duplicate sequence check
    seq_ids = [r.sequence_id for r in reconstructions]
    if len(set(seq_ids)) != len(seq_ids):
        raise CalibrationSolveError(
            f"Duplicate sequence_id in reconstructions: {seq_ids}"
        )
    # Resolution consistency checked by caller; also validate per-reconstruction
    w, h = projector_resolution
    if w <= 0 or h <= 0:
        raise CalibrationSolveError(
            f"Invalid projector resolution {projector_resolution}"
        )
    cx, cy = w / 2.0, h / 2.0

    # Collect per-plane normals for diversity check
    normals: list[Any] = []
    homographies: list[Any] = []
    for rec in reconstructions:
        if len(rec.points_camera) < 4:
            raise CalibrationSolveError(
                f"Reconstruction {rec.sequence_id} has too few points: {len(rec.points_camera)}"
            )
        if not np.all(np.isfinite(rec.points_camera)):
            raise CalibrationSolveError(
                f"Reconstruction {rec.sequence_id} contains NaN/Inf"
            )
        if not np.all(np.isfinite(rec.projector_pixels)):
            raise CalibrationSolveError(
                f"Reconstruction {rec.sequence_id} projector_pixels contains NaN/Inf"
            )
        hom = _homography_for_plane(rec.points_camera, rec.projector_pixels, cx, cy)
        if hom is None:
            raise CalibrationSolveError(
                f"Homography estimation failed for {rec.sequence_id}"
            )
        homographies.append(hom)
        # derive normal from plane_basis
        centroid = rec.points_camera.mean(axis=0)
        _, _, vh = np.linalg.svd(rec.points_camera - centroid, full_matrices=False)
        normals.append(vh[2])

    # Orientation diversity guard (pairwise angle >= MIN_TILT_DEG)
    max_angle = 0.0
    for i in range(len(normals)):
        for j in range(i + 1, len(normals)):
            dot = float(np.clip(np.dot(normals[i], normals[j]), -1.0, 1.0))
            ang = float(np.degrees(np.arccos(abs(dot))))
            # angle between plane normals; for parallel planes ang ~0
            # we want diverse tilts: at least one pair with ang >= MIN_TILT
            if ang > max_angle:
                max_angle = ang
    if max_angle < _MIN_TILT_DEG - 1e-6:
        raise CalibrationSolveError(
            f"Insufficient calibration orientation diversity: max relative tilt {max_angle:.1f}° < {_MIN_TILT_DEG:.0f}° (need at least {_MIN_TILT_DEG:.0f}° between two planes)"
        )

    # Stack Zhang constraints
    a_rows: list[list[float]] = []
    b_rows: list[float] = []
    for hom in homographies:
        r1, r2, b1, b2 = _zhang_rows(hom)
        a_rows.append(r1)
        b_rows.append(b1)
        a_rows.append(r2)
        b_rows.append(b2)
    A = np.array(a_rows, dtype=np.float64)
    b = np.array(b_rows, dtype=np.float64)

    # Rank and condition check
    if A.shape[0] < 2 or A.shape[1] != 2:
        raise CalibrationSolveError("Joint constraint matrix has insufficient rows")
    rank = int(np.linalg.matrix_rank(A))
    if rank < 2:
        raise CalibrationSolveError(
            f"Joint constraint matrix is rank-deficient (rank {rank} < 2)"
        )
    # condition number via SVD of A
    try:
        s = np.linalg.svd(A, compute_uv=False)
        cond = float(s[0] / s[-1]) if s[-1] > 0 else float("inf")
    except Exception:
        cond = float("inf")
    if cond > _MAX_COND:
        raise CalibrationSolveError(
            f"Joint constraint matrix is ill-conditioned (cond {cond:.2e} > {_MAX_COND:.0e}); orientations may be too similar or degenerate"
        )

    sol, residuals_arr, _, _ = np.linalg.lstsq(A, b, rcond=None)
    inv_fx2, inv_fy2 = float(sol[0]), float(sol[1])
    if (
        inv_fx2 <= 0
        or inv_fy2 <= 0
        or not np.isfinite(inv_fx2)
        or not np.isfinite(inv_fy2)
    ):
        raise CalibrationSolveError(
            f"Non-positive focal length estimate: inv_fx2={inv_fx2:.3e} inv_fy2={inv_fy2:.3e} — degenerate geometry"
        )
    fx = float(np.sqrt(1.0 / inv_fx2))
    fy = float(np.sqrt(1.0 / inv_fy2))
    if not np.isfinite(fx) or not np.isfinite(fy) or fx <= 0 or fy <= 0:
        raise CalibrationSolveError(f"Invalid focal length: fx={fx} fy={fy}")

    K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)

    # Per-row residuals for diagnostics
    pred = A @ sol
    resid = tuple(float(abs(pred[i] - b[i])) for i in range(len(b)))

    return JointIntrinsicsResult(
        intrinsics=K,
        fx=fx,
        fy=fy,
        cx=cx,
        cy=cy,
        condition_number=cond,
        rank=rank,
        num_planes=len(reconstructions),
        residuals=resid,
    )


def solve_per_plane_poses(
    reconstructions: tuple[ReconstructionResult, ...] | list[ReconstructionResult],
    intrinsics: NDArray[np.float64],
) -> list[PerPlanePose]:
    estimator = ProjectorExtrinsicsEstimator()
    results: list[PerPlanePose] = []
    for rec in reconstructions:
        try:
            pose = estimator.estimate(
                rec.points_camera, rec.projector_pixels, intrinsics
            )
        except ProjectorCalibrationError as exc:
            raise CalibrationSolveError(
                f"solvePnP failed for {rec.sequence_id}: {exc}"
            ) from exc
        # Validate pose
        if not np.all(np.isfinite(pose)):
            raise CalibrationSolveError(f"Non-finite pose for {rec.sequence_id}")
        if pose.shape != (4, 4):
            raise CalibrationSolveError(
                f"Invalid pose shape for {rec.sequence_id}: {pose.shape}"
            )
        # Reprojection per plane
        pred = project_points(rec.points_camera, intrinsics, pose)
        if not np.all(np.isfinite(pred)):
            raise CalibrationSolveError(f"Non-finite projection for {rec.sequence_id}")
        err = np.linalg.norm(pred - rec.projector_pixels, axis=1)
        rms = float(np.sqrt(np.mean(err**2)))
        median = float(np.median(err))
        p95 = float(np.percentile(err, 95))
        mx = float(np.max(err))
        results.append(
            PerPlanePose(
                sequence_id=rec.sequence_id,
                pose=pose,
                reprojection_rms=rms,
                reprojection_median=median,
                reprojection_p95=p95,
                reprojection_max=mx,
                num_points=len(rec.points_camera),
            )
        )
    return results


def validate_cross_plane_consistency(
    per_plane: list[PerPlanePose],
) -> None:
    # Check that no single plane has wildly different RMS
    if not per_plane:
        return
    rms_vals = [p.reprojection_rms for p in per_plane]
    median_rms = float(np.median(rms_vals))
    for p in per_plane:
        if p.reprojection_rms > max(5.0, median_rms * 3.0):
            raise CalibrationSolveError(
                f"Plane {p.sequence_id} RMS {p.reprojection_rms:.2f}px is inconsistent (median {median_rms:.2f}px)"
            )
        if p.reprojection_max > 20.0:
            raise CalibrationSolveError(
                f"Plane {p.sequence_id} max error {p.reprojection_max:.2f}px too large"
            )


def _pose_to_vec3_quat(
    pose: NDArray[np.float64],
) -> tuple[Vec3, tuple[float, float, float, float]]:
    try:
        from scipy.spatial.transform import Rotation as R
    except ImportError:
        # SciPy not available — fallback to identity rotation
        pos = Vec3(float(pose[0, 3]), float(pose[1, 3]), float(pose[2, 3]))
        return pos, (1.0, 0.0, 0.0, 0.0)
    try:
        rot = R.from_matrix(pose[:3, :3]).as_quat()
    except Exception as exc:
        raise CalibrationSolveError(f"Invalid rotation matrix: {exc}") from exc
    w, x, y, z = float(rot[3]), float(rot[0]), float(rot[1]), float(rot[2])
    q: tuple[float, float, float, float] = (w, x, y, z)
    pos = Vec3(float(pose[0, 3]), float(pose[1, 3]), float(pose[2, 3]))
    return pos, q


def solve_calibration(
    reconstructions: tuple[ReconstructionResult, ...] | list[ReconstructionResult],
    projector_resolution: tuple[int, int],
    projector_id: str = "projector_0",
    camera_id: str = "camera_0",
    surface_id: str = "",
    calibration_id: str | None = None,
    method: CalibrationMethod = CalibrationMethod.GRAY_CODE,
    camera_matrix: NDArray[np.float64] | None = None,
    distortion_coeffs: NDArray[np.float64] | None = None,
    image_size: tuple[int, int] | None = None,
    metadata_extra: dict[str, Any] | None = None,
) -> CalibrationResult:
    if not reconstructions:
        raise CalibrationSolveError("No reconstructions provided")
    # Canonicalize to tuple
    recs = tuple(reconstructions)
    joint = solve_joint_intrinsics(recs, projector_resolution)
    per_plane = solve_per_plane_poses(recs, joint.intrinsics)
    validate_cross_plane_consistency(per_plane)

    # Aggregate reprojection
    all_rms = [p.reprojection_rms for p in per_plane]
    all_max = [p.reprojection_max for p in per_plane]
    overall_rms = float(np.mean(all_rms))
    overall_max = float(max(all_max)) if all_max else 0.0
    overall_median = float(np.median([p.reprojection_median for p in per_plane]))
    p95_vals = [p.reprojection_p95 for p in per_plane]
    overall_p95 = float(np.mean(p95_vals)) if p95_vals else 0.0
    total_points = sum(p.num_points for p in per_plane)
    w, h = projector_resolution
    # Real projector-space coverage: unique integer projector pixels / area
    try:
        all_pixels = np.vstack([r.projector_pixels for r in recs])
        finite = np.all(np.isfinite(all_pixels), axis=1)
        xs = np.floor(all_pixels[finite, 0]).astype(int)
        ys = np.floor(all_pixels[finite, 1]).astype(int)
        in_bounds = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        if np.any(in_bounds):
            uniq = np.unique(np.column_stack((xs[in_bounds], ys[in_bounds])), axis=0)
            coverage = float(len(uniq) / float(w * h)) if w * h > 0 else 0.0
        else:
            coverage = 0.0
    except Exception:
        # fallback to point-count proxy
        coverage = (
            float(min(1.0, total_points / float(w * h) * 10.0)) if w * h > 0 else 0.0
        )
    coverage = float(np.clip(coverage, 0.0, 1.0))
    legacy_proxy = (
        float(min(1.0, total_points / float(w * h) * 10.0)) if w * h > 0 else 0.0
    )
    # Confidence derived from RMS and coverage
    # Similar to GrayCodeProjectorCalibration._confidence
    max_rms = 2.0
    error_term = max(0.0, 1.0 - overall_rms / (2.0 * max_rms))
    confidence = float(max(0.0, min(1.0, error_term * min(1.0, coverage * 2.0))))

    # Choose best pose (lowest RMS) as canonical projector_pose
    best = min(per_plane, key=lambda p: p.reprojection_rms)
    pose = best.pose

    # Per-point errors: collect from best plane for now; more accurate would be all planes
    # Use reprojection errors from best plane's residuals
    # Compute per-point errors for best plane
    best_rec = next(r for r in recs if r.sequence_id == best.sequence_id)
    pred_best = project_points(best_rec.points_camera, joint.intrinsics, pose)
    per_err = tuple(
        float(v) for v in np.linalg.norm(pred_best - best_rec.projector_pixels, axis=1)
    )

    pos, quat = _pose_to_vec3_quat(pose)
    obj_pose = Pose(position=pos, rotation=quat)

    cal_id = calibration_id or uuid.uuid4().hex
    seq_id = recs[0].sequence_id
    seq_ids = tuple(r.sequence_id for r in recs)
    return CalibrationResult(
        calibration_id=cal_id,
        sequence_id=seq_id,
        method=method,
        projector_id=projector_id,
        camera_id=camera_id,
        surface_id=surface_id,
        projector_intrinsics=joint.intrinsics,
        projector_pose=pose,
        projector_resolution=projector_resolution,
        reprojection_error=overall_rms,
        coverage=coverage,
        num_correspondences=total_points,
        confidence=confidence,
        calibration_sequence_ids=seq_ids,
        per_point_errors=per_err,
        camera_matrix=camera_matrix,
        distortion_coeffs=distortion_coeffs,
        image_size=image_size,
        object_pose=obj_pose,
        metadata={
            "joint_fx": joint.fx,
            "joint_fy": joint.fy,
            "joint_condition": joint.condition_number,
            "joint_rank": joint.rank,
            "num_planes": joint.num_planes,
            "per_plane_rms": {p.sequence_id: p.reprojection_rms for p in per_plane},
            "per_plane_p95": {p.sequence_id: p.reprojection_p95 for p in per_plane},
            "per_plane_max": {p.sequence_id: p.reprojection_max for p in per_plane},
            "overall_median": overall_median,
            "overall_p95": overall_p95,
            "overall_max": overall_max,
            "best_plane": best.sequence_id,
            "legacy_coverage_proxy": legacy_proxy,
            **(metadata_extra or {}),
        },
    )


def refine_calibration(
    reconstructions: tuple[ReconstructionResult, ...] | list[ReconstructionResult],
    initial: CalibrationResult,
    rms_threshold: float = 2.0,
) -> tuple[CalibrationResult, bool, float, float]:
    """Optional SciPy refinement hook. Returns (result, was_refined, rms_before, rms_after).

    Disabled unless explicitly called. Never replaces a failed base solve.
    """
    rms_before = initial.reprojection_error
    if rms_before <= rms_threshold:
        return initial, False, rms_before, rms_before
    try:
        from scipy.optimize import least_squares
    except ImportError:
        return initial, False, rms_before, rms_before

    # Joint refinement over fx, fy (cx,cy fixed) + per-plane pose
    # For MVP we refine only the best plane's pose + intrinsics jointly
    recs = tuple(reconstructions)
    # Find best plane
    best_seq = initial.metadata.get("best_plane", recs[0].sequence_id)
    best_rec = next((r for r in recs if r.sequence_id == best_seq), recs[0])
    pts = best_rec.points_camera
    obs = best_rec.projector_pixels

    fx0, fy0 = (
        float(initial.projector_intrinsics[0, 0]),
        float(initial.projector_intrinsics[1, 1]),
    )
    cx, cy = (
        float(initial.projector_intrinsics[0, 2]),
        float(initial.projector_intrinsics[1, 2]),
    )
    # Decompose pose to rvec/tvec
    pose0 = initial.projector_pose
    try:
        inv = np.linalg.inv(pose0)
    except np.linalg.LinAlgError:
        return initial, False, rms_before, rms_before
    rvec0, _ = cv2.Rodrigues(inv[:3, :3])
    tvec0 = inv[:3, 3]

    def resid(p: NDArray[np.float64]) -> NDArray[np.float64]:
        fx, fy = float(p[0]), float(p[1])
        rv = p[2:5]
        tv = p[5:8]
        R, _ = cv2.Rodrigues(rv)
        # Camera → projector local: R, t
        hom = pts @ R.T + tv
        # guard divide by zero
        mask = hom[:, 2] > 1e-9
        if not np.any(mask):
            return np.full(2 * len(obs), 1e6)
        u = np.full(len(obs), 1e6)
        v = np.full(len(obs), 1e6)
        u[mask] = fx * hom[mask, 0] / hom[mask, 2] + cx - obs[mask, 0]
        v[mask] = fy * hom[mask, 1] / hom[mask, 2] + cy - obs[mask, 1]
        return np.concatenate([u, v])

    p0 = np.array(
        [
            fx0,
            fy0,
            float(rvec0[0, 0]),
            float(rvec0[1, 0]),
            float(rvec0[2, 0]),
            float(tvec0[0]),
            float(tvec0[1]),
            float(tvec0[2]),
        ],
        dtype=np.float64,
    )
    try:
        sol = least_squares(resid, p0, method="lm", max_nfev=200)
    except Exception:
        return initial, False, rms_before, rms_before
    n_pts = len(obs)
    # sol.fun is [u_0..u_{n-1}, v_0..v_{n-1}]; Euclidean per-point error is sqrt(u_i^2 + v_i^2)
    if len(sol.fun) == 2 * n_pts:
        e2 = sol.fun[:n_pts] ** 2 + sol.fun[n_pts:] ** 2
        rms_after = float(np.sqrt(np.mean(e2))) if e2.size else float("inf")
    else:
        # Fallback for unexpected fun length (should not happen)
        rms_after = float(np.sqrt(np.mean(sol.fun**2)) * np.sqrt(2.0))
    if rms_after >= rms_before - 1e-9:
        return initial, False, rms_before, rms_after
    fx1, fy1 = float(sol.x[0]), float(sol.x[1])
    if fx1 <= 0 or fy1 <= 0 or not np.isfinite(fx1) or not np.isfinite(fy1):
        return initial, False, rms_before, rms_after
    K1 = np.array([[fx1, 0, cx], [0, fy1, cy], [0, 0, 1]], dtype=np.float64)
    rv1 = sol.x[2:5].reshape(3, 1)
    tv1 = sol.x[5:8]
    R1, _ = cv2.Rodrigues(rv1)
    cam_to_proj = np.eye(4)
    cam_to_proj[:3, :3] = R1
    cam_to_proj[:3, 3] = tv1
    pose1 = np.linalg.inv(cam_to_proj)
    # Build refined CalibrationResult
    refined = CalibrationResult(
        calibration_id=initial.calibration_id,
        sequence_id=initial.sequence_id,
        method=initial.method,
        projector_id=initial.projector_id,
        camera_id=initial.camera_id,
        surface_id=initial.surface_id,
        projector_intrinsics=K1,
        projector_pose=pose1,
        projector_resolution=initial.projector_resolution,
        reprojection_error=rms_after,
        coverage=initial.coverage,
        num_correspondences=initial.num_correspondences,
        confidence=initial.confidence,
        calibration_sequence_ids=initial.calibration_sequence_ids,
        per_point_errors=initial.per_point_errors,
        camera_matrix=initial.camera_matrix,
        distortion_coeffs=initial.distortion_coeffs,
        image_size=initial.image_size,
        warp_mesh=initial.warp_mesh,
        object_pose=initial.object_pose,
        created_at=initial.created_at,
        metadata={
            **initial.metadata,
            "refined": True,
            "rms_before": rms_before,
            "rms_after": rms_after,
        },
    )
    return refined, True, rms_before, rms_after
