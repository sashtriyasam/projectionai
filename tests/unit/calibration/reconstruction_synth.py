"""Deterministic synthetic reconstruction ground truth.

Generates known 3D surface points, projects them through known camera
and projector models, and packages the result as a CorrespondenceSet so
decoder/reconstruction correctness can be verified independently of
camera hardware and synchronization.

Cases:
- identity:     camera and projector co-located at origin looking +Z
- translated:   surface plane translated + tilted in camera frame
- rotated:      surface plane rotated 15 deg about X
- offset_cam:   camera translated; projector offset to the side
- distorted:    camera with mild radial distortion
"""

from __future__ import annotations

from typing import TypedDict

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.calibration_session import CorrespondenceSet
from projectionai.services.projector_calibration import CalibratedCamera, SurfacePlane


class SynthCase(TypedDict):
    correspondences: CorrespondenceSet
    camera: CalibratedCamera
    surface: SurfacePlane
    projector_intrinsics: NDArray[np.float64]
    projector_pose: NDArray[np.float64]
    gt_points: NDArray[np.float64]
    gt_projector_pixels: NDArray[np.float64]
    gt_camera_pixels: NDArray[np.float64]


def _rotation_x(deg: float) -> NDArray[np.float64]:
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def _project(
    points: NDArray[np.float64],
    k: NDArray[np.float64],
    dist: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Project 3D points with a pinhole + Brown-Conrady distortion."""
    x = points[:, 0] / points[:, 2]
    y = points[:, 1] / points[:, 2]
    if dist is not None and np.any(dist != 0):
        r2 = x * x + y * y
        k1, k2, p1, p2, k3 = dist[0], dist[1], dist[2], dist[3], dist[4]
        radial = 1.0 + k1 * r2 + k2 * r2**2 + k3 * r2**3
        xd = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
        yd = y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
        x, y = xd, yd
    u = k[0, 0] * x + k[0, 2]
    v = k[1, 1] * y + k[1, 2]
    return np.column_stack((u, v))


def make_synthetic_case(
    case: str,
    n_points: int = 8000,
    cam_size: tuple[int, int] = (640, 480),
    proj_size: tuple[int, int] = (1280, 720),
    seed: int = 7,
) -> SynthCase:
    """Build a synthetic reconstruction case with known ground truth.

    Returns dict with:
    - correspondences: domain CorrespondenceSet (dense map, camera size)
    - camera: CalibratedCamera
    - surface: SurfacePlane (camera frame)
    - projector_intrinsics: (3,3)
    - projector_pose: (4,4) projector-local -> camera frame
    - gt_points: (N,3) ground-truth 3D points (camera frame)
    - gt_projector_pixels: (N,2)
    - gt_camera_pixels: (N,2)
    """
    rng = np.random.default_rng(seed)
    cw, ch = cam_size
    pw, ph = proj_size

    cam_k = np.array(
        [[float(cw), 0.0, cw / 2.0], [0.0, float(cw), ch / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    proj_k = np.array(
        [[float(pw), 0.0, pw / 2.0], [0.0, float(pw), ph / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )

    # Camera pose is identity (camera frame == world frame).
    # Surface plane (camera frame): normal . p + offset = 0
    if case == "identity":
        normal = np.array([0.0, 0.0, -1.0])
        offset = 2.0
        cam_dist = None
        proj_pose = np.eye(4)
    elif case == "translated":
        normal = np.array([0.0, 0.0, -1.0])
        offset = 3.0
        cam_dist = None
        proj_pose = np.eye(4)
        proj_pose[0, 3] = 0.2
    elif case == "rotated":
        r = _rotation_x(15.0)
        normal = -r @ np.array([0.0, 0.0, 1.0])
        offset = 2.0
        cam_dist = None
        proj_pose = np.eye(4)
    elif case == "offset_cam":
        normal = np.array([0.0, 0.0, -1.0])
        offset = 2.5
        cam_dist = None
        proj_pose = np.eye(4)
        proj_pose[0, 3] = 0.5
        proj_pose[1, 3] = 0.1
    elif case == "distorted":
        normal = np.array([0.0, 0.0, -1.0])
        offset = 2.0
        cam_dist = np.array([0.1, -0.05, 0.001, 0.001, 0.0])
        proj_pose = np.eye(4)
    else:
        raise ValueError(f"unknown case {case!r}")

    # Build orthonormal plane basis (u, v in-plane)
    n = normal / np.linalg.norm(normal)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[2]) > 0.9 else np.array([0.0, 0.0, 1.0])
    u = np.cross(helper, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)

    # Sample plane points in-plane
    span_x = 1.2
    span_y = 0.9
    su = rng.uniform(-span_x, span_x, n_points)
    sv = rng.uniform(-span_y, span_y, n_points)
    center = -offset * n
    gt_points = center + su[:, None] * u + sv[:, None] * v

    # Project through camera
    cam_px = _project(gt_points, cam_k, cam_dist)
    # Project through projector. The pose maps projector-local points into the
    # camera frame, so a camera-frame point maps to projector-local via the
    # inverse pose (matching project_points semantics: K @ (inv(pose) @ p)).
    inv_pose = np.linalg.inv(proj_pose)
    proj_local = gt_points @ inv_pose[:3, :3].T + inv_pose[:3, 3]
    proj_px = _project(proj_local, proj_k, None)

    # Keep points inside the camera frame and in front of both
    in_cam = (
        (cam_px[:, 0] >= 0)
        & (cam_px[:, 0] < cw)
        & (cam_px[:, 1] >= 0)
        & (cam_px[:, 1] < ch)
    )
    in_proj = (
        (proj_px[:, 0] >= 0)
        & (proj_px[:, 0] < pw)
        & (proj_px[:, 1] >= 0)
        & (proj_px[:, 1] < ph)
    )
    keep = in_cam & in_proj & (gt_points[:, 2] > 0) & (proj_local[:, 2] > 0)
    gt_points = gt_points[keep]
    cam_px = cam_px[keep]
    proj_px = proj_px[keep]
    if len(gt_points) == 0:
        raise ValueError("synthetic case produced no visible points")

    # Build dense CorrespondenceSet at camera resolution
    proj_x = np.full((ch, cw), np.nan, dtype=np.float32)
    proj_y = np.full((ch, cw), np.nan, dtype=np.float32)
    mask = np.zeros((ch, cw), dtype=np.bool_)
    xi = np.clip(cam_px[:, 0].astype(np.int64), 0, cw - 1)
    yi = np.clip(cam_px[:, 1].astype(np.int64), 0, ch - 1)
    proj_x[yi, xi] = proj_px[:, 0].astype(np.float32)
    proj_y[yi, xi] = proj_px[:, 1].astype(np.float32)
    mask[yi, xi] = True
    valid_ratio = float(mask.sum()) / float(cw * ch)

    correspondences = CorrespondenceSet(
        projector_x=proj_x,
        projector_y=proj_y,
        mask=mask,
        image_size=(cw, ch),
        projector_resolution=(pw, ph),
        sequence_id=f"synth-{case}",
        threshold=127,
        valid_ratio=valid_ratio,
    )
    camera = CalibratedCamera(
        camera_matrix=cam_k,
        distortion_coeffs=cam_dist if cam_dist is not None else np.zeros(5),
        image_size=(cw, ch),
    )
    surface = SurfacePlane(normal=normal, offset=offset)

    return {
        "correspondences": correspondences,
        "camera": camera,
        "surface": surface,
        "projector_intrinsics": proj_k,
        "projector_pose": proj_pose,
        "gt_points": gt_points,
        "gt_projector_pixels": proj_px,
        "gt_camera_pixels": cam_px,
    }
