"""End-to-end tests for the gray-code projector calibration algorithm."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.calibration.types import CalibrationMethod
from projectionai.infrastructure.projector_calibration.estimators import (
    CameraProjectorTransform,
    CameraProjectorTransformEstimator,
)
from projectionai.infrastructure.projector_calibration.gray_code import (
    GrayCodeProjectorCalibration,
)
from projectionai.infrastructure.projector_calibration.validation import (
    ReprojectionValidator,
    ValidationReport,
)
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationError,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_CAMERA_MATRIX,
    SYNTHETIC_PLANE,
    SYNTHETIC_PROJECTOR_MATRIX,
    SYNTHETIC_PROJECTOR_RESOLUTION,
    projector_pose_matrix,
    synthetic_captures,
    synthetic_sequence,
)

WIDTH, HEIGHT = SYNTHETIC_PROJECTOR_RESOLUTION


class TestGrayCodeProjectorCalibration:
    def test_method_is_gray_code(self) -> None:
        assert GrayCodeProjectorCalibration().method is CalibrationMethod.GRAY_CODE

    def test_build_sequence(self) -> None:
        sequence = GrayCodeProjectorCalibration().build_sequence(
            SYNTHETIC_PROJECTOR_RESOLUTION
        )
        assert sequence.width == WIDTH
        assert sequence.height == HEIGHT
        assert sequence.bits_x == 11
        assert sequence.bits_y == 10
        assert len(sequence.patterns) == 21

    def test_decode_returns_dense_correspondences(self) -> None:
        algorithm = GrayCodeProjectorCalibration()
        correspondences = algorithm.decode(synthetic_captures(), synthetic_sequence())
        assert isinstance(correspondences, CorrespondenceMap)
        assert correspondences.num_correspondences > 0.8 * WIDTH * HEIGHT

    def test_calibrate_recovers_intrinsics_pose_and_quality(self) -> None:
        algorithm = GrayCodeProjectorCalibration()
        correspondences = algorithm.decode(synthetic_captures(), synthetic_sequence())
        result = algorithm.calibrate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )

        # Intrinsics.
        assert result.projector_intrinsics[0, 0] == pytest.approx(2000.0, rel=0.01)
        assert result.projector_intrinsics[1, 1] == pytest.approx(2000.0, rel=0.01)
        assert result.projector_intrinsics[0, 2] == WIDTH / 2.0
        assert result.projector_intrinsics[1, 2] == HEIGHT / 2.0

        # Pose (projector-local -> camera frame).
        assert np.abs(result.projector_pose - projector_pose_matrix()).max() < 0.5

        # Quality metrics (platform-tolerant gates: absolute solve error
        # varies with BLAS backend, so only one-sided bounds are enforced).
        assert result.reprojection_error < 1.0
        assert result.coverage > 0.8
        assert 0.5 < result.confidence < 1.0
        assert result.num_correspondences == correspondences.num_correspondences
        assert len(result.per_point_errors) > 10_000

        # Echoed camera inputs.
        np.testing.assert_array_equal(result.camera_matrix, SYNTHETIC_CAMERA_MATRIX)
        assert result.image_size == SYNTHETIC_CAMERA.image_size
        assert len(result.distortion_coeffs) == 5

    def test_calibrate_rejects_sparse_correspondences(self) -> None:
        sparse = CorrespondenceMap(
            projector_x=np.full((HEIGHT, WIDTH), np.nan, dtype=np.float32),
            projector_y=np.full((HEIGHT, WIDTH), np.nan, dtype=np.float32),
            mask=np.zeros((HEIGHT, WIDTH), dtype=np.bool_),
            image_size=(WIDTH, HEIGHT),
        )
        sparse.mask[100, 100] = True
        sparse.mask[200, 200] = True
        with pytest.raises(ProjectorCalibrationError, match="after sampling"):
            GrayCodeProjectorCalibration().calibrate(
                sparse,
                SYNTHETIC_CAMERA,
                SYNTHETIC_PLANE,
                SYNTHETIC_PROJECTOR_RESOLUTION,
            )


class _FakeTransformEstimator(CameraProjectorTransformEstimator):
    """Returns a fixed ground-truth transform without any solving."""

    def estimate(self, correspondences, camera, surface, resolution):
        return CameraProjectorTransform(
            intrinsics=SYNTHETIC_PROJECTOR_MATRIX.copy(),
            resolution=resolution,
            pose=projector_pose_matrix(),
        )


class _FakeValidator(ReprojectionValidator):
    def __init__(self, max_rms: float = 2.0) -> None:
        super().__init__(max_rms=max_rms)
        self.calls = 0

    def validate(self, correspondences, camera, surface, intrinsics, pose, resolution):
        self.calls += 1
        return ValidationReport(
            rms_error=0.1,
            mean_error=0.1,
            max_error=0.2,
            inlier_ratio=1.0,
            coverage=0.9,
            num_sampled=2,
            per_point_errors=(0.1, 0.2),
            passed=True,
        )


class TestComponentInjection:
    def test_calibrate_composes_estimator_and_validator(self) -> None:
        validator = _FakeValidator()
        algorithm = GrayCodeProjectorCalibration(
            transform_estimator=_FakeTransformEstimator(), validator=validator
        )
        correspondences = algorithm.decode(synthetic_captures(), synthetic_sequence())
        result = algorithm.calibrate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )

        np.testing.assert_array_equal(
            result.projector_intrinsics, SYNTHETIC_PROJECTOR_MATRIX
        )
        assert result.reprojection_error == 0.1
        assert result.coverage == 0.9
        # confidence = (1 - rms / (2 * max_rms)) * coverage, with max_rms = 2.
        assert result.confidence == pytest.approx((1.0 - 0.1 / 4.0) * 0.9, abs=1e-4)
        assert result.num_correspondences == correspondences.num_correspondences
        assert validator.calls == 1

    def test_confidence_normalises_against_validator_max_rms(self) -> None:
        # _confidence derives its threshold from the injected validator, so a
        # tolerant validator (max_rms=5) normalises RMS against 2 * 5 = 10 px
        # instead of the default 2 * 2 = 4 px.
        validator = _FakeValidator(max_rms=5.0)
        algorithm = GrayCodeProjectorCalibration(
            transform_estimator=_FakeTransformEstimator(), validator=validator
        )
        correspondences = algorithm.decode(synthetic_captures(), synthetic_sequence())
        result = algorithm.calibrate(
            correspondences,
            SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            SYNTHETIC_PROJECTOR_RESOLUTION,
        )
        assert result.confidence == pytest.approx((1.0 - 0.1 / 10.0) * 0.9, abs=1e-4)
