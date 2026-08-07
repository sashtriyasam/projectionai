"""Data models for the real-hardware validation workflow.

Defines the containers that describe a hardware validation run: the
recorded :class:`CaptureSequence`, the computed :class:`ValidationMetrics`,
the final :class:`CalibrationReport`, and the mutable
:class:`HardwareValidationSession` state machine. These compose the
existing projector-calibration building blocks (correspondence maps,
calibration results, reprojection reports) with display and environment
snapshots into one self-contained report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from projectionai.calibration.hardware_validation.environment import EnvironmentInfo
from projectionai.calibration.types import CalibrationStatus
from projectionai.core.errors import ProjectionAIError
from projectionai.infrastructure.display import DisplayInfo
from projectionai.infrastructure.projector_calibration.validation import (
    ValidationReport,
)
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationResult,
)


class HardwareValidationError(ProjectionAIError):
    """Raised when a hardware validation step fails."""


@dataclass(frozen=True)
class CaptureSequence:
    """A recorded structured light capture run.

    Attributes:
        camera_id: Camera the frames were captured from.
        projector_resolution: ``(width, height)`` of the projector
            display used.
        camera_resolution: ``(width, height)`` of the captured frames.
        num_patterns: Number of patterns in the sequence.
        captured_frames: One grayscale frame per pattern, in projection
            order.
        capture_times: Per-pattern capture duration in seconds.
        total_capture_seconds: Total projection/capture wall time.
    """

    camera_id: str
    projector_resolution: tuple[int, int]
    camera_resolution: tuple[int, int]
    num_patterns: int
    captured_frames: tuple[NDArray[np.uint8], ...]
    capture_times: tuple[float, ...]
    total_capture_seconds: float

    def __post_init__(self) -> None:
        if self.num_patterns != len(self.captured_frames):
            raise HardwareValidationError(
                f"num_patterns {self.num_patterns} does not match "
                f"{len(self.captured_frames)} captured frames"
            )
        if len(self.capture_times) != self.num_patterns:
            raise HardwareValidationError(
                f"capture_times has {len(self.capture_times)} entries, "
                f"expected {self.num_patterns}"
            )
        height, width = self.camera_resolution[1], self.camera_resolution[0]
        for frame in self.captured_frames:
            if frame.shape != (height, width):
                raise HardwareValidationError(
                    f"frame shape {frame.shape} does not match camera "
                    f"resolution {self.camera_resolution}"
                )


@dataclass(frozen=True)
class ValidationMetrics:
    """Quality metrics computed during hardware validation.

    Attributes:
        rms_error: RMS projector reprojection error in pixels.
        mean_error: Mean absolute reprojection error in pixels.
        max_error: Maximum reprojection error in pixels.
        inlier_ratio: Fraction of sampled correspondences within the
            inlier threshold.
        coverage: Fraction of projector pixels covered by at least one
            correspondence.
        corner_error: RMS projector corner reprojection error in pixels,
            or ``None`` when corners could not be estimated.
        confidence: Overall calibration confidence in ``[0, 1]``.
        num_correspondences: Number of valid camera-to-projector
            correspondences.
        missing_correspondences: Camera pixels with no valid decode.
        num_calibration_images: Number of captured frames used.
        calibration_seconds: Wall time of the calibration step.
        per_point_errors: Per-correspondence reprojection error in
            projector pixels.
        passed: ``True`` when the validation gates pass.
    """

    rms_error: float
    mean_error: float
    max_error: float
    inlier_ratio: float
    coverage: float
    corner_error: float | None
    confidence: float
    num_correspondences: int
    missing_correspondences: int
    num_calibration_images: int
    calibration_seconds: float
    per_point_errors: tuple[float, ...]
    passed: bool


@dataclass(frozen=True)
class CalibrationReport:
    """Self-contained report of a hardware validation run.

    Aggregates the environment snapshot, capture sequence, decoded
    correspondences, computed calibration, validation metrics, per-step
    timing, and warnings/errors into a single exportable artifact.

    Attributes:
        session_id: Unique identifier of the run.
        created_at: ISO-8601 UTC timestamp of report creation.
        camera_id: Camera used for capture.
        camera_model: Camera model string, if known.
        projector_display: Display used as the projector, or ``None``.
        projector_resolution: ``(width, height)`` of the projector, or
            ``None`` if no display could be selected.
        environment: Host environment snapshot.
        capture: The recorded capture sequence, or ``None`` on failure.
        correspondences: Decoded correspondence map, or ``None``.
        calibration: Computed calibration result, or ``None``.
        validation: Reprojection validation report, or ``None``.
        metrics: Computed validation metrics, or ``None``.
        status: Final session status.
        step_times: Per-step wall times in seconds.
        warnings: Non-fatal issues encountered.
        errors: Fatal errors (non-empty when ``status`` is FAILED).
        total_seconds: Total run wall time.
    """

    session_id: str
    created_at: str
    camera_id: str
    camera_model: str
    projector_display: DisplayInfo | None
    projector_resolution: tuple[int, int] | None
    environment: EnvironmentInfo
    capture: CaptureSequence | None
    correspondences: CorrespondenceMap | None
    calibration: ProjectorCalibrationResult | None
    validation: ValidationReport | None
    metrics: ValidationMetrics | None
    status: CalibrationStatus
    step_times: dict[str, float]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    total_seconds: float


@dataclass
class HardwareValidationSession:
    """Mutable state of an in-progress hardware validation run.

    Updated by :class:`ValidationRunner` as the workflow advances; the
    runner freezes the completed state into a :class:`CalibrationReport`.

    Attributes:
        session_id: Unique identifier of the run.
        status: Current lifecycle status.
        camera_id: Camera used for capture.
        screen_index: Display index used as the projector.
        current_step: Human-readable name of the active step.
        progress: Overall progress in ``[0, 1]``.
        status_text: Free-form status message for the UI.
        step_times: Wall time per step name, in seconds.
        warnings: Non-fatal issues.
        errors: Fatal errors.
        started_at: Monotonic clock time at run start.
        elapsed_seconds: Total elapsed time (filled at completion).
        capture: Intermediate capture sequence.
        correspondences: Intermediate correspondence map.
        calibration: Intermediate calibration result.
        validation: Intermediate reprojection report.
        metrics: Computed validation metrics.
    """

    session_id: str
    status: CalibrationStatus = CalibrationStatus.IDLE
    camera_id: str = ""
    screen_index: int = 0
    current_step: str = ""
    progress: float = 0.0
    status_text: str = ""
    step_times: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: float = 0.0
    elapsed_seconds: float = 0.0
    capture: CaptureSequence | None = None
    correspondences: CorrespondenceMap | None = None
    calibration: ProjectorCalibrationResult | None = None
    validation: ValidationReport | None = None
    metrics: ValidationMetrics | None = None
