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
    """Lifecycle state of a calibration session.

    Phase 6.2 canonical status is domain.calibration_session.CalibrationSessionStatus.
    This enum retains backward-compatible values and adds Phase 6.2 aliases.
    """

    IDLE = "idle"
    CREATED = "created"
    PREPARING = "preparing"
    ACQUIRING = "acquiring"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    SOLVING = "solving"
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
    RECONSTRUCTION = "reconstruction"
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


# ---------------------------------------------------------------------------
# Phase 6.2 compat — canonical domain adapters
# ---------------------------------------------------------------------------


def calibration_result_to_canonical(legacy: CalibrationResult) -> Any:
    """Convert legacy calibration/types.CalibrationResult to canonical domain."""
    import time as _time
    import uuid as _uuid

    import numpy as _np

    from projectionai.domain.calibration_session import (
        CalibrationMethod as _DomainMethod,
    )
    from projectionai.domain.calibration_session import (
        CalibrationResult as _Canonical,
    )

    if legacy.data is None:
        raise ValueError("Cannot convert CalibrationResult with no data")
    data = legacy.data
    # Prefer projector_pose first entry
    if data.projector_pose:
        pid = next(iter(data.projector_pose))
        pdict = data.projector_pose[pid]
        pose_list = (
            pdict.get("pose") or pdict.get("projector_pose") or pdict.get("matrix")
        )
        mat = (
            _np.array(pose_list, dtype=_np.float64).reshape(4, 4)
            if pose_list is not None
            else _np.eye(4)
        )
        intr_list = pdict.get("projector_matrix") or pdict.get("camera_matrix")
        if intr_list is not None:
            intr = _np.array(intr_list, dtype=_np.float64).reshape(3, 3)
        else:
            intr = _np.eye(3)
        pw = int(pdict.get("width", 1920))
        ph = int(pdict.get("height", 1080))
    else:
        pid = "projector_0"
        mat = _np.eye(4)
        intr = _np.eye(3)
        pw, ph = 1920, 1080
    # camera
    cam_id = next(iter(data.camera_pose)) if data.camera_pose else "camera_0"
    cdict = data.camera_pose.get(cam_id, {}) if data.camera_pose else {}
    cam_mat = None
    if cdict.get("camera_matrix") is not None:
        cam_mat = _np.array(cdict["camera_matrix"], dtype=_np.float64).reshape(3, 3)
    dist = None
    if cdict.get("distortion_coeffs") is not None:
        dist = _np.array(cdict["distortion_coeffs"], dtype=_np.float64)
    img_size = None
    if cdict.get("width") and cdict.get("height"):
        img_size = (int(cdict["width"]), int(cdict["height"]))
    try:
        method = _DomainMethod(str(data.method.value))
    except Exception:
        method = _DomainMethod.MANUAL
    return _Canonical(
        calibration_id=_uuid.uuid4().hex,
        sequence_id=str(data.custom.get("sequence_id", _uuid.uuid4().hex)),
        method=method,
        projector_id=pid,
        camera_id=cam_id,
        surface_id=str(data.custom.get("surface_id", "")),
        projector_intrinsics=intr,
        projector_pose=mat,
        projector_resolution=(pw, ph),
        reprojection_error=float(data.reprojection_error),
        coverage=float(data.custom.get("coverage", 0.0)),
        num_correspondences=int(data.num_samples),
        confidence=float(data.confidence),
        per_point_errors=tuple(float(x) for x in data.residuals),
        camera_matrix=cam_mat,
        distortion_coeffs=dist,
        image_size=img_size,
        created_at=_time.time(),
        metadata=dict(data.custom),
    )


def canonical_to_legacy_result(canonical: Any) -> CalibrationResult:
    """Convert canonical domain CalibrationResult back to legacy."""
    from projectionai.domain.calibration_session import (
        CalibrationResult as _Canonical,  # noqa: F401
    )

    data = CalibrationData(
        projector_pose={
            canonical.projector_id: {
                "pose": canonical.projector_pose.tolist(),
                "projector_matrix": canonical.projector_intrinsics.tolist(),
                "width": canonical.projector_resolution[0],
                "height": canonical.projector_resolution[1],
            }
        },
        camera_pose={},
        surface_pose={},
        confidence=canonical.confidence,
        reprojection_error=canonical.reprojection_error,
        residuals=list(canonical.per_point_errors),
        method=CalibrationMethod(canonical.method.value)
        if canonical.method.value in [m.value for m in CalibrationMethod]
        else CalibrationMethod.MANUAL,
        num_samples=canonical.num_correspondences,
        custom={
            **dict(canonical.metadata),
            "sequence_id": canonical.sequence_id,
            "surface_id": canonical.surface_id,
            "coverage": canonical.coverage,
        },
    )
    if canonical.camera_matrix is not None:
        data.camera_pose[canonical.camera_id] = {
            "camera_matrix": canonical.camera_matrix.tolist(),
            "distortion_coeffs": canonical.distortion_coeffs.tolist()
            if canonical.distortion_coeffs is not None
            else [0.0] * 5,
            "width": canonical.image_size[0] if canonical.image_size else 1920,
            "height": canonical.image_size[1] if canonical.image_size else 1080,
        }
    return CalibrationResult(
        success=True,
        data=data,
        validation_errors=[],
        validation_warnings=[],
        quality_score=canonical.confidence,
        error_message="",
    )
