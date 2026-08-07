"""Gray-code structured light projector calibration — the MVP.

Implements the :class:`ProjectorCalibrationAlgorithm` service contract
by composing the package components:

1. ``GrayCodePatternGenerator`` builds the stripe sequence.
2. ``CorrespondenceMatcher`` decodes captures into a dense map.
3. ``CameraProjectorTransformEstimator`` recovers intrinsics + pose.
4. ``ReprojectionValidator`` gates the result quality.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import override

import numpy as np
from numpy.typing import NDArray

from projectionai.calibration.types import CalibrationMethod
from projectionai.infrastructure.projector_calibration.correspondence import (
    CorrespondenceMatcher,
)
from projectionai.infrastructure.projector_calibration.estimators import (
    CameraProjectorTransformEstimator,
)
from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
    StructuredLightPatternGenerator,
)
from projectionai.infrastructure.projector_calibration.validation import (
    ReprojectionValidator,
    ValidationReport,
)
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    CorrespondenceMap,
    PatternSequence,
    ProjectorCalibrationAlgorithm,
    ProjectorCalibrationResult,
    SurfacePlane,
)

_logger = logging.getLogger(__name__)

_MAX_RMS_PX = 2.0
_MIN_COVERAGE = 0.5


class GrayCodeProjectorCalibration(ProjectorCalibrationAlgorithm):
    """Gray-code structured light projector calibration (MVP).

    Args:
        generator: Pattern generator (defaults to
            :class:`GrayCodePatternGenerator`).
        matcher: Capture decoder (defaults to
            :class:`CorrespondenceMatcher`).
        transform_estimator: Intrinsics/pose solver (defaults to
            :class:`CameraProjectorTransformEstimator`).
        validator: Quality gate (defaults to
            :class:`ReprojectionValidator` with RMS <= 2 px and
            coverage >= 0.5).
    """

    def __init__(
        self,
        generator: StructuredLightPatternGenerator | None = None,
        matcher: CorrespondenceMatcher | None = None,
        transform_estimator: CameraProjectorTransformEstimator | None = None,
        validator: ReprojectionValidator | None = None,
    ) -> None:
        self._generator = generator or GrayCodePatternGenerator()
        self._matcher = matcher or CorrespondenceMatcher()
        self._transform_estimator = (
            transform_estimator or CameraProjectorTransformEstimator()
        )
        self._validator = validator or ReprojectionValidator(
            max_rms=_MAX_RMS_PX, min_coverage=_MIN_COVERAGE
        )

    @property
    @override
    def method(self) -> CalibrationMethod:
        """The calibration method this algorithm implements."""
        return CalibrationMethod.GRAY_CODE

    def build_sequence(self, resolution: tuple[int, int]) -> PatternSequence:
        """Build the ordered gray-code stripe sequence."""
        width, height = resolution
        return self._generator.build_sequence(width, height)

    def decode(
        self,
        captures: Sequence[NDArray[np.uint8]],
        sequence: PatternSequence,
    ) -> CorrespondenceMap:
        """Decode captured frames into a dense correspondence map."""
        return self._matcher.decode(captures, sequence)

    def calibrate(
        self,
        correspondences: CorrespondenceMap,
        camera: CalibratedCamera,
        surface: SurfacePlane,
        resolution: tuple[int, int],
    ) -> ProjectorCalibrationResult:
        """Compute projector intrinsics, pose, and quality metrics."""
        transform = self._transform_estimator.estimate(
            correspondences, camera, surface, resolution
        )
        report = self._validator.validate(
            correspondences,
            camera,
            surface,
            transform.intrinsics,
            transform.pose,
            resolution,
        )
        confidence = self._confidence(report)
        _logger.info(
            "Projector calibration: %d correspondences, RMS %.3f px, "
            "coverage %.1f%%, confidence %.3f",
            correspondences.num_correspondences,
            report.rms_error,
            report.coverage * 100.0,
            confidence,
        )
        return ProjectorCalibrationResult(
            projector_intrinsics=transform.intrinsics,
            projector_resolution=resolution,
            projector_pose=transform.pose,
            reprojection_error=report.rms_error,
            num_correspondences=correspondences.num_correspondences,
            coverage=report.coverage,
            confidence=confidence,
            per_point_errors=report.per_point_errors,
            camera_matrix=camera.camera_matrix,
            distortion_coeffs=camera.distortion_coeffs,
            image_size=camera.image_size,
        )

    # -- Internal -----------------------------------------------------------

    def _confidence(self, report: ValidationReport) -> float:
        """Combine reprojection RMS and coverage into a ``[0, 1]`` score."""
        error_term = max(0.0, 1.0 - report.rms_error / (2.0 * self._validator.max_rms))
        return round(max(0.0, min(1.0, error_term * report.coverage)), 4)
