"""Camera calibration pipeline stages.

Generic orchestration stages that drive a
:class:`~projectionai.services.camera_calibration.CameraCalibrationAlgorithm`
through the calibration framework's pipeline. These stages contain no
vision logic — they read frames/detections from the ``StageContext`` and
delegate to the injected algorithm.

StageContext key conventions:

- ``frames``: ``list[Frame]`` — captured frames (input to detection).
- ``detections``: ``list[BoardDetection]`` — successful board detections.
- ``camera_calibration``: ``CameraCalibrationResult`` — intrinsics output.
"""

from __future__ import annotations

import logging

from projectionai.calibration.pipeline import CalibrationStage, StageContext, StageError
from projectionai.calibration.types import CalibrationStageType
from projectionai.services.camera_calibration import (
    BoardDetection,
    CameraCalibrationAlgorithm,
    CameraCalibrationError,
)

_logger = logging.getLogger(__name__)


class BoardDetectionStage(CalibrationStage):
    """Detect the calibration board in every captured frame.

    Reads ``ctx.data["frames"]`` and writes ``ctx.data["detections"]``
    with the boards that were found. Frames where the board is not
    visible are skipped.
    """

    def __init__(self, algorithm: CameraCalibrationAlgorithm) -> None:
        super().__init__(CalibrationStageType.FEATURE_DETECTION)
        self.name = "board_detection"
        self._algorithm = algorithm

    async def execute(self, ctx: StageContext) -> StageContext:
        frames = ctx.data.get("frames")
        if not isinstance(frames, list) or not frames:
            msg = "No frames in context — run acquisition before detection"
            raise StageError(msg)

        detections: list[BoardDetection] = []
        for frame in frames:
            detection = self._algorithm.detect(frame)
            if detection is not None:
                detections.append(detection)

        if not detections:
            ctx.warnings.append("No board detected in any captured frame")
        ctx.data["detections"] = detections
        _logger.debug(
            "Board detection: %d/%d frames matched", len(detections), len(frames)
        )
        return ctx


class IntrinsicsCalibrationStage(CalibrationStage):
    """Compute camera intrinsics from collected board detections.

    Reads ``ctx.data["detections"]`` and writes
    ``ctx.data["camera_calibration"]``. Requires at least one detection;
    the algorithm enforces its own minimum view count.
    """

    def __init__(self, algorithm: CameraCalibrationAlgorithm) -> None:
        super().__init__(CalibrationStageType.POSE_ESTIMATION)
        self.name = "intrinsics_calibration"
        self._algorithm = algorithm

    async def execute(self, ctx: StageContext) -> StageContext:
        detections = ctx.data.get("detections")
        if not isinstance(detections, list) or not detections:
            msg = "No board detections in context — run detection first"
            raise StageError(msg)

        try:
            result = self._algorithm.calibrate(detections)
        except CameraCalibrationError as exc:
            raise StageError(str(exc)) from exc

        ctx.data["camera_calibration"] = result
        return ctx
