"""Unit tests for the hardware validation data models."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.calibration.hardware_validation.environment import EnvironmentInfo
from projectionai.calibration.hardware_validation.models import (
    CalibrationReport,
    CaptureSequence,
    HardwareValidationError,
    HardwareValidationSession,
    ValidationMetrics,
)
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


def _environment() -> EnvironmentInfo:
    return EnvironmentInfo(
        opencv_version="5.0.0",
        python_version="3.12",
        platform="win32",
        machine="AMD64",
        processor="x86_64",
        cpu_count=8,
        memory_bytes=16 * 1024**3,
        started_at="2026-01-01T00:00:00+00:00",
    )


def _capture_sequence() -> CaptureSequence:
    return CaptureSequence(
        camera_id="cam-0",
        projector_resolution=(32, 16),
        camera_resolution=(8, 8),
        num_patterns=2,
        captured_frames=(
            np.zeros((8, 8), dtype=np.uint8),
            np.full((8, 8), 255, dtype=np.uint8),
        ),
        capture_times=(0.1, 0.2),
        total_capture_seconds=0.3,
    )


def _correspondence_map() -> CorrespondenceMap:
    projector_x = np.full((8, 8), np.nan, dtype=np.float32)
    projector_y = np.full((8, 8), np.nan, dtype=np.float32)
    mask = np.zeros((8, 8), dtype=np.bool_)
    projector_x[2, 2] = 10.0
    projector_y[2, 2] = 5.0
    mask[2, 2] = True
    projector_x[3, 3] = 20.0
    projector_y[3, 3] = 6.0
    mask[3, 3] = True
    return CorrespondenceMap(
        projector_x=projector_x,
        projector_y=projector_y,
        mask=mask,
        image_size=(8, 8),
    )


def _calibration_result() -> ProjectorCalibrationResult:
    return ProjectorCalibrationResult(
        projector_intrinsics=np.eye(3, dtype=np.float64),
        projector_resolution=(32, 16),
        projector_pose=np.eye(4, dtype=np.float64),
        reprojection_error=0.5,
        num_correspondences=2,
        coverage=0.5,
        confidence=0.9,
        per_point_errors=(0.4, 0.6),
        camera_matrix=np.eye(3, dtype=np.float64),
        distortion_coeffs=np.zeros(5, dtype=np.float64),
        image_size=(8, 8),
    )


class TestHardwareValidationError:
    def test_is_projectionai_error(self) -> None:
        assert issubclass(HardwareValidationError, ProjectionAIError)

    def test_can_be_raised(self) -> None:
        with pytest.raises(HardwareValidationError, match="boom"):
            raise HardwareValidationError("boom")


class TestCaptureSequence:
    def test_valid_sequence(self) -> None:
        sequence = _capture_sequence()
        assert sequence.num_patterns == 2
        assert sequence.camera_id == "cam-0"
        assert sequence.projector_resolution == (32, 16)
        assert sequence.camera_resolution == (8, 8)
        assert len(sequence.captured_frames) == 2
        assert sequence.capture_times == (0.1, 0.2)
        assert sequence.total_capture_seconds == pytest.approx(0.3)

    def test_num_patterns_mismatch_raises(self) -> None:
        with pytest.raises(HardwareValidationError, match="num_patterns"):
            CaptureSequence(
                camera_id="cam-0",
                projector_resolution=(32, 16),
                camera_resolution=(8, 8),
                num_patterns=3,
                captured_frames=(np.zeros((8, 8), dtype=np.uint8),),
                capture_times=(0.1,),
                total_capture_seconds=0.1,
            )

    def test_capture_times_mismatch_raises(self) -> None:
        with pytest.raises(HardwareValidationError, match="capture_times"):
            CaptureSequence(
                camera_id="cam-0",
                projector_resolution=(32, 16),
                camera_resolution=(8, 8),
                num_patterns=2,
                captured_frames=(
                    np.zeros((8, 8), dtype=np.uint8),
                    np.zeros((8, 8), dtype=np.uint8),
                ),
                capture_times=(0.1,),
                total_capture_seconds=0.1,
            )

    def test_frame_shape_mismatch_raises(self) -> None:
        with pytest.raises(HardwareValidationError, match="frame shape"):
            CaptureSequence(
                camera_id="cam-0",
                projector_resolution=(32, 16),
                camera_resolution=(8, 8),
                num_patterns=2,
                captured_frames=(
                    np.zeros((8, 8), dtype=np.uint8),
                    np.zeros((9, 9), dtype=np.uint8),
                ),
                capture_times=(0.1, 0.2),
                total_capture_seconds=0.3,
            )


class TestHardwareValidationSession:
    def test_defaults(self) -> None:
        session = HardwareValidationSession(session_id="hwval-1")
        assert session.session_id == "hwval-1"
        assert session.status is CalibrationStatus.IDLE
        assert session.camera_id == ""
        assert session.screen_index == 0
        assert session.progress == 0.0
        assert session.step_times == {}
        assert session.warnings == []
        assert session.errors == []
        assert session.capture is None
        assert session.correspondences is None
        assert session.calibration is None
        assert session.validation is None
        assert session.metrics is None

    def test_mutable_after_creation(self) -> None:
        session = HardwareValidationSession(session_id="hwval-1")
        session.status = CalibrationStatus.COMPLETED
        session.progress = 1.0
        session.step_times["capture"] = 1.5
        session.errors.append("nope")
        assert session.status is CalibrationStatus.COMPLETED
        assert session.progress == 1.0
        assert session.step_times == {"capture": 1.5}
        assert session.errors == ["nope"]


class TestCalibrationReport:
    def test_completed_report(self) -> None:
        display = DisplayInfo(
            index=0, name="projector", width=1280, height=720, is_primary=True
        )
        validation = ValidationReport(
            rms_error=0.5,
            mean_error=0.4,
            max_error=0.9,
            inlier_ratio=1.0,
            coverage=0.9,
            num_sampled=2,
            per_point_errors=(0.4, 0.6),
            passed=True,
        )
        metrics = ValidationMetrics(
            rms_error=0.5,
            mean_error=0.4,
            max_error=0.9,
            inlier_ratio=1.0,
            coverage=0.9,
            corner_error=0.7,
            confidence=0.9,
            num_correspondences=2,
            missing_correspondences=62,
            num_calibration_images=2,
            calibration_seconds=0.1,
            per_point_errors=(0.4, 0.6),
            passed=True,
        )
        report = CalibrationReport(
            session_id="hwval-test",
            created_at="2026-01-01T00:00:00+00:00",
            camera_id="cam-0",
            camera_model="Synthetic",
            projector_display=display,
            projector_resolution=(32, 16),
            environment=_environment(),
            capture=_capture_sequence(),
            correspondences=_correspondence_map(),
            calibration=_calibration_result(),
            validation=validation,
            metrics=metrics,
            status=CalibrationStatus.COMPLETED,
            step_times={"connect_camera": 0.01},
            warnings=(),
            errors=(),
            total_seconds=0.5,
        )
        assert report.status is CalibrationStatus.COMPLETED
        assert report.capture is not None
        assert report.metrics is not None
        assert report.metrics.rms_error == pytest.approx(0.5)
        assert report.projector_display is display
        assert report.projector_resolution == (32, 16)

    def test_failed_report_has_no_metrics(self) -> None:
        report = CalibrationReport(
            session_id="hwval-test",
            created_at="2026-01-01T00:00:00+00:00",
            camera_id="",
            camera_model="",
            projector_display=None,
            projector_resolution=None,
            environment=_environment(),
            capture=None,
            correspondences=None,
            calibration=None,
            validation=None,
            metrics=None,
            status=CalibrationStatus.FAILED,
            step_times={},
            warnings=(),
            errors=("No cameras detected",),
            total_seconds=0.1,
        )
        assert report.status is CalibrationStatus.FAILED
        assert report.metrics is None
        assert report.capture is None
        assert report.errors == ("No cameras detected",)
