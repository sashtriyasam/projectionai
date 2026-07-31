"""Chessboard camera calibration implementation.

Implements :class:`CameraCalibrationAlgorithm` using OpenCV's
``findChessboardCornersSB`` (subpixel-accuracy variant) and
``calibrateCamera``.

The implementation is deliberately free of framework concerns — the
calibration pipeline orchestrates it through the generic stages in
``projectionai.calibration.camera_stages``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import override

import cv2
import numpy as np

from projectionai.services.camera import Frame
from projectionai.services.camera_calibration import (
    BoardDetection,
    CalibrationBoardConfig,
    CameraCalibrationAlgorithm,
    CameraCalibrationError,
    CameraCalibrationResult,
)

_logger = logging.getLogger(__name__)

# Minimum views required for a well-posed intrinsic solve with OpenCV.
_MIN_CALIBRATION_VIEWS = 3

# cornerSubPix refinement window and termination criteria.
_SUBPIX_WINDOW = (11, 11)
_SUBPIX_CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001,
)


class ChessboardCalibrationAlgorithm(CameraCalibrationAlgorithm):
    """Camera intrinsic calibration from planar chessboard views.

    Args:
        config: The chessboard geometry (interior corners, square size).
        refine_subpixel: Refine detected corners with ``cv2.cornerSubPix``
            (default ``True``). ``findChessboardCornersSB`` already
            returns subpixel corners with the accuracy flag, but the
            extra refinement tightens the estimates for calibration.
    """

    def __init__(
        self,
        config: CalibrationBoardConfig,
        refine_subpixel: bool = True,
    ) -> None:
        self._config = config
        self._refine_subpixel = refine_subpixel

    @property
    def config(self) -> CalibrationBoardConfig:
        """The board configuration this algorithm is calibrated for."""
        return self._config

    @override
    def detect(self, frame: Frame) -> BoardDetection | None:
        gray = cv2.cvtColor(frame.image, cv2.COLOR_RGB2GRAY)
        found, corners = cv2.findChessboardCornersSB(
            gray, self._config.pattern_size, flags=cv2.CALIB_CB_ACCURACY
        )
        if not found:
            return None
        if self._refine_subpixel:
            corners = cv2.cornerSubPix(
                gray, corners, _SUBPIX_WINDOW, (-1, -1), _SUBPIX_CRITERIA
            )
        return BoardDetection(
            corners=np.asarray(corners, dtype=np.float32),
            image_size=(frame.width, frame.height),
            frame_number=frame.frame_number,
        )

    @override
    def calibrate(
        self, detections: Sequence[BoardDetection]
    ) -> CameraCalibrationResult:
        views = list(detections)
        if len(views) < _MIN_CALIBRATION_VIEWS:
            msg = (
                f"Need at least {_MIN_CALIBRATION_VIEWS} board views for "
                f"calibration, got {len(views)}"
            )
            raise CameraCalibrationError(msg)

        sizes = {view.image_size for view in views}
        if len(sizes) != 1:
            msg = f"All views must share one image size, got {sorted(sizes)}"
            raise CameraCalibrationError(msg)

        object_points = [self._object_points() for _ in views]
        image_points = [view.corners for view in views]
        image_size = views[0].image_size

        ret, camera_matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
            object_points,
            image_points,
            (image_size[0], image_size[1]),
            None,
            None,
        )

        per_view_errors = self._per_view_errors(
            object_points, image_points, rvecs, tvecs, camera_matrix, distortion
        )
        _logger.info(
            "Chessboard calibration: %d views, RMS %.3f px",
            len(views),
            float(ret),
        )
        return CameraCalibrationResult(
            camera_matrix=np.asarray(camera_matrix, dtype=np.float64),
            # OpenCV 5 returns the coefficients as a row vector (1, 5);
            # normalise to the documented 1-D layout (k1, k2, p1, p2, k3).
            distortion_coeffs=np.asarray(distortion, dtype=np.float64).reshape(-1),
            image_size=image_size,
            reprojection_error=float(ret),
            num_views=len(views),
            per_view_errors=tuple(per_view_errors),
        )

    # -- Internal -----------------------------------------------------------

    def _object_points(self) -> np.ndarray:
        """Object points of the board corners on the Z=0 plane (mm)."""
        cols, rows = self._config.pattern_size
        square = self._config.square_size_mm
        points = np.zeros((cols * rows, 3), np.float32)
        points[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square
        return points

    @staticmethod
    def _per_view_errors(
        object_points: Sequence[np.ndarray],
        image_points: Sequence[np.ndarray],
        rvecs: Sequence[np.ndarray],
        tvecs: Sequence[np.ndarray],
        camera_matrix: np.ndarray,
        distortion: np.ndarray,
    ) -> list[float]:
        """Per-view RMS reprojection error in pixels."""
        errors: list[float] = []
        for obj, img, rvec, tvec in zip(
            object_points, image_points, rvecs, tvecs, strict=True
        ):
            projected, _ = cv2.projectPoints(obj, rvec, tvec, camera_matrix, distortion)
            projected = projected.reshape(-1, 2)
            img = img.reshape(-1, 2)
            errors.append(
                float(np.sqrt(np.mean(np.sum(np.square(projected - img), axis=1))))
            )
        return errors
