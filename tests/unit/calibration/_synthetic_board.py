"""Synthetic chessboard view generation shared by calibration tests.

Renders perspective views of a planar checkerboard with known ground-truth
intrinsics, so tests can assert that the calibration recovers the true
camera matrix. Views use fixed poses (in-plane rotation, slight tilt, and
translation offsets) to constrain the intrinsic solve.
"""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.services.camera import Frame
from projectionai.services.camera_calibration import CalibrationBoardConfig

# Ground-truth intrinsics of the synthetic camera.
SYNTHETIC_CAMERA_MATRIX: NDArray[np.float64] = np.array(
    [[1000.0, 0.0, 640.0], [0.0, 1000.0, 360.0], [0.0, 0.0, 1.0]],
    dtype=np.float64,
)
SYNTHETIC_IMAGE_SIZE = (1280, 720)
SYNTHETIC_CONFIG = CalibrationBoardConfig(pattern_size=(9, 6), square_size_mm=30.0)

# Fixed board poses as (rvec, tvec). The world grid is centred on the board,
# so tvec (millimetres) is the board-centre position in camera coordinates.
# Views span three distances (480 / 600 / 900 mm) with in-plane rotation,
# tilt, and offsets: the z-spread keeps the radial distortion terms (k1, k2)
# separately identifiable, and every pose keeps the whole board in frame.
VIEW_POSES: tuple[tuple[list[float], list[float]], ...] = (
    ([0.0, 0.0, -0.6], [0.0, 0.0, 480.0]),
    ([0.0, 0.0, -0.45], [40.0, 0.0, 480.0]),
    ([0.0, 0.0, -0.3], [-40.0, 0.0, 480.0]),
    ([0.15, -0.1, -0.15], [0.0, 0.0, 600.0]),
    ([0.0, 0.0, 0.0], [0.0, -20.0, 600.0]),
    ([-0.15, 0.1, 0.15], [0.0, 0.0, 600.0]),
    ([0.2, 0.05, 0.3], [0.0, 0.0, 900.0]),
    ([-0.1, -0.15, 0.45], [20.0, 20.0, 900.0]),
    ([0.1, 0.15, 0.6], [-20.0, -20.0, 900.0]),
)

_SQUARE_PX = 50


def render_board_view(
    rvec: list[float] | NDArray[np.float64],
    tvec: list[float] | NDArray[np.float64],
    *,
    image_size: tuple[int, int] = SYNTHETIC_IMAGE_SIZE,
    camera_matrix: NDArray[np.float64] = SYNTHETIC_CAMERA_MATRIX,
    distortion: NDArray[np.float64] | None = None,
) -> NDArray[np.uint8]:
    """Render a perspective checkerboard view as an RGB image (H, W, 3).

    The board is warped with the pure pinhole homography first, then lens
    distortion is applied to the whole frame. Rendering the distortion in
    image space (rather than through the homography) keeps the frame
    physically consistent with ``camera_matrix`` and ``distortion``, which
    is what lets calibration recover the coefficients.
    """
    cols, rows = SYNTHETIC_CONFIG.pattern_size
    square_mm = SYNTHETIC_CONFIG.square_size_mm

    # World grid centred on the board so that tvec is the board-centre
    # position in camera coordinates.
    centre = np.array([cols / 2, rows / 2], np.float64)
    grid = (np.mgrid[0 : cols + 1, 0 : rows + 1] - centre.reshape(2, 1, 1)).T.reshape(
        -1, 2
    ).astype(np.float64) * square_mm
    world = np.hstack([grid, np.zeros((grid.shape[0], 1))])

    # Undistorted pinhole projection — the homography maps the board onto it.
    projected, _ = cv2.projectPoints(
        world,
        np.asarray(rvec, np.float64),
        np.asarray(tvec, np.float64),
        camera_matrix,
        None,
    )

    board = np.full(((rows + 1) * _SQUARE_PX, (cols + 1) * _SQUARE_PX), 255, np.uint8)
    for row in range(rows + 1):
        for col in range(cols + 1):
            if (row + col) % 2 == 0:
                board[
                    row * _SQUARE_PX : (row + 1) * _SQUARE_PX,
                    col * _SQUARE_PX : (col + 1) * _SQUARE_PX,
                ] = 0

    # Canonical grid in board-pixel coordinates (origin at the board's
    # top-left corner) matching the rendered board image.
    canonical = (
        np.mgrid[0 : cols + 1, 0 : rows + 1].T.reshape(-1, 2).astype(np.float32)
        * _SQUARE_PX
    )
    homography, _ = cv2.findHomography(canonical, projected.reshape(-1, 2))
    view = cv2.warpPerspective(board, homography, image_size, borderValue=255)

    if distortion is not None and np.any(distortion):
        view = _apply_distortion(view, camera_matrix, distortion)
    return cv2.cvtColor(view, cv2.COLOR_GRAY2RGB)


def _apply_distortion(
    image: NDArray[np.uint8],
    camera_matrix: NDArray[np.float64],
    distortion: NDArray[np.float64],
) -> NDArray[np.uint8]:
    """Remap *image* (a distortion-free view) with the lens distortion model."""
    k1, k2, p1, p2, k3 = (float(c) for c in np.asarray(distortion).reshape(-1))
    fx, fy = float(camera_matrix[0, 0]), float(camera_matrix[1, 1])
    cx, cy = float(camera_matrix[0, 2]), float(camera_matrix[1, 2])
    height, width = image.shape[:2]

    # Normalised pixel grid of the distorted (output) frame.
    yy, xx = np.mgrid[0:height, 0:width]
    xd = (xx - cx) / fx
    yd = (yy - cy) / fy

    # Fixed-point inversion of the OpenCV distortion model: find the
    # undistorted coordinate that lands on each distorted pixel.
    x = xd
    y = yd
    for _ in range(10):
        r2 = x * x + y * y
        radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        x = (xd - 2.0 * p1 * x * y - p2 * (r2 + 2.0 * x * x)) / radial
        y = (yd - p1 * (r2 + 2.0 * y * y) - 2.0 * p2 * x * y) / radial

    map_x = (x * fx + cx).astype(np.float32)
    map_y = (y * fy + cy).astype(np.float32)
    return cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderValue=255)


def synthetic_frame(index: int, camera_id: str = "synthetic") -> Frame:
    """Return a Frame with the board rendered at a fixed pose (wraps around)."""
    rvec, tvec = VIEW_POSES[index % len(VIEW_POSES)]
    return Frame(
        image=render_board_view(rvec, tvec),
        timestamp=float(index),
        camera_id=camera_id,
        frame_number=index,
    )
