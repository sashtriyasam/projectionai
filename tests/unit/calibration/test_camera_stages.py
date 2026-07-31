"""Tests for the camera calibration pipeline stages."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from projectionai.calibration.camera_stages import (
    BoardDetectionStage,
    IntrinsicsCalibrationStage,
)
from projectionai.calibration.pipeline import (
    CalibrationPipeline,
    StageContext,
    StageError,
)
from projectionai.calibration.types import CalibrationStageType
from projectionai.services.camera import Frame
from projectionai.services.camera_calibration import (
    BoardDetection,
    CameraCalibrationAlgorithm,
    CameraCalibrationError,
    CameraCalibrationResult,
)

_IMAGE_SIZE = (1280, 720)


def _frame(index: int) -> Frame:
    return Frame(
        image=np.full((720, 1280, 3), 128, np.uint8),
        timestamp=float(index),
        camera_id="cam-0",
        frame_number=index,
    )


def _detection(frame_number: int = 0) -> BoardDetection:
    return BoardDetection(
        corners=np.zeros((54, 1, 2), np.float32),
        image_size=_IMAGE_SIZE,
        frame_number=frame_number,
    )


def _result() -> CameraCalibrationResult:
    return CameraCalibrationResult(
        camera_matrix=np.eye(3, dtype=np.float64),
        distortion_coeffs=np.zeros(5, np.float64),
        image_size=_IMAGE_SIZE,
        reprojection_error=0.5,
        num_views=1,
    )


class StubAlgorithm(CameraCalibrationAlgorithm):
    """Configurable stub: detects on frames whose number is a multiple."""

    def __init__(self, detect_every: int = 1, fail_calibrate: bool = False) -> None:
        self._detect_every = detect_every
        self._fail_calibrate = fail_calibrate

    def detect(self, frame: Frame) -> BoardDetection | None:
        if frame.frame_number % self._detect_every != 0:
            return None
        return _detection(frame.frame_number)

    def calibrate(
        self, detections: Sequence[BoardDetection]
    ) -> CameraCalibrationResult:
        if self._fail_calibrate:
            raise CameraCalibrationError("calibration exploded")
        return _result()


class TestBoardDetectionStage:
    async def test_stage_type_and_name(self) -> None:
        stage = BoardDetectionStage(StubAlgorithm())
        assert stage.stage_type == CalibrationStageType.FEATURE_DETECTION
        assert stage.name == "board_detection"

    async def test_missing_frames_raises(self) -> None:
        stage = BoardDetectionStage(StubAlgorithm())
        with pytest.raises(StageError, match="No frames"):
            await stage(StageContext())

    async def test_empty_frames_list_raises(self) -> None:
        stage = BoardDetectionStage(StubAlgorithm())
        with pytest.raises(StageError, match="No frames"):
            await stage(StageContext(data={"frames": []}))

    async def test_collects_detections(self) -> None:
        stage = BoardDetectionStage(StubAlgorithm())
        ctx = await stage(StageContext(data={"frames": [_frame(0), _frame(1)]}))
        assert len(ctx.data["detections"]) == 2
        assert not ctx.warnings

    async def test_skips_frames_without_board(self) -> None:
        stage = BoardDetectionStage(StubAlgorithm(detect_every=2))
        ctx = await stage(StageContext(data={"frames": [_frame(0), _frame(1)]}))
        assert len(ctx.data["detections"]) == 1
        assert not ctx.warnings

    async def test_no_detections_appends_warning(self) -> None:
        stage = BoardDetectionStage(StubAlgorithm(detect_every=2))
        ctx = await stage(StageContext(data={"frames": [_frame(1)]}))
        assert ctx.data["detections"] == []
        assert any("No board detected" in warning for warning in ctx.warnings)


class TestIntrinsicsCalibrationStage:
    async def test_stage_type_and_name(self) -> None:
        stage = IntrinsicsCalibrationStage(StubAlgorithm())
        assert stage.stage_type == CalibrationStageType.POSE_ESTIMATION
        assert stage.name == "intrinsics_calibration"

    async def test_missing_detections_raises(self) -> None:
        stage = IntrinsicsCalibrationStage(StubAlgorithm())
        with pytest.raises(StageError, match="No board detections"):
            await stage(StageContext())

    async def test_writes_calibration_result(self) -> None:
        stage = IntrinsicsCalibrationStage(StubAlgorithm())
        ctx = await stage(StageContext(data={"detections": [_detection()]}))
        result = ctx.data["camera_calibration"]
        assert isinstance(result, CameraCalibrationResult)
        assert result.reprojection_error == 0.5

    async def test_wraps_algorithm_error(self) -> None:
        stage = IntrinsicsCalibrationStage(StubAlgorithm(fail_calibrate=True))
        with pytest.raises(StageError, match="calibration exploded"):
            await stage(StageContext(data={"detections": [_detection()]}))


class TestCameraPipelineIntegration:
    async def test_detect_and_calibrate_through_pipeline(self) -> None:
        pipeline = CalibrationPipeline()
        algorithm = StubAlgorithm()
        pipeline.add_stage(BoardDetectionStage(algorithm))
        pipeline.add_stage(IntrinsicsCalibrationStage(algorithm))
        ctx = await pipeline.run(
            StageContext(data={"frames": [_frame(0), _frame(1), _frame(2)]})
        )
        assert ctx.data["camera_calibration"].reprojection_error == 0.5
        assert len(ctx.data["detections"]) == 3

    async def test_pipeline_records_stage_failure(self) -> None:
        pipeline = CalibrationPipeline()
        algorithm = StubAlgorithm(fail_calibrate=True)
        pipeline.add_stage(BoardDetectionStage(algorithm))
        pipeline.add_stage(IntrinsicsCalibrationStage(algorithm))
        ctx = await pipeline.run(StageContext(data={"frames": [_frame(0)]}))
        assert ctx.errors
        assert "calibration exploded" in ctx.errors[0]
