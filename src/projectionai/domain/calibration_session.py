"""Canonical calibration domain — typed session lifecycle.

Framework-independent. No Qt, no OpenCV, no ModernGL, no pybind11.

Reuses:
- domain.geometry.Pose
- domain.warp_mesh.WarpMesh
- numpy for dense arrays (buffer-protocol friendly for future SHM/native)

Does NOT import:
- services/camera
- services/projector_calibration
- calibration/types (to keep domain → calibration = 0)
- infrastructure

All calibration/types and services types adapt TO this canonical domain.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.geometry import Pose
from projectionai.domain.warp_mesh import WarpMesh

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums — canonical
# ---------------------------------------------------------------------------


class CalibrationMethod(StrEnum):
    """Canonical calibration method (domain-owned)."""

    MANUAL = "manual"
    ARUCO = "aruco"
    CHESSBOARD = "chessboard"
    STRUCTURED_LIGHT = "structured_light"
    GRAY_CODE = "gray_code"
    PHASE_SHIFT = "phase_shift"
    LIDAR = "lidar"
    AI_ASSISTED = "ai_assisted"
    CUSTOM = "custom"


class CalibrationSessionStatus(StrEnum):
    """Typed lifecycle for the domain CalibrationSession.

    Reuses values from previous CalibrationStatus where possible.
    New explicit states:
    - CREATED  (alias IDLE)
    - CAPTURING (alias ACQUIRING)
    - SOLVING  (alias PROCESSING sub-phase)
    """

    CREATED = "created"
    IDLE = "created"  # alias for backward compat: IDLE == CREATED
    PREPARING = "preparing"
    ACQUIRING = "capturing"  # alias for CAPTURING (legacy value "acquiring" mapped via _missing_)
    CAPTURING = "capturing"
    PROCESSING = "processing"
    SOLVING = "solving"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def _missing_(cls, value: object) -> CalibrationSessionStatus | None:
        if value == "acquiring":
            return cls.CAPTURING
        return None


class PatternAxis(StrEnum):
    """Axis a pattern encodes."""

    COLUMN = "column"
    ROW = "row"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _array_eq(a: NDArray[Any] | None, b: NDArray[Any] | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


# ---------------------------------------------------------------------------
# CalibrationPattern
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CalibrationPattern:
    """Single structured-light pattern (domain)."""

    pattern_id: int
    sequence_id: str
    axis: PatternAxis
    bit_index: int
    bit_value: int
    image: NDArray[np.uint8]  # (H, W) grayscale
    width: int
    height: int

    def __post_init__(self) -> None:
        if not self.sequence_id:
            raise ValueError("sequence_id must be non-empty")
        if self.pattern_id < 0:
            raise ValueError(f"pattern_id must be >=0, got {self.pattern_id}")
        if self.bit_index < 0:
            raise ValueError(f"bit_index must be >=0, got {self.bit_index}")
        if self.bit_value not in (0, 1):
            raise ValueError(f"bit_value must be 0 or 1, got {self.bit_value}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"resolution must be positive, got {self.width}x{self.height}"
            )
        if self.image.ndim != 2:
            raise ValueError(f"pattern image must be 2D, got {self.image.ndim}D")
        if self.image.shape != (self.height, self.width):
            raise ValueError(
                f"pattern image shape {self.image.shape} != ({self.height},{self.width})"
            )
        if self.image.dtype != np.uint8:
            raise ValueError(f"pattern image must be uint8, got {self.image.dtype}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationPattern):
            return NotImplemented
        return (
            self.pattern_id == other.pattern_id
            and self.sequence_id == other.sequence_id
            and self.axis == other.axis
            and self.bit_index == other.bit_index
            and self.bit_value == other.bit_value
            and self.width == other.width
            and self.height == other.height
            and _array_eq(self.image, other.image)
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# CalibrationSequence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CalibrationSequence:
    """Ordered sequence of patterns for one projector resolution."""

    sequence_id: str
    method: CalibrationMethod
    patterns: tuple[CalibrationPattern, ...]
    width: int
    height: int
    bits_x: int
    bits_y: int
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.sequence_id:
            raise ValueError("sequence_id must be non-empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"resolution must be positive, got {self.width}x{self.height}"
            )
        if self.bits_x < 0 or self.bits_y < 0:
            raise ValueError(
                f"bit counts must be >=0, got x={self.bits_x} y={self.bits_y}"
            )
        if not self.patterns:
            raise ValueError("sequence must contain at least one pattern")
        if len(self.patterns) != self.bits_x + self.bits_y:
            raise ValueError(
                f"sequence has {len(self.patterns)} patterns but bits_x+bits_y={self.bits_x + self.bits_y}"
            )
        seen = set()
        for p in self.patterns:
            if p.sequence_id != self.sequence_id:
                raise ValueError(
                    f"pattern {p.pattern_id} sequence_id {p.sequence_id!r} != sequence {self.sequence_id!r}"
                )
            if p.width != self.width or p.height != self.height:
                raise ValueError(f"pattern {p.pattern_id} resolution mismatch")
            if p.pattern_id in seen:
                raise ValueError(f"duplicate pattern_id {p.pattern_id}")
            seen.add(p.pattern_id)

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.width, self.height)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationSequence):
            return NotImplemented
        return (
            self.sequence_id == other.sequence_id
            and self.method == other.method
            and self.patterns == other.patterns
            and self.width == other.width
            and self.height == other.height
            and self.bits_x == other.bits_x
            and self.bits_y == other.bits_y
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "method": self.method.value,
            "width": self.width,
            "height": self.height,
            "bits_x": self.bits_x,
            "bits_y": self.bits_y,
            "created_at": self.created_at,
            "patterns": [
                {
                    "pattern_id": p.pattern_id,
                    "axis": p.axis.value,
                    "bit_index": p.bit_index,
                    "bit_value": p.bit_value,
                    "image": p.image.tolist(),
                }
                for p in self.patterns
            ],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CalibrationSequence:
        sid = str(data["sequence_id"])
        patterns = tuple(
            CalibrationPattern(
                pattern_id=int(p["pattern_id"]),
                sequence_id=sid,
                axis=PatternAxis(str(p["axis"])),
                bit_index=int(p["bit_index"]),
                bit_value=int(p["bit_value"]),
                image=np.array(p["image"], dtype=np.uint8),
                width=int(data["width"]),
                height=int(data["height"]),
            )
            for p in data.get("patterns", [])
        )
        return CalibrationSequence(
            sequence_id=sid,
            method=CalibrationMethod(str(data.get("method", "gray_code"))),
            patterns=patterns,
            width=int(data["width"]),
            height=int(data["height"]),
            bits_x=int(data["bits_x"]),
            bits_y=int(data["bits_y"]),
            created_at=float(data.get("created_at", time.time())),
        )


# ---------------------------------------------------------------------------
# CameraCapture
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CameraCapture:
    """Single camera frame with sync metadata (domain).

    Mirrors services/camera.Frame but adds typed sync fields.
    Image ownership: borrowed view of SHM in future; domain holds reference.
    """

    image: NDArray[np.uint8]  # (H,W,3) RGB
    timestamp: float  # monotonic seconds
    timestamp_ns: int  # monotonic nanoseconds
    camera_id: str
    frame_number: int
    sequence_id: str  # which sequence this capture belongs to ("" if none)
    pattern_id: int  # which pattern was displayed (-1 if none/unknown)
    projector_state: str  # pattern_N / black / white / unknown
    presentation_timestamp_ns: int | None = None
    capture_latency_ms: float | None = None
    exposure_ms: float | None = None
    gain: float | None = None

    def __post_init__(self) -> None:
        if self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError(f"image must be (H,W,3) RGB, got {self.image.shape}")
        if self.image.dtype != np.uint8:
            raise ValueError(f"image must be uint8, got {self.image.dtype}")
        if not self.camera_id:
            raise ValueError("camera_id must be non-empty")
        if self.frame_number < 0:
            raise ValueError(f"frame_number must be >=0, got {self.frame_number}")
        if self.pattern_id < -1:
            raise ValueError(f"pattern_id must be >=-1, got {self.pattern_id}")
        if self.timestamp_ns < 0:
            raise ValueError(f"timestamp_ns must be >=0, got {self.timestamp_ns}")
        if (
            self.presentation_timestamp_ns is not None
            and self.presentation_timestamp_ns < 0
        ):
            raise ValueError(
                f"presentation_timestamp_ns must be >=0, got {self.presentation_timestamp_ns}"
            )
        if self.capture_latency_ms is not None and not (
            -1.0 <= self.capture_latency_ms <= 100000.0
        ):
            raise ValueError(
                f"capture_latency_ms out of range, got {self.capture_latency_ms}"
            )

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CameraCapture):
            return NotImplemented
        return (
            _array_eq(self.image, other.image)
            and self.timestamp == other.timestamp
            and self.timestamp_ns == other.timestamp_ns
            and self.camera_id == other.camera_id
            and self.frame_number == other.frame_number
            and self.sequence_id == other.sequence_id
            and self.pattern_id == other.pattern_id
            and self.projector_state == other.projector_state
            and self.presentation_timestamp_ns == other.presentation_timestamp_ns
            and self.capture_latency_ms == other.capture_latency_ms
            and self.exposure_ms == other.exposure_ms
            and self.gain == other.gain
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# CalibrationFrame
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CalibrationFrame:
    """Paired capture + pattern with invariant checks."""

    capture: CameraCapture
    pattern: CalibrationPattern

    def __post_init__(self) -> None:
        if self.capture.sequence_id != self.pattern.sequence_id:
            raise ValueError(
                f"sequence_id mismatch: capture {self.capture.sequence_id!r} "
                f"!= pattern {self.pattern.sequence_id!r}"
            )
        if self.capture.pattern_id != self.pattern.pattern_id:
            raise ValueError(
                f"pattern_id mismatch: capture {self.capture.pattern_id} "
                f"!= pattern {self.pattern.pattern_id}"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationFrame):
            return NotImplemented
        return self.capture == other.capture and self.pattern == other.pattern

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# CorrespondenceSet
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CorrespondenceSet:
    """Dense camera→projector correspondence (domain)."""

    projector_x: NDArray[np.float32]  # (H,W)
    projector_y: NDArray[np.float32]  # (H,W)
    mask: NDArray[np.bool_]  # (H,W) valid
    image_size: tuple[int, int]  # (W,H) camera
    projector_resolution: tuple[int, int]  # (W,H) projector
    sequence_id: str
    threshold: int = 127
    valid_ratio: float = 0.0

    def __post_init__(self) -> None:
        w, h = self.image_size
        pw, ph = self.projector_resolution
        if w <= 0 or h <= 0:
            raise ValueError(f"image_size must be positive, got {self.image_size}")
        if pw <= 0 or ph <= 0:
            raise ValueError(
                f"projector_resolution must be positive, got {self.projector_resolution}"
            )
        if not self.sequence_id:
            raise ValueError("sequence_id must be non-empty")
        for name, arr in (
            ("projector_x", self.projector_x),
            ("projector_y", self.projector_y),
            ("mask", self.mask),
        ):
            if arr.shape != (h, w):
                raise ValueError(f"{name} shape {arr.shape} != ({h},{w})")
        if self.mask.dtype != np.bool_:
            raise ValueError(f"mask must be bool, got {self.mask.dtype}")
        if not (0.0 <= self.valid_ratio <= 1.0):
            raise ValueError(f"valid_ratio must be in [0,1], got {self.valid_ratio}")

    @property
    def num_correspondences(self) -> int:
        return int(np.count_nonzero(self.mask))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CorrespondenceSet):
            return NotImplemented
        return (
            _array_eq(self.projector_x, other.projector_x)
            and _array_eq(self.projector_y, other.projector_y)
            and _array_eq(self.mask, other.mask)
            and self.image_size == other.image_size
            and self.projector_resolution == other.projector_resolution
            and self.sequence_id == other.sequence_id
            and self.threshold == other.threshold
            and self.valid_ratio == other.valid_ratio
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# ReconstructionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class ReconstructionResult:
    """Triangulated 3D points in camera frame (domain)."""

    points_camera: NDArray[np.float64]  # (N,3)
    projector_pixels: NDArray[np.float64]  # (N,2)
    sequence_id: str
    normals: NDArray[np.float64] | None = None  # (N,3)
    method: str = "plane_triangulation"

    def __post_init__(self) -> None:
        if not self.sequence_id:
            raise ValueError("sequence_id must be non-empty")
        if self.points_camera.ndim != 2 or self.points_camera.shape[1] != 3:
            raise ValueError(
                f"points_camera must be (N,3), got {self.points_camera.shape}"
            )
        if self.projector_pixels.ndim != 2 or self.projector_pixels.shape[1] != 2:
            raise ValueError(
                f"projector_pixels must be (N,2), got {self.projector_pixels.shape}"
            )
        if len(self.points_camera) != len(self.projector_pixels):
            raise ValueError(
                f"points/projector len mismatch {len(self.points_camera)} != {len(self.projector_pixels)}"
            )
        if self.normals is not None and self.normals.shape != self.points_camera.shape:
            raise ValueError(
                f"normals shape {self.normals.shape} != {self.points_camera.shape}"
            )
        if len(self.points_camera) == 0:
            raise ValueError("ReconstructionResult must have at least one point")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ReconstructionResult):
            return NotImplemented
        return (
            _array_eq(self.points_camera, other.points_camera)
            and _array_eq(self.projector_pixels, other.projector_pixels)
            and self.sequence_id == other.sequence_id
            and _array_eq(self.normals, other.normals)
            and self.method == other.method
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Canonical CalibrationResult (domain)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class CalibrationResult:
    """One canonical production calibration result (domain, immutable).

    For multi-orientation calibrations, ``calibration_sequence_ids`` lists
    every sequence_id / orientation that contributed. ``sequence_id`` remains
    the primary (first) orientation for backward compatibility.
    """

    calibration_id: str
    sequence_id: str
    method: CalibrationMethod
    projector_id: str
    camera_id: str
    surface_id: str
    projector_intrinsics: NDArray[np.float64]  # 3x3
    projector_pose: NDArray[np.float64]  # 4x4 projector→camera
    projector_resolution: tuple[int, int]  # (W,H)
    reprojection_error: float
    coverage: float  # valid projected pixels / projector area, see solver
    num_correspondences: int
    confidence: float
    calibration_sequence_ids: tuple[str, ...] = ()
    per_point_errors: tuple[float, ...] = ()
    camera_matrix: NDArray[np.float64] | None = None  # 3x3 echo
    distortion_coeffs: NDArray[np.float64] | None = None  # (5,)
    image_size: tuple[int, int] | None = None  # (W,H) camera
    warp_mesh: WarpMesh | None = None
    object_pose: Pose | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.calibration_id:
            raise ValueError("calibration_id must be non-empty")
        if not self.sequence_id:
            raise ValueError("sequence_id must be non-empty")
        if not self.projector_id:
            raise ValueError("projector_id must be non-empty")
        if not self.camera_id:
            raise ValueError("camera_id must be non-empty")
        if self.projector_intrinsics.shape != (3, 3):
            raise ValueError(
                f"projector_intrinsics must be 3x3, got {self.projector_intrinsics.shape}"
            )
        if self.projector_pose.shape != (4, 4):
            raise ValueError(
                f"projector_pose must be 4x4, got {self.projector_pose.shape}"
            )
        pw, ph = self.projector_resolution
        if pw <= 0 or ph <= 0:
            raise ValueError(
                f"projector_resolution must be positive, got {self.projector_resolution}"
            )
        if not np.isfinite(self.reprojection_error) or self.reprojection_error < 0:
            raise ValueError(
                f"reprojection_error must be finite >=0, got {self.reprojection_error}"
            )
        if not (0.0 <= self.coverage <= 1.0) or not np.isfinite(self.coverage):
            raise ValueError(f"coverage must be in [0,1], got {self.coverage}")
        if self.num_correspondences < 0:
            raise ValueError(
                f"num_correspondences must be >=0, got {self.num_correspondences}"
            )
        if not (0.0 <= self.confidence <= 1.0) or not np.isfinite(self.confidence):
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
        if self.camera_matrix is not None and self.camera_matrix.shape != (3, 3):
            raise ValueError(
                f"camera_matrix must be 3x3, got {self.camera_matrix.shape}"
            )
        if self.distortion_coeffs is not None and self.distortion_coeffs.shape not in (
            (5,),
            (4,),
            (8,),
        ):
            # allow 4/5/8 for compat
            raise ValueError(
                f"distortion_coeffs shape invalid, got {self.distortion_coeffs.shape}"
            )
        # multi-orientation: if provided, sequence_id must be first and all ids non-empty
        if self.calibration_sequence_ids:
            if self.sequence_id not in self.calibration_sequence_ids:
                raise ValueError(
                    f"sequence_id {self.sequence_id!r} must be in calibration_sequence_ids {self.calibration_sequence_ids!r}"
                )
            for sid in self.calibration_sequence_ids:
                if not sid:
                    raise ValueError(
                        "calibration_sequence_ids must not contain empty strings"
                    )
            if len(set(self.calibration_sequence_ids)) != len(
                self.calibration_sequence_ids
            ):
                raise ValueError(
                    f"calibration_sequence_ids must be unique, got {self.calibration_sequence_ids!r}"
                )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationResult):
            return NotImplemented
        return (
            self.calibration_id == other.calibration_id
            and self.sequence_id == other.sequence_id
            and self.method == other.method
            and self.projector_id == other.projector_id
            and self.camera_id == other.camera_id
            and self.surface_id == other.surface_id
            and _array_eq(self.projector_intrinsics, other.projector_intrinsics)
            and _array_eq(self.projector_pose, other.projector_pose)
            and self.projector_resolution == other.projector_resolution
            and self.reprojection_error == other.reprojection_error
            and self.coverage == other.coverage
            and self.num_correspondences == other.num_correspondences
            and self.confidence == other.confidence
            and self.calibration_sequence_ids == other.calibration_sequence_ids
            and self.per_point_errors == other.per_point_errors
            and _array_eq(self.camera_matrix, other.camera_matrix)
            and _array_eq(self.distortion_coeffs, other.distortion_coeffs)
            and self.image_size == other.image_size
            and self.warp_mesh == other.warp_mesh
            and self.object_pose == other.object_pose
            and self.metadata == other.metadata
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]

    @property
    def orientation_ids(self) -> tuple[str, ...]:
        """Alias for calibration_sequence_ids — domain-consistent name."""
        return self.calibration_sequence_ids

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (arrays as lists)."""
        return {
            "calibration_id": self.calibration_id,
            "sequence_id": self.sequence_id,
            "method": self.method.value,
            "projector_id": self.projector_id,
            "camera_id": self.camera_id,
            "surface_id": self.surface_id,
            "projector_intrinsics": self.projector_intrinsics.tolist(),
            "projector_pose": self.projector_pose.tolist(),
            "projector_resolution": list(self.projector_resolution),
            "reprojection_error": self.reprojection_error,
            "coverage": self.coverage,
            "num_correspondences": self.num_correspondences,
            "confidence": self.confidence,
            "calibration_sequence_ids": list(self.calibration_sequence_ids),
            "per_point_errors": list(self.per_point_errors),
            "camera_matrix": self.camera_matrix.tolist()
            if self.camera_matrix is not None
            else None,
            "distortion_coeffs": self.distortion_coeffs.tolist()
            if self.distortion_coeffs is not None
            else None,
            "image_size": list(self.image_size)
            if self.image_size is not None
            else None,
            "warp_mesh": self.warp_mesh.to_dict()
            if self.warp_mesh is not None
            else None,
            "object_pose": {
                "position": {
                    "x": self.object_pose.position.x,
                    "y": self.object_pose.position.y,
                    "z": self.object_pose.position.z,
                },
                "rotation": list(self.object_pose.rotation),
            }
            if self.object_pose is not None
            else None,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CalibrationResult:
        """Reconstruct from to_dict output. Fail clearly if impossible."""
        try:
            warp = None
            if data.get("warp_mesh") is not None:
                warp = WarpMesh.from_dict(data["warp_mesh"])
            obj_pose = None
            if data.get("object_pose") is not None:
                from projectionai.domain.geometry import Vec3

                op = data["object_pose"]
                pos = op.get("position", {})
                obj_pose = Pose(
                    position=Vec3(
                        float(pos.get("x", 0)),
                        float(pos.get("y", 0)),
                        float(pos.get("z", 0)),
                    ),
                    rotation=tuple(op.get("rotation", (1.0, 0.0, 0.0, 0.0))),
                )
            return CalibrationResult(
                calibration_id=str(data["calibration_id"]),
                sequence_id=str(data["sequence_id"]),
                method=CalibrationMethod(str(data["method"])),
                projector_id=str(data["projector_id"]),
                camera_id=str(data["camera_id"]),
                surface_id=str(data.get("surface_id", "")),
                projector_intrinsics=np.array(
                    data["projector_intrinsics"], dtype=np.float64
                ),
                projector_pose=np.array(data["projector_pose"], dtype=np.float64),
                projector_resolution=(
                    int(data["projector_resolution"][0]),
                    int(data["projector_resolution"][1]),
                ),
                reprojection_error=float(data["reprojection_error"]),
                coverage=float(data["coverage"]),
                num_correspondences=int(data["num_correspondences"]),
                confidence=float(data["confidence"]),
                per_point_errors=tuple(
                    float(x) for x in data.get("per_point_errors", ())
                ),
                camera_matrix=np.array(data["camera_matrix"], dtype=np.float64)
                if data.get("camera_matrix") is not None
                else None,
                distortion_coeffs=np.array(data["distortion_coeffs"], dtype=np.float64)
                if data.get("distortion_coeffs") is not None
                else None,
                image_size=(int(data["image_size"][0]), int(data["image_size"][1]))
                if data.get("image_size") is not None
                else None,
                warp_mesh=warp,
                object_pose=obj_pose,
                created_at=float(data.get("created_at", time.time())),
                metadata=dict(data.get("metadata", {})),
                calibration_sequence_ids=tuple(
                    data.get("calibration_sequence_ids")
                    or data.get("orientation_ids")
                    or []
                ),
            )
        except Exception as exc:
            raise ValueError(f"Cannot load CalibrationResult: {exc}") from exc

    # --- Compat adapters ---------------------------------------------------

    def to_legacy_domain(self) -> Any:
        """Adapt to old domain/calibration.CalibrationResult for bridge compat."""
        from projectionai.domain.calibration import (  # local import to avoid cycle
            CalibrationResult as LegacyDomainResult,
        )
        from projectionai.domain.calibration import (
            ProjectorCalibration,
        )

        pc = ProjectorCalibration(
            projector_id=self.projector_id,
            pose=_pose_from_matrix(self.projector_pose),
            fov_degrees=60.0,
            resolution_width=self.projector_resolution[0],
            resolution_height=self.projector_resolution[1],
            confidence=self.confidence,
        )
        return LegacyDomainResult(
            object_pose=self.object_pose,
            projectors=(pc,),
            reprojection_error=self.reprojection_error,
            confidence=self.confidence,
            camera_matrix=self.camera_matrix,
            distortion_coeffs=self.distortion_coeffs,
            metadata=dict(self.metadata),
        )


def _rotation_to_quat(
    r: NDArray[np.float64],
) -> tuple[float, float, float, float] | None:
    """Extract a (w, x, y, z) quaternion from a 3x3 rotation matrix.

    Pure NumPy (Shepperd's method), no scipy. Returns None when the matrix
    is not a valid rotation (non-orthonormal or negative determinant).
    """
    if r.shape != (3, 3) or not np.all(np.isfinite(r)):
        return None
    # Orthonormality + proper-rotation checks.
    if not np.allclose(r @ r.T, np.eye(3), atol=1e-6):
        return None
    if np.linalg.det(r) < 0.0:
        return None

    trace = float(np.trace(r))
    if trace > 0.0:
        s = float(np.sqrt(trace + 1.0)) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = float(np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = float(np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = float(np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s

    # Normalize.
    n = float(np.sqrt(w * w + x * x + y * y + z * z))
    if n == 0.0 or not np.isfinite(n):
        return None
    return (float(w) / n, float(x) / n, float(y) / n, float(z) / n)


def _pose_from_matrix(m: NDArray[np.float64]) -> Pose:
    """Minimal Pose from a 4x4 matrix using public Pose.from_matrix.

    Preserved for backward compatibility; new code should use Pose.from_matrix.
    """
    return Pose.from_matrix(m)


# ---------------------------------------------------------------------------
# Domain CalibrationSession
# ---------------------------------------------------------------------------


_ALLOWED_TRANSITIONS: dict[CalibrationSessionStatus, set[CalibrationSessionStatus]] = {
    CalibrationSessionStatus.CREATED: {
        CalibrationSessionStatus.PREPARING,
        CalibrationSessionStatus.FAILED,
        CalibrationSessionStatus.CANCELLED,
    },
    CalibrationSessionStatus.PREPARING: {
        CalibrationSessionStatus.CAPTURING,
        CalibrationSessionStatus.FAILED,
        CalibrationSessionStatus.CANCELLED,
    },
    CalibrationSessionStatus.CAPTURING: {
        CalibrationSessionStatus.PROCESSING,
        CalibrationSessionStatus.FAILED,
        CalibrationSessionStatus.CANCELLED,
    },
    CalibrationSessionStatus.PROCESSING: {
        CalibrationSessionStatus.SOLVING,
        CalibrationSessionStatus.VALIDATING,
        CalibrationSessionStatus.COMPLETED,
        CalibrationSessionStatus.FAILED,
        CalibrationSessionStatus.CANCELLED,
    },
    CalibrationSessionStatus.SOLVING: {
        CalibrationSessionStatus.VALIDATING,
        CalibrationSessionStatus.COMPLETED,
        CalibrationSessionStatus.FAILED,
        CalibrationSessionStatus.CANCELLED,
    },
    CalibrationSessionStatus.VALIDATING: {
        CalibrationSessionStatus.COMPLETED,
        CalibrationSessionStatus.FAILED,
        CalibrationSessionStatus.CANCELLED,
    },
    CalibrationSessionStatus.COMPLETED: set(),
    CalibrationSessionStatus.FAILED: set(),
    CalibrationSessionStatus.CANCELLED: set(),
}


@dataclass
class CalibrationSession:
    """Domain entity — typed session state (not the runner)."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Calibration Session"
    status: CalibrationSessionStatus = CalibrationSessionStatus.CREATED
    sequence: CalibrationSequence | None = None
    frames: tuple[CalibrationFrame, ...] = ()
    correspondences: CorrespondenceSet | None = None
    reconstruction: ReconstructionResult | None = None
    result: CalibrationResult | None = None
    projector_id: str = ""
    camera_id: str = ""
    surface_id: str = ""
    method: CalibrationMethod = CalibrationMethod.GRAY_CODE
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def transition(self, new_status: CalibrationSessionStatus) -> None:
        """Validate and apply status transition."""
        allowed = _ALLOWED_TRANSITIONS.get(self.status, set())
        # allow idempotent
        if new_status == self.status:
            return
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition {self.status.value} → {new_status.value}"
            )
        object.__setattr__(self, "status", new_status)
        if (
            new_status
            in (
                CalibrationSessionStatus.COMPLETED,
                CalibrationSessionStatus.FAILED,
                CalibrationSessionStatus.CANCELLED,
            )
            and self.completed_at is None
        ):
            object.__setattr__(self, "completed_at", time.time())

    def add_frame(self, frame: CalibrationFrame) -> None:
        if self.sequence is None:
            raise ValueError("sequence must be set before adding frames")
        if frame.capture.sequence_id != self.sequence.sequence_id:
            raise ValueError("frame sequence_id mismatch")
        object.__setattr__(self, "frames", (*self.frames, frame))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session to a JSON-compatible dict (partial).

        Note: this is NOT a full round trip. Frames, reconstruction, and the
        full correspondence arrays (projector_x/projector_y/mask) are not
        persisted; only the correspondence *summary* (sequence_id, image_size,
        projector_resolution, threshold, valid_ratio, num_correspondences) is
        stored. A session reloaded via :meth:`from_dict` therefore has no
        frames, no reconstruction, and empty correspondence state.
        """
        return {
            "session_id": self.session_id,
            "name": self.name,
            "status": self.status.value,
            "method": self.method.value,
            "projector_id": self.projector_id,
            "camera_id": self.camera_id,
            "surface_id": self.surface_id,
            "sequence": self.sequence.to_dict() if self.sequence else None,
            "correspondences": {
                "sequence_id": self.correspondences.sequence_id,
                "image_size": list(self.correspondences.image_size),
                "projector_resolution": list(self.correspondences.projector_resolution),
                "threshold": self.correspondences.threshold,
                "valid_ratio": self.correspondences.valid_ratio,
                "num_correspondences": self.correspondences.num_correspondences,
            }
            if self.correspondences
            else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CalibrationSession:
        """Reconstruct a session from a dict produced by :meth:`to_dict` (partial).

        Note: this is NOT a full round trip. Frames, reconstruction, and the
        full correspondence arrays (projector_x/projector_y/mask) are not
        restored — only correspondence *summary* data is available, and the
        session is rebuilt with empty frames and no correspondence/reconstruction
        state. Re-running capture is required to recover those.
        """
        seq = None
        if data.get("sequence") is not None:
            seq = CalibrationSequence.from_dict(data["sequence"])
        res = None
        if data.get("result") is not None:
            res = CalibrationResult.from_dict(data["result"])
        return CalibrationSession(
            session_id=str(data["session_id"]),
            name=str(data.get("name", "Calibration Session")),
            status=CalibrationSessionStatus(str(data.get("status", "created"))),
            sequence=seq,
            frames=(),
            correspondences=None,
            reconstruction=None,
            result=res,
            projector_id=str(data.get("projector_id", "")),
            camera_id=str(data.get("camera_id", "")),
            surface_id=str(data.get("surface_id", "")),
            method=CalibrationMethod(str(data.get("method", "gray_code"))),
            created_at=float(data.get("created_at", time.time())),
            completed_at=data.get("completed_at"),
            errors=tuple(data.get("errors", ())),
            warnings=tuple(data.get("warnings", ())),
        )
