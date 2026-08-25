"""Calibration domain model.

Captures the geometric relationship between:
- The physical object / surface (real world)
- The 3D digital model (virtual)
- The projector(s)
- The camera(s)

Phase 6.2: canonical domain is domain.calibration_session.CalibrationResult.
This module is retained for backward compatibility; new code should
import CalibrationResult from projectionai.domain.calibration_session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

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

    # -- Phase 6.2 compat: bridge to canonical domain --------------------------

    def to_canonical(self) -> Any:
        """Convert legacy domain result to canonical calibration_session.CalibrationResult."""
        import time as _time
        import uuid as _uuid

        import numpy as _np

        from projectionai.domain.calibration_session import (
            CalibrationMethod as _Method,
        )
        from projectionai.domain.calibration_session import (
            CalibrationResult as _Canonical,
        )

        # Use first projector if present, else identity
        if self.projectors:
            pc = self.projectors[0]
            # Derive intrinsics from FOV/resolution (same as calibration_to_warp_mesh)
            import math as _math

            if 0 < pc.fov_degrees < 180:
                fx = (pc.resolution_width * 0.5) / _math.tan(
                    _math.radians(pc.fov_degrees) * 0.5
                )
                fy = fx
            else:
                fx = fy = 1000.0
            cx = pc.resolution_width * 0.5
            cy = pc.resolution_height * 0.5
            k = _np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=_np.float64)
            mtx = pc.pose.as_matrix()
            # Canonical expects projector→camera. Compose with known camera pose if
            # available; otherwise record unknown frame and keep world pose as fallback
            # with explicit metadata flag (do not silently substitute).
            cam_pose_raw = self.metadata.get("camera_pose")
            if cam_pose_raw is None:
                cam_pose_raw = self.metadata.get("camera_pose_matrix")
            if cam_pose_raw is not None:
                try:
                    cam_mtx = _np.asarray(cam_pose_raw, dtype=_np.float64)
                    pose = _np.asarray(_np.linalg.inv(cam_mtx) @ mtx, dtype=_np.float64)
                    pose_frame = "camera"
                except Exception as exc:
                    raise ValueError(
                        f"Invalid camera_pose matrix for canonical conversion: {exc}"
                    ) from exc
            else:
                raise ValueError(
                    "Cannot convert legacy CalibrationResult to canonical: "
                    "camera pose unknown — provide metadata['camera_pose'] "
                    "(4x4 camera→world) or metadata['camera_pose_matrix'] to "
                    "compose projector→camera. World-frame pose is not a valid "
                    "canonical projector_pose (metadata pose_frame is not sufficient)."
                )
            res = (pc.resolution_width, pc.resolution_height)
            pid = pc.projector_id
        else:
            k = _np.eye(3, dtype=_np.float64)
            pose = _np.eye(4, dtype=_np.float64)
            pose_frame = "camera"
            res = (1920, 1080)
            pid = "projector_0"
        # Preserve original method if stored in metadata
        raw_method = self.metadata.get("method") or self.metadata.get(
            "calibration_method"
        )
        try:
            method = (
                _Method(str(raw_method)) if raw_method is not None else _Method.MANUAL
            )
        except ValueError:
            method = _Method.MANUAL
        meta = dict(self.metadata)
        if pose_frame == "world":
            meta["pose_frame"] = "world"
        return _Canonical(
            calibration_id=_uuid.uuid4().hex,
            sequence_id=str(self.metadata.get("sequence_id", _uuid.uuid4().hex)),
            method=method,
            projector_id=pid,
            camera_id=str(self.metadata.get("camera_id", "camera_0")),
            surface_id=str(self.metadata.get("surface_id", "")),
            projector_intrinsics=k,
            projector_pose=pose,
            projector_resolution=res,
            reprojection_error=float(self.reprojection_error),
            coverage=float(self.metadata.get("coverage", 0.0) or 0.0),  # type: ignore
            num_correspondences=int(self.metadata.get("num_correspondences", 0) or 0),  # type: ignore
            confidence=float(self.confidence),
            camera_matrix=self.camera_matrix,
            distortion_coeffs=self.distortion_coeffs,
            object_pose=self.object_pose,
            created_at=_time.time(),
            metadata=meta,
        )

    @staticmethod
    def from_canonical(canonical: Any) -> CalibrationResult:
        """Create legacy domain result from canonical.

        Preserves method, sequence_id, surface_id, coverage and
        num_correspondences via metadata for to_canonical() round-trip.
        Existing canonical.metadata values are retained. image_size,
        per_point_errors, warp_mesh and scale are not preserved.
        """

        pose = Pose.from_matrix(canonical.projector_pose)
        pc = ProjectorCalibration(
            projector_id=canonical.projector_id,
            pose=pose,
            resolution_width=canonical.projector_resolution[0],
            resolution_height=canonical.projector_resolution[1],
            confidence=canonical.confidence,
        )
        meta = dict(canonical.metadata)
        meta["method"] = (
            str(canonical.method.value)
            if hasattr(canonical.method, "value")
            else str(canonical.method)
        )
        meta["sequence_id"] = str(canonical.sequence_id)
        meta["surface_id"] = str(canonical.surface_id)
        meta["coverage"] = float(canonical.coverage)
        meta["num_correspondences"] = int(canonical.num_correspondences)
        return CalibrationResult(
            object_pose=canonical.object_pose,
            projectors=(pc,),
            reprojection_error=canonical.reprojection_error,
            confidence=canonical.confidence,
            camera_matrix=canonical.camera_matrix,
            distortion_coeffs=canonical.distortion_coeffs,
            metadata=meta,
        )
