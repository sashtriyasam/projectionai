"""Projector calibration estimators.

Triangulates camera-to-projector correspondences through the known
surface plane and recovers:

- the projector's 3x3 intrinsic matrix (``ProjectorIntrinsicsEstimator``),
- the projector's pose relative to the camera (``ProjectorExtrinsicsEstimator``),
- the combined transform plus forward/inverse projections
  (``CameraProjectorTransformEstimator`` / ``CameraProjectorTransform``),
- projector pixel positions of known 3D points
  (``ProjectorCornerEstimator``).

The intrinsics estimate fixes the principal point at the projector's
centre and assumes a pinhole model (zero skew, zero distortion) — the
single-surface MVP limitation documented in the OUTPUT document. With
one surface orientation, the two Zhang-style constraints on the
plane-to-projector homography are exactly enough to recover ``fx`` and
``fy``; multiple orientations would refine the full model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.services.projector_calibration import (
    CalibratedCamera,
    CorrespondenceMap,
    ProjectorCalibrationError,
    SurfacePlane,
)

_logger = logging.getLogger(__name__)

_MIN_HOMOGRAPHY_POINTS = 4
_DEFAULT_MAX_CORRESPONDENCES = 20_000


def project_points(
    points_camera: NDArray[np.float64],
    intrinsics: NDArray[np.float64],
    pose: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Forward-project camera-frame 3D points into projector pixels.

    Applies ``p = K @ (T_inv @ p_cam)`` where ``T_inv`` is the inverse
    of *pose* (which maps projector-local points into the camera frame).

    Returns:
        ``(N, 2)`` projector pixel coordinates.
    """
    transform_inv = np.linalg.inv(pose)
    hom = np.column_stack((points_camera, np.ones(len(points_camera))))
    local = hom @ transform_inv.T
    projected = local[:, :3] @ intrinsics.T
    with np.errstate(divide="ignore", invalid="ignore"):
        return projected[:, :2] / projected[:, 2:3]


def undistort_points(
    points: NDArray[np.float64], camera: CalibratedCamera
) -> NDArray[np.float64]:
    """Map camera pixels to normalized (undistorted) image coordinates."""
    if len(points) == 0:
        return np.zeros((0, 2), dtype=np.float64)
    undistorted = cv2.undistortPoints(
        points.reshape(-1, 1, 2).astype(np.float64),
        camera.camera_matrix,
        camera.distortion_coeffs,
        P=np.eye(3),
    )
    return np.asarray(undistorted, dtype=np.float64).reshape(-1, 2)


def triangulate_plane(
    normalized: NDArray[np.float64], surface: SurfacePlane
) -> NDArray[np.float64]:
    """Intersect normalized camera rays with the surface plane.

    For each ray ``r = (x, y, 1)`` the intersection with
    ``normal . p + offset = 0`` is ``p = t * r`` with
    ``t = -offset / (normal . r)``.
    """
    rays = np.column_stack((normalized, np.ones(len(normalized))))
    denominator = rays @ surface.normal
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = -surface.offset / denominator
        return rays * scale[:, None]


def sample_correspondences(
    correspondences: CorrespondenceMap,
    max_points: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Sample camera/projector pixel pairs using deterministic stride.

    Returns:
        ``(camera_pixels (N, 2), projector_pixels (N, 2))``.
    """
    ys, xs = np.nonzero(correspondences.mask)
    if len(xs) > max_points:
        step = int(np.ceil(len(xs) / max_points))
        ys, xs = ys[::step], xs[::step]
    camera_pixels = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
    projector_pixels = np.column_stack(
        (
            correspondences.projector_x[ys, xs].astype(np.float64),
            correspondences.projector_y[ys, xs].astype(np.float64),
        )
    )
    return camera_pixels, projector_pixels


def plane_basis(
    points: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Compute an orthonormal plane basis from coplanar 3D points.

    Returns:
        ``(centroid (3,), u_axis (3,), v_axis (3,))``.
    """
    centroid = points.mean(axis=0)
    # Thin SVD: only the 3x3 right singular vectors are needed. The default
    # full_matrices=True computes an (N, N) U matrix for the (N, 3) point
    # cloud — ~3 GB allocation and minutes of work at 20k points (and worse
    # for the (2N, 9) homography solve), which made calibration appear
    # pathologically slow and occasionally fail with MemoryError.
    _, _, vh = np.linalg.svd(points - centroid, full_matrices=False)
    return centroid, vh[0], vh[1]


class ProjectorIntrinsicsEstimator:
    """Estimates the projector's 3x3 intrinsic matrix.

    Recovers ``fx`` and ``fy`` from a single homography between the
    surface plane and the projector image, applying the Zhang constraints
    with the principal point fixed at the projector's centre and zero
    skew/distortion.

    The homography is fitted with deterministic least squares rather than
    RANSAC: correspondences are already filtered by the decode validity
    mask and finite plane intersections, and the reprojection validator
    gates the final result, so the extra robustness is unnecessary —
    while RANSAC's adaptive termination degenerates on near-perfect data
    and can burn its full iteration budget (tens of seconds on 20k
    points), LSQ is exact and constant-time.
    """

    def estimate(
        self,
        plane_points: NDArray[np.float64],
        projector_pixels: NDArray[np.float64],
        resolution: tuple[int, int],
    ) -> NDArray[np.float64]:
        """Estimate the intrinsic matrix.

        Args:
            plane_points: ``(N, 3)`` coplanar points in camera coordinates.
            projector_pixels: ``(N, 2)`` observed projector pixels.
            resolution: Projector ``(width, height)``.

        Returns:
            The 3x3 intrinsic matrix.

        Raises:
            ProjectorCalibrationError: If the geometry is degenerate.
        """
        if len(plane_points) < _MIN_HOMOGRAPHY_POINTS:
            raise ProjectorCalibrationError(
                f"Need at least {_MIN_HOMOGRAPHY_POINTS} correspondences, "
                f"got {len(plane_points)}"
            )

        width, height = resolution
        cx, cy = width / 2.0, height / 2.0

        centroid, u_axis, v_axis = plane_basis(plane_points)
        centered_3d = plane_points - centroid
        plane_2d = np.column_stack((centered_3d @ u_axis, centered_3d @ v_axis))
        centered_pixels = projector_pixels - np.array([cx, cy])

        homography, _ = cv2.findHomography(plane_2d, centered_pixels, 0)
        if homography is None:
            raise ProjectorCalibrationError("Homography estimation failed")

        h1, h2, _ = homography[:, 0], homography[:, 1], homography[:, 2]

        # Zhang single-view constraints with K = diag(fx, fy, 1):
        #   h1^T K^-T K^-1 h2 = 0                (rotations orthogonal)
        #   h1^T K^-T K^-1 h1 = h2^T K^-T K^-1 h2 (equal column norms)
        matrix = np.array(
            [
                [h1[0] * h2[0], h1[1] * h2[1]],
                [h1[0] ** 2 - h2[0] ** 2, h1[1] ** 2 - h2[1] ** 2],
            ]
        )
        rhs = np.array([-h1[2] * h2[2], -(h1[2] ** 2 - h2[2] ** 2)])

        if abs(np.linalg.det(matrix)) < 1e-12:
            raise ProjectorCalibrationError(
                "Degenerate plane pose — intrinsics are not recoverable "
                "from this single surface orientation"
            )

        inv_fx2, inv_fy2 = np.linalg.solve(matrix, rhs)
        if inv_fx2 <= 0.0 or inv_fy2 <= 0.0:
            raise ProjectorCalibrationError(
                "Non-positive focal length estimate — degenerate geometry"
            )

        fx = float(np.sqrt(1.0 / inv_fx2))
        fy = float(np.sqrt(1.0 / inv_fy2))
        _logger.debug("Estimated projector intrinsics fx=%.2f fy=%.2f", fx, fy)
        return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])


class ProjectorExtrinsicsEstimator:
    """Estimates the projector pose given its intrinsic matrix.

    Uses ``cv2.solvePnP`` with the projector modelled as an inverse
    camera: 3D points (camera frame) map to projector pixels through
    ``K_proj`` and the camera-to-projector rigid transform.
    """

    def estimate(
        self,
        plane_points: NDArray[np.float64],
        projector_pixels: NDArray[np.float64],
        intrinsics: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Estimate the projector pose.

        Args:
            plane_points: ``(N, 3)`` points in camera coordinates.
            projector_pixels: ``(N, 2)`` observed projector pixels.
            intrinsics: The 3x3 projector intrinsic matrix.

        Returns:
            The 4x4 pose mapping projector-local points into the camera
            coordinate frame.

        Raises:
            ProjectorCalibrationError: If ``solvePnP`` fails.
        """
        if len(plane_points) < _MIN_HOMOGRAPHY_POINTS:
            raise ProjectorCalibrationError(
                f"Need at least {_MIN_HOMOGRAPHY_POINTS} correspondences, "
                f"got {len(plane_points)}"
            )

        distortion = np.zeros(5, dtype=np.float64)
        ret, rvec, tvec = cv2.solvePnP(
            plane_points.reshape(-1, 1, 3).astype(np.float64),
            projector_pixels.reshape(-1, 1, 2).astype(np.float64),
            intrinsics.astype(np.float64),
            distortion,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ret:
            raise ProjectorCalibrationError("solvePnP failed to converge")

        rotation, _ = cv2.Rodrigues(rvec)
        transform_camera_to_projector = np.eye(4)
        transform_camera_to_projector[:3, :3] = rotation
        transform_camera_to_projector[:3, 3] = np.asarray(
            tvec, dtype=np.float64
        ).reshape(3)

        # Pose maps projector-local -> camera frame (inverse of the
        # camera -> projector transform recovered by solvePnP).
        return np.linalg.inv(transform_camera_to_projector)


@dataclass(frozen=True)
class CameraProjectorTransform:
    """Complete camera<->projector calibration result.

    Attributes:
        intrinsics: Projector 3x3 intrinsic matrix.
        resolution: Projector ``(width, height)``.
        pose: 4x4 transform mapping projector-local 3D points into the
            camera coordinate frame.
    """

    intrinsics: NDArray[np.float64]
    resolution: tuple[int, int]
    pose: NDArray[np.float64]

    @property
    def transform_camera_to_projector(self) -> NDArray[np.float64]:
        """4x4 transform mapping camera-frame points to projector-local."""
        return np.linalg.inv(self.pose)

    def project(self, points_camera: NDArray[np.float64]) -> NDArray[np.float64]:
        """Project camera-frame 3D points into projector pixels."""
        return project_points(points_camera, self.intrinsics, self.pose)

    def unproject_ray(
        self, projector_pixels: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Unit ray directions (camera frame) through projector pixels."""
        kinv = np.linalg.inv(self.intrinsics)
        hom = np.column_stack((projector_pixels, np.ones(len(projector_pixels))))
        local_directions = hom @ kinv.T
        directions = local_directions @ self.pose[:3, :3].T
        norms = np.linalg.norm(directions, axis=1, keepdims=True)
        return directions / norms


class CameraProjectorTransformEstimator:
    """Composes triangulation, intrinsics, and pose estimation.

    Args:
        max_correspondences: Upper bound on correspondences fed to the
            solvers (deterministic stride sampling).
    """

    def __init__(self, max_correspondences: int = _DEFAULT_MAX_CORRESPONDENCES) -> None:
        self._intrinsics_estimator = ProjectorIntrinsicsEstimator()
        self._extrinsics_estimator = ProjectorExtrinsicsEstimator()
        self._max_correspondences = max_correspondences

    def estimate(
        self,
        correspondences: CorrespondenceMap,
        camera: CalibratedCamera,
        surface: SurfacePlane,
        resolution: tuple[int, int],
    ) -> CameraProjectorTransform:
        """Estimate the full camera<->projector transform.

        Raises:
            ProjectorCalibrationError: If too few correspondences survive
                triangulation or the solvers degenerate.
        """
        camera_pixels, projector_pixels = sample_correspondences(
            correspondences, self._max_correspondences
        )
        if len(camera_pixels) < _MIN_HOMOGRAPHY_POINTS:
            raise ProjectorCalibrationError(
                f"Only {len(camera_pixels)} valid correspondences after sampling"
            )

        normalized = undistort_points(camera_pixels, camera)
        plane_points = triangulate_plane(normalized, surface)

        finite = np.all(np.isfinite(plane_points), axis=1)
        if np.count_nonzero(finite) < _MIN_HOMOGRAPHY_POINTS:
            raise ProjectorCalibrationError(
                "Too few correspondences triangulate to finite 3D points"
            )
        plane_points = plane_points[finite]
        projector_pixels = projector_pixels[finite]

        intrinsics = self._intrinsics_estimator.estimate(
            plane_points, projector_pixels, resolution
        )
        pose = self._extrinsics_estimator.estimate(
            plane_points, projector_pixels, intrinsics
        )
        return CameraProjectorTransform(
            intrinsics=intrinsics, resolution=resolution, pose=pose
        )


class ProjectorCornerEstimator:
    """Estimates projector pixel positions of known 3D points.

    Given surface corners (or any points) in camera coordinates and a
    completed :class:`CameraProjectorTransform`, returns where each point
    projects in the projector image — the basis for warp-mesh generation
    and coverage visualization.
    """

    def estimate(
        self,
        points_camera: NDArray[np.float64],
        transform: CameraProjectorTransform,
    ) -> NDArray[np.float64]:
        """Project camera-frame 3D points into projector pixels.

        Raises:
            ProjectorCalibrationError: If projection yields non-finite
                pixels (points behind the projector).
        """
        if points_camera.ndim != 2 or points_camera.shape[1] != 3:
            raise ProjectorCalibrationError(
                f"points_camera must have shape (N, 3), got {points_camera.shape}"
            )
        pixels = transform.project(points_camera)
        if not np.all(np.isfinite(pixels)):
            raise ProjectorCalibrationError(
                "Projection produced non-finite pixels — points behind projector?"
            )
        return pixels
