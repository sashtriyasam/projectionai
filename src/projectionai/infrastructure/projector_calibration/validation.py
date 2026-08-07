"""Reprojection validation for projector calibration.

Validates a computed calibration by reprojecting the triangulated
correspondences through the estimated projector model and measuring the
residual error in projector pixels. Also measures projector coverage —
the fraction of projector pixels backed by at least one correspondence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from projectionai.infrastructure.projector_calibration.estimators import (
    project_points,
    sample_correspondences,
    triangulate_plane,
    undistort_points,
)
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    CorrespondenceMap,
    ProjectorCalibrationError,
    SurfacePlane,
)

_logger = logging.getLogger(__name__)

_DEFAULT_MAX_RMS = 2.0
_DEFAULT_MIN_COVERAGE = 0.5
_DEFAULT_INLIER_THRESHOLD = 1.5
_DEFAULT_MAX_SAMPLES = 20_000


@dataclass(frozen=True)
class ValidationReport:
    """Quality metrics of a projector calibration.

    Attributes:
        rms_error: RMS projector reprojection error in pixels.
        mean_error: Mean absolute reprojection error in pixels.
        max_error: Maximum reprojection error in pixels.
        inlier_ratio: Fraction of sampled points within
            ``inlier_threshold`` pixels.
        coverage: Fraction of projector pixels covered by at least one
            valid correspondence.
        num_sampled: Number of correspondences validated.
        per_point_errors: Per-point reprojection errors in pixels.
        passed: ``True`` when RMS error and coverage meet thresholds.
    """

    rms_error: float
    mean_error: float
    max_error: float
    inlier_ratio: float
    coverage: float
    num_sampled: int
    discarded_samples: int = 0
    per_point_errors: tuple[float, ...] = ()
    passed: bool = False


class ReprojectionValidator:
    """Validates a calibration by reprojecting correspondences.

    Args:
        max_rms: RMS error threshold (pixels) for ``passed``.
        min_coverage: Minimum projector coverage for ``passed``.
        inlier_threshold: Pixel error below which a point counts as an
            inlier.
        max_samples: Upper bound on validated correspondences.
    """

    def __init__(
        self,
        max_rms: float = _DEFAULT_MAX_RMS,
        min_coverage: float = _DEFAULT_MIN_COVERAGE,
        inlier_threshold: float = _DEFAULT_INLIER_THRESHOLD,
        max_samples: int = _DEFAULT_MAX_SAMPLES,
    ) -> None:
        if not np.isfinite(max_rms) or max_rms <= 0:
            raise ProjectorCalibrationError(
                f"max_rms must be positive and finite, got {max_rms}"
            )
        self._max_rms = max_rms
        self._min_coverage = min_coverage
        self._inlier_threshold = inlier_threshold
        self._max_samples = max_samples

    @property
    def max_rms(self) -> float:
        """RMS error threshold (pixels) for ``passed``."""
        return self._max_rms

    def validate(
        self,
        correspondences: CorrespondenceMap,
        camera: CalibratedCamera,
        surface: SurfacePlane,
        intrinsics: NDArray[np.float64],
        pose: NDArray[np.float64],
        resolution: tuple[int, int],
    ) -> ValidationReport:
        """Validate a calibration against the decoded correspondences.

        Raises:
            ProjectorCalibrationError: If there is nothing to validate.
        """
        camera_pixels, projector_pixels = sample_correspondences(
            correspondences, self._max_samples
        )
        if len(camera_pixels) == 0:
            raise ProjectorCalibrationError("No correspondences to validate")

        normalized = undistort_points(camera_pixels, camera)
        plane_points = triangulate_plane(normalized, surface)
        predicted = project_points(plane_points, intrinsics, pose)
        errors = np.linalg.norm(predicted - projector_pixels, axis=1)

        finite = np.isfinite(errors) & np.all(np.isfinite(plane_points), axis=1)
        discarded_samples = int(np.count_nonzero(~finite))
        errors = errors[finite]
        if len(errors) == 0:
            raise ProjectorCalibrationError("No finite correspondences to validate")

        rms_error = float(np.sqrt(np.mean(np.square(errors))))
        mean_error = float(np.mean(errors))
        max_error = float(np.max(errors))
        inlier_ratio = float(np.mean(errors <= self._inlier_threshold))
        coverage = self._coverage(correspondences, resolution)
        passed = rms_error <= self._max_rms and coverage >= self._min_coverage

        _logger.info(
            "Validation: RMS %.3f px, max %.3f px, inliers %.1f%%, "
            "coverage %.1f%%, %d samples discarded, passed=%s",
            rms_error,
            max_error,
            inlier_ratio * 100.0,
            coverage * 100.0,
            discarded_samples,
            passed,
        )
        return ValidationReport(
            rms_error=rms_error,
            mean_error=mean_error,
            max_error=max_error,
            inlier_ratio=inlier_ratio,
            coverage=coverage,
            num_sampled=len(errors),
            discarded_samples=discarded_samples,
            per_point_errors=tuple(float(e) for e in errors),
            passed=passed,
        )

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _coverage(
        correspondences: CorrespondenceMap, resolution: tuple[int, int]
    ) -> float:
        """Fraction of projector pixels covered by valid correspondences."""
        width, height = resolution
        if width <= 0 or height <= 0:
            raise ProjectorCalibrationError(
                f"Invalid projector resolution: {width}x{height}"
            )
        xs = correspondences.projector_x[correspondences.mask]
        ys = correspondences.projector_y[correspondences.mask]
        if len(xs) == 0:
            return 0.0

        xs_int = np.floor(xs).astype(np.int64)
        ys_int = np.floor(ys).astype(np.int64)
        in_bounds = (xs_int >= 0) & (xs_int < width) & (ys_int >= 0) & (ys_int < height)
        unique = np.unique(
            np.column_stack((xs_int[in_bounds], ys_int[in_bounds])), axis=0
        )
        return float(len(unique)) / float(width * height)
