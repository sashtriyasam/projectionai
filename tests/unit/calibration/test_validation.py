"""Tests for projector calibration reprojection validation."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.infrastructure.projector_calibration.estimators import (
    project_points,
    sample_correspondences,
    triangulate_plane,
    undistort_points,
)
from projectionai.infrastructure.projector_calibration.gray_code import (
    GrayCodeProjectorCalibration,
)
from projectionai.infrastructure.projector_calibration.validation import (
    ReprojectionValidator,
)
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationError,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_PLANE,
    SYNTHETIC_PROJECTOR_MATRIX,
    SYNTHETIC_PROJECTOR_RESOLUTION,
    projector_pose_matrix,
    synthetic_captures,
    synthetic_sequence,
)

WIDTH, HEIGHT = SYNTHETIC_PROJECTOR_RESOLUTION


@pytest.fixture(scope="module")
def calibration() -> tuple[CorrespondenceMap, np.ndarray, np.ndarray]:
    """Synthetic correspondences plus ground-truth intrinsics and pose."""
    algorithm = GrayCodeProjectorCalibration()
    correspondences = algorithm.decode(synthetic_captures(), synthetic_sequence())
    return (
        correspondences,
        SYNTHETIC_PROJECTOR_MATRIX,
        projector_pose_matrix(),
    )


def _empty_correspondences() -> CorrespondenceMap:
    return CorrespondenceMap(
        projector_x=np.full((HEIGHT, WIDTH), np.nan, dtype=np.float32),
        projector_y=np.full((HEIGHT, WIDTH), np.nan, dtype=np.float32),
        mask=np.zeros((HEIGHT, WIDTH), dtype=np.bool_),
        image_size=(WIDTH, HEIGHT),
    )


class TestValidate:
    def test_reports_quality_metrics_on_synthetic_scene(
        self, calibration: tuple[CorrespondenceMap, np.ndarray, np.ndarray]
    ) -> None:
        correspondences, intrinsics, pose = calibration
        report = ReprojectionValidator().validate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            intrinsics,
            pose,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        assert 0.3 < report.rms_error < 0.6
        assert report.mean_error > 0.0
        assert 0.5 < report.max_error < 1.0
        # Every sampled point reprojects within 1.5 px on the synthetic scene.
        assert report.inlier_ratio == 1.0
        assert 0.8 < report.coverage < 0.9
        assert report.passed
        # Stride sampling caps at max_samples (20k) but the exact count is
        # determined by the stride over the ~921k valid mask pixels.
        assert 0 < report.num_sampled <= 20_000
        assert len(report.per_point_errors) == report.num_sampled

    def test_passed_reflects_rms_threshold(
        self, calibration: tuple[CorrespondenceMap, np.ndarray, np.ndarray]
    ) -> None:
        correspondences, intrinsics, pose = calibration
        strict = ReprojectionValidator(max_rms=0.1)
        report = strict.validate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            intrinsics,
            pose,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        assert not report.passed

    def test_passed_reflects_coverage_threshold(
        self, calibration: tuple[CorrespondenceMap, np.ndarray, np.ndarray]
    ) -> None:
        correspondences, intrinsics, pose = calibration
        strict = ReprojectionValidator(min_coverage=0.99)
        report = strict.validate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            intrinsics,
            pose,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        assert not report.passed

    def test_inlier_threshold_controls_inlier_ratio(
        self, calibration: tuple[CorrespondenceMap, np.ndarray, np.ndarray]
    ) -> None:
        correspondences, intrinsics, pose = calibration
        report = ReprojectionValidator(inlier_threshold=0.01).validate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            intrinsics,
            pose,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        # A few pixels land at (or under) 0.01 px, so the ratio is tiny but
        # not exactly zero — and far below the 1.0 ratio at the default 1.5.
        assert report.inlier_ratio < 0.001

    def test_per_point_errors_match_direct_computation(
        self, calibration: tuple[CorrespondenceMap, np.ndarray, np.ndarray]
    ) -> None:
        correspondences, intrinsics, pose = calibration
        validator = ReprojectionValidator(max_samples=1000)
        report = validator.validate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            intrinsics,
            pose,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        camera_pixels, projector_pixels = sample_correspondences(correspondences, 1000)
        normalized = undistort_points(camera_pixels, SYNTHETIC_CAMERA)
        plane_points = triangulate_plane(normalized, SYNTHETIC_PLANE)
        predicted = project_points(plane_points, intrinsics, pose)
        expected = np.linalg.norm(predicted - projector_pixels, axis=1)
        np.testing.assert_allclose(report.per_point_errors, expected, atol=1e-9)
        assert report.num_sampled == len(expected)

    def test_rejects_empty_correspondences(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="No correspondences"):
            ReprojectionValidator().validate(
                _empty_correspondences(),
                SYNTHETIC_CAMERA,
                SYNTHETIC_PLANE,
                SYNTHETIC_PROJECTOR_MATRIX,
                projector_pose_matrix(),
                SYNTHETIC_PROJECTOR_RESOLUTION,
            )


class TestMaxRmsProperty:
    def test_exposes_configured_threshold(self) -> None:
        assert ReprojectionValidator(max_rms=0.1).max_rms == 0.1

    def test_defaults_to_two_pixels(self) -> None:
        assert ReprojectionValidator().max_rms == 2.0

    def test_rejects_zero(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="max_rms must be positive"):
            ReprojectionValidator(max_rms=0.0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="max_rms must be positive"):
            ReprojectionValidator(max_rms=-1.0)

    def test_rejects_positive_infinity(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="max_rms must be positive"):
            ReprojectionValidator(max_rms=float("inf"))

    def test_rejects_nan(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="max_rms must be positive"):
            ReprojectionValidator(max_rms=float("nan"))
