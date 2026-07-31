"""Tests for the chessboard camera calibration algorithm."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.infrastructure.calibration.chessboard import (
    ChessboardCalibrationAlgorithm,
)
from projectionai.services.camera import Frame
from projectionai.services.camera_calibration import (
    BoardDetection,
    CalibrationBoardConfig,
    CameraCalibrationError,
)
from tests.unit.calibration._synthetic_board import (
    SYNTHETIC_CAMERA_MATRIX,
    SYNTHETIC_CONFIG,
    SYNTHETIC_IMAGE_SIZE,
    VIEW_POSES,
    render_board_view,
    synthetic_frame,
)


class TestCalibrationBoardConfig:
    def test_valid_config(self) -> None:
        config = CalibrationBoardConfig(pattern_size=(9, 6), square_size_mm=30.0)
        assert config.corner_count == 54

    def test_pattern_too_small_raises(self) -> None:
        with pytest.raises(CameraCalibrationError, match="pattern_size"):
            CalibrationBoardConfig(pattern_size=(1, 6), square_size_mm=30.0)

    def test_nonpositive_square_size_raises(self) -> None:
        with pytest.raises(CameraCalibrationError, match="square_size_mm"):
            CalibrationBoardConfig(pattern_size=(9, 6), square_size_mm=0.0)


class TestChessboardDetection:
    def setup_method(self) -> None:
        self._algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)

    def test_detect_finds_board_in_synthetic_view(self) -> None:
        detection = self._algorithm.detect(synthetic_frame(0))
        assert detection is not None
        assert detection.corners.shape == (54, 2)
        assert detection.image_size == SYNTHETIC_IMAGE_SIZE
        assert detection.frame_number == 0

    def test_detect_finds_board_in_all_poses(self) -> None:
        for index in range(len(VIEW_POSES)):
            assert self._algorithm.detect(synthetic_frame(index)) is not None

    def test_detect_returns_none_for_noise(self) -> None:
        rng = np.random.default_rng(42)
        noise = rng.integers(0, 256, size=(720, 1280, 3), dtype=np.uint8)
        frame = Frame(
            image=noise,
            timestamp=0.0,
            camera_id="noise",
            frame_number=0,
        )
        assert self._algorithm.detect(frame) is None


class TestChessboardCalibration:
    def _detections(self, count: int = len(VIEW_POSES)) -> list[BoardDetection]:
        algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        detections = [
            detection
            for index in range(count)
            if (detection := algorithm.detect(synthetic_frame(index))) is not None
        ]
        assert len(detections) == count
        return detections

    def test_calibrate_recovers_intrinsics(self) -> None:
        algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        result = algorithm.calibrate(self._detections())

        camera_matrix = result.camera_matrix
        assert camera_matrix[0, 0] == pytest.approx(1000.0, rel=0.02)
        assert camera_matrix[1, 1] == pytest.approx(1000.0, rel=0.02)
        assert camera_matrix[0, 2] == pytest.approx(640.0, abs=10.0)
        assert camera_matrix[1, 2] == pytest.approx(360.0, abs=10.0)
        assert result.reprojection_error < 0.5
        assert result.num_views == len(VIEW_POSES)
        assert len(result.per_view_errors) == len(VIEW_POSES)

    def test_calibrate_too_few_views_raises(self) -> None:
        algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        detections = [
            BoardDetection(
                corners=np.zeros((54, 1, 2), np.float32),
                image_size=SYNTHETIC_IMAGE_SIZE,
                frame_number=index,
            )
            for index in range(2)
        ]
        with pytest.raises(CameraCalibrationError, match="at least 3"):
            algorithm.calibrate(detections)

    def test_calibrate_mixed_image_sizes_raises(self) -> None:
        algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        detections = [
            BoardDetection(
                corners=np.zeros((54, 1, 2), np.float32),
                image_size=image_size,
                frame_number=index,
            )
            for index, image_size in enumerate([(1280, 720), (640, 480), (1280, 720)])
        ]
        with pytest.raises(CameraCalibrationError, match="image size"):
            algorithm.calibrate(detections)

    def test_calibrate_with_distortion_recovers_coefficients(self) -> None:
        algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        distortion = np.array([0.06, -0.02, 0.0, 0.0, 0.0], np.float64)
        detections = [
            detection
            for index, (rvec, tvec) in enumerate(VIEW_POSES)
            if (
                detection := algorithm.detect(
                    Frame(
                        image=render_board_view(rvec, tvec, distortion=distortion),
                        timestamp=float(index),
                        camera_id="distorted",
                        frame_number=index,
                    )
                )
            )
            is not None
        ]
        assert len(detections) == len(VIEW_POSES)

        result = algorithm.calibrate(detections)
        assert result.distortion_coeffs[0] == pytest.approx(0.06, abs=0.05)
        assert result.distortion_coeffs[1] < 0.0
        assert result.camera_matrix[0, 0] == pytest.approx(
            SYNTHETIC_CAMERA_MATRIX[0, 0], rel=0.03
        )
