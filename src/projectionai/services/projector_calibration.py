"""Projector calibration abstraction.

Defines the reusable :class:`ProjectorCalibrationAlgorithm` interface for
estimating a projector's intrinsics and pose relative to a calibrated
camera using structured light projection.

The projector is modelled as an *inverse camera*: it projects rays from
its lens onto the scene instead of gathering them. Calibration therefore
recovers the 3x3 intrinsic matrix ``K_proj`` (focal length, principal
point) and a 4x4 rigid transform that places the projector in the
camera's coordinate frame. Once known, any camera-frame 3D point can be
projected into projector pixel coordinates, which is the foundation of
projection mapping (warp mesh generation).

Workflow (MVP — gray code):

1. ``build_sequence`` generates the ordered structured light patterns
   (vertical stripes encoding column bits, horizontal stripes encoding
   row bits).
2. A capture session projects each pattern onto a planar surface while
   the calibrated camera records it.
3. ``decode`` converts the captured frames into a dense
   :class:`CorrespondenceMap` — for every camera pixel, the projector
   pixel that illuminates it.
4. ``calibrate`` triangulates each correspondence through the known
   surface plane, then solves for ``K_proj`` and the projector pose.

Design:

- Algorithm implementations live in
  ``projectionai.infrastructure.projector_calibration`` (gray code MVP;
  future phase shift, ArUco, checkerboard, LiDAR, AI-assisted) and
  implement this interface.
- The calibration framework orchestrates algorithms through the generic
  pipeline stages; the framework itself never contains vision logic.
- This module depends on ``projectionai.calibration.types`` only for the
  canonical :class:`CalibrationMethod` enum, and on
  ``projectionai.services.camera`` for the :class:`Frame` capture
  contract. The enum import is ``TYPE_CHECKING``-only (it appears solely
  in annotations): importing ``calibration.types`` at runtime would pull
  in the ``calibration`` package's ``__init__`` (which eagerly imports
  ``CalibrationManager`` -> ``projector_stages`` -> this module), a
  circular import.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray

from projectionai.core.errors import ProjectionAIError
from projectionai.services.camera import Frame

if TYPE_CHECKING:
    from projectionai.calibration.types import CalibrationMethod


class ProjectorCalibrationError(ProjectionAIError):
    """Raised when projector calibration cannot be computed."""


# ---------------------------------------------------------------------------
# Capture contracts
# ---------------------------------------------------------------------------


class PatternProjector(Protocol):
    """A device that can display full-screen patterns.

    Implementations display the pattern image at the projector's native
    resolution and blank the display on ``hide``. Satisfied by any
    projection backend; injected by the composition root.
    """

    async def show(self, image: NDArray[np.uint8]) -> None:
        """Display *image* full-screen."""
        ...

    async def hide(self) -> None:
        """Blank the display."""
        ...


class FrameSource(Protocol):
    """Minimal frame-capture facade (satisfied by ``CameraManager``)."""

    async def capture_frame(self, camera_id: str) -> Frame:
        """Capture a single frame from *camera_id*."""
        ...


class PatternAxis(StrEnum):
    """Which projector coordinate axis a structured light pattern encodes.

    A *column* pattern (vertical stripes) decodes to the projector ``x``
    pixel coordinate; a *row* pattern (horizontal stripes) decodes to the
    projector ``y`` pixel coordinate.
    """

    COLUMN = "column"
    ROW = "row"


# ---------------------------------------------------------------------------
# Structured light patterns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternSpec:
    """Metadata of a single structured light pattern.

    Attributes:
        pattern_id: Zero-based index within the capture sequence.
        axis: The projector axis this pattern encodes.
        bit_index: Which binary bit of the axis coordinate this pattern
            encodes (``0`` = least significant bit).
        bit_value: The bit value this pattern displays (``0`` or ``1``).
    """

    pattern_id: int
    axis: PatternAxis
    bit_index: int
    bit_value: int

    def __post_init__(self) -> None:
        if self.pattern_id < 0:
            raise ProjectorCalibrationError(
                f"pattern_id must be >= 0, got {self.pattern_id}"
            )
        if self.bit_index < 0:
            raise ProjectorCalibrationError(
                f"bit_index must be >= 0, got {self.bit_index}"
            )
        if self.bit_value not in (0, 1):
            raise ProjectorCalibrationError(
                f"bit_value must be 0 or 1, got {self.bit_value}"
            )


@dataclass(frozen=True)
class StructuredLightPattern:
    """A rendered pattern ready to be projected.

    Attributes:
        spec: Metadata describing the pattern.
        image: Grayscale ``uint8`` image of the pattern with shape
            ``(height, width)`` at the projector's native resolution.
    """

    spec: PatternSpec
    image: NDArray[np.uint8]

    def __post_init__(self) -> None:
        if self.image.ndim != 2:
            raise ProjectorCalibrationError(
                f"pattern image must be 2D, got {self.image.ndim}D"
            )


@dataclass(frozen=True)
class PatternSequence:
    """An ordered collection of structured light patterns.

    A complete gray-code sequence contains one pattern per bit of the
    projector column coordinate (``bits_x`` vertical stripes) plus one
    pattern per bit of the row coordinate (``bits_y`` horizontal
    stripes).

    Attributes:
        patterns: The ordered patterns (projection order).
        width: Projector resolution width in pixels.
        height: Projector resolution height in pixels.
        bits_x: Number of column bits encoded.
        bits_y: Number of row bits encoded.
    """

    patterns: tuple[StructuredLightPattern, ...]
    width: int
    height: int
    bits_x: int
    bits_y: int

    def __post_init__(self) -> None:
        if not self.patterns:
            raise ProjectorCalibrationError(
                "sequence must contain at least one pattern"
            )
        if self.width <= 0 or self.height <= 0:
            raise ProjectorCalibrationError(
                f"resolution must be positive, got {self.width}x{self.height}"
            )
        if self.bits_x < 0 or self.bits_y < 0:
            raise ProjectorCalibrationError(
                f"bit counts must be >= 0, got x={self.bits_x} y={self.bits_y}"
            )
        if len(self.patterns) != self.bits_x + self.bits_y:
            raise ProjectorCalibrationError(
                f"sequence has {len(self.patterns)} patterns but "
                f"bits_x + bits_y = {self.bits_x + self.bits_y}"
            )
        for pattern in self.patterns:
            if pattern.image.shape != (self.height, self.width):
                raise ProjectorCalibrationError(
                    f"pattern {pattern.spec.pattern_id} has shape "
                    f"{pattern.image.shape}, expected ({self.height}, {self.width})"
                )

    @property
    def resolution(self) -> tuple[int, int]:
        """Projector resolution as ``(width, height)``."""
        return (self.width, self.height)


# ---------------------------------------------------------------------------
# Camera / surface prerequisites
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibratedCamera:
    """Camera intrinsics required as input to projector calibration.

    Attributes:
        camera_matrix: 3x3 intrinsic matrix
            ``[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]``.
        distortion_coeffs: Distortion coefficients ``(k1, k2, p1, p2, k3)``.
        image_size: ``(width, height)`` of the camera frames.
    """

    camera_matrix: NDArray[np.float64]
    distortion_coeffs: NDArray[np.float64]
    image_size: tuple[int, int]

    def __post_init__(self) -> None:
        if self.camera_matrix.shape != (3, 3):
            raise ProjectorCalibrationError(
                f"camera_matrix must be 3x3, got {self.camera_matrix.shape}"
            )
        if self.distortion_coeffs.shape != (5,):
            raise ProjectorCalibrationError(
                f"distortion_coeffs must have shape (5,), "
                f"got {self.distortion_coeffs.shape}"
            )
        if self.image_size[0] <= 0 or self.image_size[1] <= 0:
            raise ProjectorCalibrationError(
                f"image_size must be positive, got {self.image_size}"
            )


@dataclass(frozen=True)
class SurfacePlane:
    """Planar surface onto which patterns are projected.

    The plane is expressed in the camera coordinate frame as
    ``normal . p + offset = 0``. It is used to triangulate camera rays:
    the 3D point of a correspondence is the intersection of its camera
    ray with this plane.

    Attributes:
        normal: Unit normal ``(nx, ny, nz)`` of the plane.
        offset: Scalar ``d`` of the plane equation.
    """

    normal: NDArray[np.float64]
    offset: float

    def __post_init__(self) -> None:
        if self.normal.shape != (3,):
            raise ProjectorCalibrationError(
                f"normal must have shape (3,), got {self.normal.shape}"
            )
        norm = np.linalg.norm(self.normal)
        if norm == 0.0:
            raise ProjectorCalibrationError("plane normal must be non-zero")
        object.__setattr__(self, "normal", self.normal / norm)


# ---------------------------------------------------------------------------
# Correspondences
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectorCorrespondence:
    """A single camera-to-projector pixel correspondence.

    Attributes:
        camera_point: Camera pixel ``(x, y)``.
        projector_point: Projector pixel ``(x, y)`` that illuminates the
            camera pixel.
        confidence: Confidence in ``[0, 1]`` of the correspondence.
    """

    camera_point: tuple[float, float]
    projector_point: tuple[float, float]
    confidence: float


@dataclass(frozen=True)
class CorrespondenceMap:
    """Dense camera-to-projector mapping produced by decoding captures.

    Every camera pixel with a valid decode holds the projector pixel
    coordinates of the light that illuminated it. Invalid pixels are
    marked in ``mask``; their entries in ``projector_x``/``projector_y``
    are ``NaN``.

    Attributes:
        projector_x: Projector ``x`` per camera pixel, shape
            ``(height, width)``.
        projector_y: Projector ``y`` per camera pixel, shape
            ``(height, width)``.
        mask: Valid-correspondence mask, shape ``(height, width)``.
        image_size: ``(width, height)`` of the camera frames.
    """

    projector_x: NDArray[np.float32]
    projector_y: NDArray[np.float32]
    mask: NDArray[np.bool_]
    image_size: tuple[int, int]

    def __post_init__(self) -> None:
        height, width = self.image_size[1], self.image_size[0]
        for name, arr in (
            ("projector_x", self.projector_x),
            ("projector_y", self.projector_y),
            ("mask", self.mask),
        ):
            if arr.shape != (height, width):
                raise ProjectorCalibrationError(
                    f"{name} has shape {arr.shape}, expected ({height}, {width})"
                )
        if self.mask.dtype != np.bool_:
            raise ProjectorCalibrationError(
                f"mask must be boolean, got {self.mask.dtype}"
            )

    @property
    def num_correspondences(self) -> int:
        """Number of camera pixels with a valid decode."""
        return int(np.count_nonzero(self.mask))


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectorCalibrationResult:
    """Output of a completed projector calibration.

    Attributes:
        projector_intrinsics: 3x3 intrinsic matrix
            ``[[fx, 0, cx], [0, fy, cy], [0, 0, 1]]`` of the projector.
        projector_resolution: ``(width, height)`` of the projector.
        projector_pose: 4x4 rigid transform mapping projector-local 3D
            points into the camera coordinate frame (the projector's
            pose *in the camera frame*).
        reprojection_error: RMS projector reprojection error in pixels.
        num_correspondences: Number of correspondences used.
        coverage: Fraction of projector pixels covered by at least one
            correspondence, in ``[0, 1]``.
        confidence: Overall confidence in ``[0, 1]`` derived from error
            and coverage.
        per_point_errors: Per-correspondence reprojection error in
            projector pixels.
        camera_matrix: Camera 3x3 intrinsics used (echoed for export).
        distortion_coeffs: Camera distortion coefficients used.
        image_size: Camera ``(width, height)`` used.
    """

    projector_intrinsics: NDArray[np.float64]
    projector_resolution: tuple[int, int]
    projector_pose: NDArray[np.float64]
    reprojection_error: float
    num_correspondences: int
    coverage: float
    confidence: float
    per_point_errors: tuple[float, ...]
    camera_matrix: NDArray[np.float64]
    distortion_coeffs: NDArray[np.float64]
    image_size: tuple[int, int]


# ---------------------------------------------------------------------------
# Algorithm interface
# ---------------------------------------------------------------------------


class ProjectorCalibrationAlgorithm(ABC):
    """Reusable interface for projector calibration methods.

    Subclasses implement one structured light family:

    - Gray code (``GrayCodeProjectorCalibration`` — the MVP)
    - Phase shift
    - ArUco / checkerboard projection
    - LiDAR-assisted, AI-assisted (future)

    Implementations are pure vision algorithms: they hold no UI, event,
    or persistence concerns. The calibration framework orchestrates them
    through ``CalibrationStage`` pipeline stages.
    """

    @property
    @abstractmethod
    def method(self) -> CalibrationMethod:
        """The calibration method this algorithm implements."""

    @abstractmethod
    def build_sequence(self, resolution: tuple[int, int]) -> PatternSequence:
        """Build the ordered structured light pattern sequence.

        Args:
            resolution: Projector resolution ``(width, height)``.

        Returns:
            The pattern sequence in projection order.
        """

    @abstractmethod
    def decode(
        self,
        captures: Sequence[NDArray[np.uint8]],
        sequence: PatternSequence,
    ) -> CorrespondenceMap:
        """Decode captured frames into a dense correspondence map.

        Args:
            captures: One captured grayscale frame per pattern, in the
                sequence's projection order. Frames should be
                geometrically aligned (static camera + static surface).
            sequence: The pattern sequence that was projected.

        Returns:
            The dense camera-to-projector correspondence map.

        Raises:
            ProjectorCalibrationError: If the number of captures does
                not match the sequence.
        """

    @abstractmethod
    def calibrate(
        self,
        correspondences: CorrespondenceMap,
        camera: CalibratedCamera,
        surface: SurfacePlane,
        resolution: tuple[int, int],
    ) -> ProjectorCalibrationResult:
        """Compute projector intrinsics and pose.

        Each correspondence (camera pixel -> projector pixel) is
        triangulated by intersecting the camera ray with ``surface``,
        yielding a 3D point and its observed projector pixel. A robust
        solve then recovers ``K_proj`` and the projector pose.

        Args:
            correspondences: Decoded correspondences.
            camera: The calibrated observing camera.
            surface: The planar surface the patterns were projected on,
                in camera coordinates.
            resolution: Projector resolution ``(width, height)`` being
                calibrated.

        Returns:
            The projector calibration result.

        Raises:
            ProjectorCalibrationError: If calibration cannot be computed
                (e.g. too few valid correspondences).
        """

    def project_points(
        self,
        points_camera: NDArray[np.float64],
        result: ProjectorCalibrationResult,
    ) -> NDArray[np.float64]:
        """Project camera-frame 3D points into projector pixels.

        Applies the forward projector model::

            p_proj = K_proj @ (T_inv @ p_cam)

        where ``T_inv`` maps camera-frame points into the projector's
        local frame. Used for warp-mesh generation and surface-corner
        estimation.

        Args:
            points_camera: ``(N, 3)`` points in camera coordinates.
            result: The completed calibration.

        Returns:
            ``(N, 2)`` projector pixel coordinates.
        """
        if points_camera.ndim != 2 or points_camera.shape[1] != 3:
            raise ProjectorCalibrationError(
                f"points_camera must have shape (N, 3), got {points_camera.shape}"
            )

        transform_inv = np.linalg.inv(result.projector_pose)
        hom = np.column_stack((points_camera, np.ones(len(points_camera))))
        local = hom @ transform_inv.T  # camera frame -> projector frame
        projected = local[:, :3] @ result.projector_intrinsics.T
        with np.errstate(divide="ignore", invalid="ignore"):
            pixels = projected[:, :2] / projected[:, 2:3]
        return pixels
