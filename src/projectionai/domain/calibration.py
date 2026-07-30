"""Calibration domain model.

Captures the geometric relationship between:
- The physical object / surface (real world)
- The 3D digital model (virtual)
- The projector(s)
- The camera(s)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.geometry import Pose


@dataclass(frozen=True)
class CalibrationPoint:
    """A single correspondence between a 2D image point and a 3D model point."""

    image_x: float
    image_y: float
    world_x: float
    world_y: float
    world_z: float
    confidence: float = 1.0
    label: str = ""


def _array_eq(a: NDArray[np.float64] | None, b: NDArray[np.float64] | None) -> bool:
    """Compare two optional NumPy arrays with ``np.array_equal``."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


@dataclass(frozen=True, eq=False)
class ProjectorCalibration:
    """Calibration data for a single projector."""

    projector_id: str
    pose: Pose  # Projector pose in world coordinates
    fov_degrees: float = 60.0
    resolution_width: int = 1920
    resolution_height: int = 1080
    keystone_matrix: NDArray[np.float64] | None = None  # 3x3 perspective transform
    warp_mesh: NDArray[np.float64] | None = None  # (H, W, 2) per-pixel warp field

    confidence: float = 1.0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectorCalibration):
            return NotImplemented
        return (
            self.projector_id == other.projector_id
            and self.pose == other.pose
            and self.fov_degrees == other.fov_degrees
            and self.resolution_width == other.resolution_width
            and self.resolution_height == other.resolution_height
            and self.confidence == other.confidence
            and _array_eq(self.keystone_matrix, other.keystone_matrix)
            and _array_eq(self.warp_mesh, other.warp_mesh)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


@dataclass(frozen=True, eq=False)
class CalibrationResult:
    """Complete calibration result for a scene.

    Combines camera calibration, projector calibration, and the
    object-to-world transform.
    """

    object_pose: Pose | None = None  # Object pose in world coordinates
    projectors: tuple[ProjectorCalibration, ...] = ()

    # Object-space scale (meters per unit)
    scale: float = 1.0

    # Quality metrics
    reprojection_error: float = 0.0  # RMS reprojection error in pixels
    confidence: float = 1.0

    # Intrinsic calibration used
    camera_matrix: NDArray[np.float64] | None = None
    distortion_coeffs: NDArray[np.float64] | None = None

    metadata: dict[str, object] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationResult):
            return NotImplemented
        return (
            self.object_pose == other.object_pose
            and self.projectors == other.projectors
            and self.scale == other.scale
            and self.reprojection_error == other.reprojection_error
            and self.confidence == other.confidence
            and self.metadata == other.metadata
            and _array_eq(self.camera_matrix, other.camera_matrix)
            and _array_eq(self.distortion_coeffs, other.distortion_coeffs)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]
