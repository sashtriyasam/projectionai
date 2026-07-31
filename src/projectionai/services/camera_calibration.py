"""Camera calibration abstraction.

Defines the reusable :class:`CameraCalibrationAlgorithm` interface for
computing camera intrinsic parameters (focal length, principal point,
distortion coefficients) from observations of a known planar calibration
board.

This interface is deliberately separate from :class:`Calibrator`
(``projectionai.services.calibration``), which aligns the virtual 3D
model with the physical object via 2D-3D correspondences for projection
mapping. Camera intrinsic calibration is a different concern: it recovers
the *lens* parameters of a camera from planar board views and is a
prerequisite for any vision-based calibration workflow.

Design:

- Algorithm implementations live in
  ``projectionai.infrastructure.calibration`` (chessboard, ArUco,
  Charuco, circle grid, ...) and implement this interface.
- The calibration framework orchestrates algorithms through the generic
  pipeline stages in ``projectionai.calibration.camera_stages``; the
  framework itself never contains vision logic.
- A camera must be calibrated before downstream steps (e.g. projector
  calibration) can assume metric accuracy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from projectionai.services.camera import Frame


class CameraCalibrationError(RuntimeError):
    """Raised when camera calibration cannot be computed."""


@dataclass(frozen=True)
class CalibrationBoardConfig:
    """Configuration of a planar calibration board.

    Attributes:
        pattern_size: Interior corner count ``(columns, rows)`` of the
            board (e.g. ``(9, 6)`` for a 10x7 checkerboard).
        square_size_mm: Physical size of one board square in millimetres.
    """

    pattern_size: tuple[int, int]
    square_size_mm: float

    def __post_init__(self) -> None:
        cols, rows = self.pattern_size
        if cols < 2 or rows < 2:
            raise CameraCalibrationError(
                f"pattern_size must be at least (2, 2), got {self.pattern_size}"
            )
        if self.square_size_mm <= 0.0:
            raise CameraCalibrationError(
                f"square_size_mm must be positive, got {self.square_size_mm}"
            )

    @property
    def corner_count(self) -> int:
        """Total number of interior corners on the board."""
        cols, rows = self.pattern_size
        return cols * rows


@dataclass(frozen=True)
class BoardDetection:
    """A detected calibration board in a single frame.

    Attributes:
        corners: Detected corner coordinates with shape ``(N, 2)`` in
            pixel space (column, row) — the layout OpenCV 5's
            ``findChessboardCornersSB`` produces.
        image_size: ``(width, height)`` of the source frame.
        frame_number: Sequence number of the source frame (``0`` when
            unknown).
    """

    corners: NDArray[np.float32]
    image_size: tuple[int, int]
    frame_number: int = 0


@dataclass(frozen=True)
class CameraCalibrationResult:
    """Intrinsic calibration output for a single camera.

    Attributes:
        camera_matrix: 3x3 intrinsic matrix
            ``[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]``.
        distortion_coeffs: Distortion coefficients ``(k1, k2, p1, p2, k3)``.
        image_size: ``(width, height)`` of the views used.
        reprojection_error: Overall RMS reprojection error in pixels.
        num_views: Number of board views used.
        per_view_errors: Per-view RMS error, one entry per view.
    """

    camera_matrix: NDArray[np.float64]
    distortion_coeffs: NDArray[np.float64]
    image_size: tuple[int, int]
    reprojection_error: float
    num_views: int
    per_view_errors: tuple[float, ...] = ()


class CameraCalibrationAlgorithm(ABC):
    """Reusable interface for camera intrinsic calibration methods.

    Subclasses implement one board-detection family:

    - Chessboard (``ChessboardCalibrationAlgorithm``)
    - ArUco / Charuco boards
    - Circle grids
    - Custom patterns

    Implementations are pure vision algorithms: they hold no UI, event,
    or persistence concerns. The calibration framework orchestrates them
    through ``CalibrationStage`` pipeline stages.
    """

    @abstractmethod
    def detect(self, frame: Frame) -> BoardDetection | None:
        """Detect the calibration board in *frame*.

        Args:
            frame: A captured RGB frame.

        Returns:
            The board detection, or ``None`` when the board is not
            (fully) visible in the frame.
        """

    @abstractmethod
    def calibrate(
        self, detections: Sequence[BoardDetection]
    ) -> CameraCalibrationResult:
        """Compute camera intrinsics from collected board detections.

        Args:
            detections: Board detections gathered from multiple views.

        Returns:
            The intrinsic calibration result.

        Raises:
            CameraCalibrationError: If calibration cannot be computed
                (e.g. too few valid views or inconsistent image sizes).
        """
