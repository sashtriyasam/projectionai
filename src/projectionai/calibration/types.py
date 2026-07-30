"""Calibration types — shared enums and data classes.

All calibration components import from here to avoid circular dependencies.
Designed for multi-projector, multi-camera, multi-surface from day one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CalibrationStatus(StrEnum):
    """Lifecycle state of a calibration session."""

    IDLE = "idle"
    PREPARING = "preparing"
    ACQUIRING = "acquiring"
    PROCESSING = "processing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CalibrationMethod(StrEnum):
    """Supported calibration techniques.

    Each value represents a family of algorithms. New methods can be added
    without changing the pipeline architecture.
    """

    MANUAL = "manual"
    ARUCO = "aruco"
    CHESSBOARD = "chessboard"
    STRUCTURED_LIGHT = "structured_light"
    GRAY_CODE = "gray_code"
    LIDAR = "lidar"
    AI_ASSISTED = "ai_assisted"
    CUSTOM = "custom"


class CalibrationStageType(StrEnum):
    """Well-known pipeline stage identifiers.

    Algorithms implement these stages. The pipeline orchestrates their
    execution order but does not contain algorithm logic.
    """

    INPUT_ACQUISITION = "input_acquisition"
    FEATURE_DETECTION = "feature_detection"
    CORRESPONDENCE_MATCHING = "correspondence_matching"
    POSE_ESTIMATION = "pose_estimation"
    WARP_GENERATION = "warp_generation"
    VALIDATION = "validation"
    EXPORT = "export"


class ProjectionType(StrEnum):
    """Type of projection surface."""

    FLAT = "flat"
    CYLINDRICAL = "cylindrical"
    SPHERICAL = "spherical"
    DOME = "dome"
    IRREGULAR = "irregular"
    CORNER = "corner"
    CUSTOM = "custom"


class LensType(StrEnum):
    """Projector lens type — affects distortion model."""

    STANDARD = "standard"
    WIDE_ANGLE = "wide_angle"
    ULTRA_SHORT_THROW = "ultra_short_throw"
    ZOOM = "zoom"
    FISHEYE = "fisheye"
    CUSTOM = "custom"


class WarpMode(StrEnum):
    """Type of warp mesh used for projection mapping."""

    BEZIER = "bezier"
    BICUBIC = "bicubic"
    PERSPECTIVE = "perspective"
    GRID_2D = "grid_2d"
    GRID_3D = "grid_3d"
    CUSTOM = "custom"


class MultiProjectorBlendMode(StrEnum):
    """Edge blending strategy for overlapping projections."""

    ALPHA_BLEND = "alpha_blend"
    LINEAR = "linear"
    GAMMA_CORRECT = "gamma_correct"
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Geometry data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0


@dataclass(frozen=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class Mat4x4:
    """4x4 transformation matrix stored as 16 floats (column-major)."""

    data: tuple[float, ...] = field(
        default_factory=lambda: (
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
        )
    )

    @staticmethod
    def identity() -> Mat4x4:
        return Mat4x4()


# ---------------------------------------------------------------------------
# Calibration data containers
# ---------------------------------------------------------------------------


@dataclass
class CalibrationData:
    """Container for all data captured or computed during calibration.

    This is the single source of truth for a calibration result — it holds
    every transform, warp mesh, error metric, and piece of metadata.
    """

    # Transforms
    projector_pose: dict[str, Any] = field(default_factory=dict)
    camera_pose: dict[str, Any] = field(default_factory=dict)
    surface_pose: dict[str, Any] = field(default_factory=dict)

    # Warp mesh
    warp_mesh: dict[str, Any] = field(default_factory=dict)
    control_points: dict[str, list[Vec2]] = field(default_factory=dict)

    # Confidence and error
    confidence: float = 0.0
    reprojection_error: float = 0.0
    residuals: list[float] = field(default_factory=list)

    # Metadata
    method: CalibrationMethod = CalibrationMethod.MANUAL
    timestamp: str = ""
    duration_ms: float = 0.0
    num_samples: int = 0
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalibrationResult:
    """Outcome of a completed calibration session.

    Contains the final data plus quality metrics and validation results.
    """

    success: bool = False
    data: CalibrationData | None = None
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    error_message: str = ""


@dataclass
class CalibrationState:
    """Mutable state of an active calibration session.

    Tracks progress, current stage, and intermediate data during the
    calibration workflow.
    """

    status: CalibrationStatus = CalibrationStatus.IDLE
    current_stage: str = ""
    progress: float = 0.0
    status_text: str = ""
    current_method: CalibrationMethod = CalibrationMethod.MANUAL
    data: CalibrationData | None = None
    intermediate_results: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Multi-entity tracking
    active_projector_id: str = ""
    active_camera_id: str = ""
    active_surface_id: str = ""

    # Timing
    started_at: float = 0.0
    elapsed_seconds: float = 0.0
