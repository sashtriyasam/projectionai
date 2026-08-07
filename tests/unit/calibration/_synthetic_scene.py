"""Synthetic structured-light scene generation shared by projector tests.

Renders what a calibrated camera sees when a projector displays gray-code
patterns onto a planar surface, with known ground-truth projector
intrinsics and pose. Calibration tests assert that the algorithm recovers
the true intrinsics and pose from these renders.

Scene model:

- Camera at the origin looking along ``+z`` (OpenCV convention), no
  distortion.
- Planar surface ``normal . p + offset = 0``, e.g. the plane ``z = 1500``.
- Projector at ``t_proj`` with rotation ``rvec_proj`` (projector-local ->
  camera frame), intrinsics ``K_proj`` (principal point at the projector
  centre — the MVP model).

The geometry is chosen so the camera *resolves* the projector's pixels:
the camera uses a long lens (f = 4500, pixel size 0.333 mm at the plane)
while the projector's pixels span 0.35 mm, so every projected pixel is
sampled by at least one camera pixel. The projector sits at
``t = (70, 140, 800)`` so its optical axis hits the plane at the camera's
principal point — the lit quad (448 x 252 mm) is centred in the camera
view (427 x 240 mm), which keeps the projector-frame coverage high
(> 0.85) while only the view corners fall outside the quad.

Pixels outside the lit quad are rendered at mid-gray (128), above the
decoder threshold (127) in every pattern, so they decode to an
out-of-range coordinate and are marked invalid. This mimics the
all-white/all-black reference mask of real gray-code pipelines and keeps
spurious ``(0, 0)`` correspondences out of the solver.

Rendering: the plane induces a homography from projector pixels to camera
pixels. With the camera as view 2 at the origin (``R2 = I, t2 = 0``) and
the projector as view 1 at pose ``(R, t)`` (projector-local -> camera
frame), the plane expressed in the projector frame is
``n1 . X1 = d1`` with ``n1 = R^T n`` and ``d1 = d - n^T t``, and the
Hartley & Zisserman two-view plane homography reduces to::

    H = K_cam (R + t n1^T / d1) K_proj^-1

``cv2.warpPerspective`` with nearest-neighbour sampling keeps the stripe
patterns binary (no interpolation ambiguity at edges).
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
)
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    PatternSequence,
    SurfacePlane,
)

# Ground-truth camera (no distortion). The long lens (f = 4500) resolves
# the projector's pixels on the plane (0.333 mm vs 0.35 mm) so decoding
# yields dense, high-coverage correspondences.
SYNTHETIC_CAMERA_MATRIX: NDArray[np.float64] = np.array(
    [[4500.0, 0.0, 640.0], [0.0, 4500.0, 360.0], [0.0, 0.0, 1.0]],
    dtype=np.float64,
)
SYNTHETIC_IMAGE_SIZE = (1280, 720)
SYNTHETIC_CAMERA = CalibratedCamera(
    camera_matrix=SYNTHETIC_CAMERA_MATRIX,
    distortion_coeffs=np.zeros(5, dtype=np.float64),
    image_size=SYNTHETIC_IMAGE_SIZE,
)

# Ground-truth projector: a narrow-frustum lens (f = 2000) at 1280 x 720,
# positioned (70, 140, 800) so the plane is tilted in the projector's view
# (a well-conditioned homography for the Zhang intrinsics solve) and the
# lit quad lands centred in the camera view.
SYNTHETIC_PROJECTOR_RESOLUTION = (1280, 720)
SYNTHETIC_PROJECTOR_MATRIX: NDArray[np.float64] = np.array(
    [[2000.0, 0.0, 640.0], [0.0, 2000.0, 360.0], [0.0, 0.0, 1.0]],
    dtype=np.float64,
)
SYNTHETIC_PROJECTOR_RVEC: NDArray[np.float64] = np.array([0.2, -0.1, 0.03])
SYNTHETIC_PROJECTOR_TVEC: NDArray[np.float64] = np.array([70.0, 140.0, 800.0])

# Plane z = 1500 mm in camera coordinates.
SYNTHETIC_PLANE = SurfacePlane(
    normal=np.array([0.0, 0.0, 1.0], dtype=np.float64), offset=-1500.0
)

_PATTERN_GENERATOR = GrayCodePatternGenerator()


def projector_pose_matrix(
    rvec: NDArray[np.float64] = SYNTHETIC_PROJECTOR_RVEC,
    tvec: NDArray[np.float64] = SYNTHETIC_PROJECTOR_TVEC,
) -> NDArray[np.float64]:
    """Ground-truth 4x4 pose mapping projector-local -> camera frame."""
    rotation, _ = cv2.Rodrigues(np.asarray(rvec, np.float64))
    pose = np.eye(4, dtype=np.float64)
    pose[:3, :3] = rotation
    pose[:3, 3] = np.asarray(tvec, np.float64).reshape(3)
    return pose


def _plane_homography(
    camera_matrix: NDArray[np.float64],
    projector_matrix: NDArray[np.float64],
    rvec: NDArray[np.float64],
    tvec: NDArray[np.float64],
    plane: SurfacePlane,
) -> NDArray[np.float64]:
    """Homography mapping projector pixels to camera pixels via the plane."""
    rotation, _ = cv2.Rodrigues(np.asarray(rvec, np.float64))
    t = np.asarray(tvec, np.float64).reshape(3, 1)
    n = np.asarray(plane.normal, np.float64).reshape(3, 1)
    d = -plane.offset  # plane: n^T p = d

    n1 = rotation.T @ n  # plane normal in the projector frame
    d1 = d - float((n.T @ t).item())  # plane offset in the projector frame
    homography = (
        camera_matrix @ (rotation + t @ n1.T / d1) @ np.linalg.inv(projector_matrix)
    )
    return homography


def render_capture(
    pattern: NDArray[np.uint8],
    *,
    camera_matrix: NDArray[np.float64] = SYNTHETIC_CAMERA_MATRIX,
    image_size: tuple[int, int] = SYNTHETIC_IMAGE_SIZE,
    projector_matrix: NDArray[np.float64] = SYNTHETIC_PROJECTOR_MATRIX,
    rvec: NDArray[np.float64] = SYNTHETIC_PROJECTOR_RVEC,
    tvec: NDArray[np.float64] = SYNTHETIC_PROJECTOR_TVEC,
    plane: SurfacePlane = SYNTHETIC_PLANE,
) -> NDArray[np.uint8]:
    """Render the camera's view of a projected pattern (RGB, H x W x 3).

    Pixels outside the lit quad are filled with mid-gray (128), above the
    decoder threshold in every pattern, so unlit pixels decode to an
    out-of-range coordinate and are marked invalid by the matcher.
    """
    homography = _plane_homography(camera_matrix, projector_matrix, rvec, tvec, plane)
    view = cv2.warpPerspective(
        pattern,
        homography,
        image_size,
        flags=cv2.INTER_NEAREST,
        borderValue=128,
    )
    return cv2.cvtColor(view, cv2.COLOR_GRAY2RGB)


def synthetic_sequence(
    resolution: tuple[int, int] = SYNTHETIC_PROJECTOR_RESOLUTION,
) -> PatternSequence:
    """Build the ground-truth gray-code pattern sequence."""
    width, height = resolution
    return _PATTERN_GENERATOR.build_sequence(width, height)


def synthetic_captures(
    sequence: PatternSequence | None = None,
    **kwargs: Any,
) -> list[NDArray[np.uint8]]:
    """Render the camera's captures for a full pattern sequence.

    Extra keyword arguments are forwarded to :func:`render_capture`.
    """
    sequence = sequence or synthetic_sequence()
    return [render_capture(pattern.image, **kwargs) for pattern in sequence.patterns]
