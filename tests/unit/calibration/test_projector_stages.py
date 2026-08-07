"""Tests for the projector calibration pipeline stages."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.calibration.pipeline import StageContext, StageError
from projectionai.calibration.projector_stages import (
    CorrespondenceDecodeStage,
    ProjectorPoseStage,
)
from projectionai.calibration.types import CalibrationMethod, CalibrationStageType
from projectionai.infrastructure.projector_calibration.gray_code import (
    GrayCodeProjectorCalibration,
)
from projectionai.services.camera import Frame
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationAlgorithm,
    ProjectorCalibrationError,
    ProjectorCalibrationResult,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_PLANE,
    SYNTHETIC_PROJECTOR_RESOLUTION,
    synthetic_captures,
    synthetic_sequence,
)


class _FakeAlgorithm(ProjectorCalibrationAlgorithm):
    """Delegates to the real gray-code algorithm but records every call."""

    def __init__(self) -> None:
        self.decode_calls: list[list[np.ndarray]] = []
        self.calibrate_calls: list[tuple] = []
        self._delegate = GrayCodeProjectorCalibration()

    @property
    def method(self) -> CalibrationMethod:
        return CalibrationMethod.GRAY_CODE

    def build_sequence(self, resolution: tuple[int, int]):
        return self._delegate.build_sequence(resolution)

    def decode(self, captures, sequence) -> CorrespondenceMap:
        self.decode_calls.append(list(captures))
        return self._delegate.decode(captures, sequence)

    def calibrate(
        self, correspondences, camera, surface, resolution
    ) -> ProjectorCalibrationResult:
        self.calibrate_calls.append((correspondences, camera, surface, resolution))
        return self._delegate.calibrate(correspondences, camera, surface, resolution)


class _RaisingAlgorithm(_FakeAlgorithm):
    def decode(self, captures, sequence) -> CorrespondenceMap:
        raise ProjectorCalibrationError("decode exploded")

    def calibrate(
        self, correspondences, camera, surface, resolution
    ) -> ProjectorCalibrationResult:
        raise ProjectorCalibrationError("calibrate exploded")


def _frames() -> list[Frame]:
    captures = synthetic_captures()
    return [
        Frame(
            image=image,
            timestamp=float(index),
            camera_id="cam-0",
            frame_number=index,
        )
        for index, image in enumerate(captures)
    ]


@pytest.fixture(scope="module")
def synthetic_correspondences() -> CorrespondenceMap:
    """Decode the synthetic scene once per module."""
    algorithm = GrayCodeProjectorCalibration()
    return algorithm.decode(synthetic_captures(), synthetic_sequence())


class TestCorrespondenceDecodeStage:
    def test_stage_metadata(self) -> None:
        stage = CorrespondenceDecodeStage(_FakeAlgorithm())
        assert stage.name == "correspondence_decode"
        assert stage.stage_type is CalibrationStageType.CORRESPONDENCE_MATCHING

    async def test_decodes_frames_into_context(self) -> None:
        algorithm = _FakeAlgorithm()
        sequence = synthetic_sequence()
        ctx = StageContext(
            data={"projector_frames": _frames(), "pattern_sequence": sequence}
        )
        result = await CorrespondenceDecodeStage(algorithm).execute(ctx)

        assert isinstance(result.data["projector_correspondences"], CorrespondenceMap)
        assert result.data["projector_correspondences"].num_correspondences > 0
        expected_frames = [frame.image for frame in _frames()]
        assert len(algorithm.decode_calls) == 1
        assert len(algorithm.decode_calls[0]) == len(expected_frames)
        for got, want in zip(algorithm.decode_calls[0], expected_frames, strict=True):
            assert np.array_equal(got, want)

    async def test_missing_frames_raises(self) -> None:
        ctx = StageContext(data={"pattern_sequence": synthetic_sequence()})
        with pytest.raises(StageError, match="No frames"):
            await CorrespondenceDecodeStage(_FakeAlgorithm()).execute(ctx)

    async def test_missing_sequence_raises(self) -> None:
        ctx = StageContext(data={"projector_frames": _frames()})
        with pytest.raises(StageError, match="sequence"):
            await CorrespondenceDecodeStage(_FakeAlgorithm()).execute(ctx)

    async def test_algorithm_error_becomes_stage_error(self) -> None:
        ctx = StageContext(
            data={
                "projector_frames": _frames(),
                "pattern_sequence": synthetic_sequence(),
            }
        )
        with pytest.raises(StageError, match="decode exploded"):
            await CorrespondenceDecodeStage(_RaisingAlgorithm()).execute(ctx)


class TestProjectorPoseStage:
    def test_stage_metadata(self) -> None:
        stage = ProjectorPoseStage(_FakeAlgorithm())
        assert stage.name == "projector_pose_estimation"
        assert stage.stage_type is CalibrationStageType.POSE_ESTIMATION

    async def test_estimates_pose_into_context(self) -> None:
        algorithm = _FakeAlgorithm()
        sequence = synthetic_sequence()
        decode_ctx = StageContext(
            data={"projector_frames": _frames(), "pattern_sequence": sequence}
        )
        decode_ctx = await CorrespondenceDecodeStage(algorithm).execute(decode_ctx)
        correspondences = decode_ctx.data["projector_correspondences"]

        pose_ctx = StageContext(
            data={
                "projector_correspondences": correspondences,
                "calibrated_camera": SYNTHETIC_CAMERA,
                "surface_plane": SYNTHETIC_PLANE,
                "projector_resolution": SYNTHETIC_PROJECTOR_RESOLUTION,
            }
        )
        result = await ProjectorPoseStage(algorithm).execute(pose_ctx)

        calibration = result.data["projector_calibration"]
        assert isinstance(calibration, ProjectorCalibrationResult)
        assert calibration.coverage > 0.5
        assert algorithm.calibrate_calls == [
            (
                correspondences,
                SYNTHETIC_CAMERA,
                SYNTHETIC_PLANE,
                SYNTHETIC_PROJECTOR_RESOLUTION,
            )
        ]

    @pytest.mark.parametrize(
        ("missing_key", "message"),
        [
            ("projector_correspondences", "No correspondences"),
            ("calibrated_camera", "No calibrated camera"),
            ("surface_plane", "No surface plane"),
            ("projector_resolution", "No projector resolution"),
        ],
    )
    async def test_missing_input_raises(
        self,
        missing_key: str,
        message: str,
        synthetic_correspondences: CorrespondenceMap,
    ) -> None:
        ctx = StageContext(
            data={
                "projector_correspondences": synthetic_correspondences,
                "calibrated_camera": SYNTHETIC_CAMERA,
                "surface_plane": SYNTHETIC_PLANE,
                "projector_resolution": SYNTHETIC_PROJECTOR_RESOLUTION,
            }
        )
        del ctx.data[missing_key]
        with pytest.raises(StageError, match=message):
            await ProjectorPoseStage(_FakeAlgorithm()).execute(ctx)

    async def test_algorithm_error_becomes_stage_error(
        self, synthetic_correspondences: CorrespondenceMap
    ) -> None:
        ctx = StageContext(
            data={
                "projector_correspondences": synthetic_correspondences,
                "calibrated_camera": SYNTHETIC_CAMERA,
                "surface_plane": SYNTHETIC_PLANE,
                "projector_resolution": SYNTHETIC_PROJECTOR_RESOLUTION,
            }
        )
        with pytest.raises(StageError, match="calibrate exploded"):
            await ProjectorPoseStage(_RaisingAlgorithm()).execute(ctx)
