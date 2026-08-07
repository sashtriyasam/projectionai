"""Projector calibration pipeline stages.

Generic orchestration stages that drive a
:class:`~projectionai.services.projector_calibration.ProjectorCalibrationAlgorithm`
through the calibration framework's pipeline. These stages contain no
vision logic — they read frames/correspondences from the ``StageContext``
and delegate to the injected algorithm.

StageContext key conventions:

- ``projector_frames``: ``list[Frame]`` — captured frames (input to decode).
- ``pattern_sequence``: ``PatternSequence`` — the projected sequence.
- ``projector_correspondences``: ``CorrespondenceMap`` — decode output.
- ``projector_resolution``: ``tuple[int, int]`` — projector resolution.
- ``calibrated_camera``: ``CalibratedCamera`` — camera intrinsics (input
  to pose estimation).
- ``surface_plane``: ``SurfacePlane`` — plane in camera coordinates.
- ``projector_calibration``: ``ProjectorCalibrationResult`` — pose output.
"""

from __future__ import annotations

import logging

from projectionai.calibration.pipeline import CalibrationStage, StageContext, StageError
from projectionai.calibration.types import CalibrationStageType
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    CorrespondenceMap,
    PatternSequence,
    ProjectorCalibrationAlgorithm,
    ProjectorCalibrationError,
    SurfacePlane,
)

_logger = logging.getLogger(__name__)


class CorrespondenceDecodeStage(CalibrationStage):
    """Decode structured light captures into dense correspondences.

    Reads ``ctx.data["projector_frames"]`` and
    ``ctx.data["pattern_sequence"]``, delegates to the algorithm's
    ``decode``, and writes ``ctx.data["projector_correspondences"]``.
    """

    def __init__(self, algorithm: ProjectorCalibrationAlgorithm) -> None:
        super().__init__(CalibrationStageType.CORRESPONDENCE_MATCHING)
        self.name = "correspondence_decode"
        self._algorithm = algorithm

    async def execute(self, ctx: StageContext) -> StageContext:
        frames = ctx.data.get("projector_frames")
        sequence = ctx.data.get("pattern_sequence")
        if not isinstance(frames, list) or not frames:
            msg = "No frames in context — run acquisition before decode"
            raise StageError(msg)
        if not isinstance(sequence, PatternSequence):
            msg = "No pattern sequence in context — run acquisition first"
            raise StageError(msg)

        try:
            correspondences = self._algorithm.decode(
                [frame.image for frame in frames], sequence
            )
        except ProjectorCalibrationError as exc:
            raise StageError(str(exc)) from exc

        ctx.data["projector_correspondences"] = correspondences
        _logger.debug(
            "Correspondence decode: %d valid pixels",
            correspondences.num_correspondences,
        )
        return ctx


class ProjectorPoseStage(CalibrationStage):
    """Compute projector intrinsics and pose from correspondences.

    Reads ``ctx.data["projector_correspondences"]``,
    ``ctx.data["calibrated_camera"]``, ``ctx.data["surface_plane"]``, and
    ``ctx.data["projector_resolution"]``; delegates to the algorithm's
    ``calibrate``, and writes ``ctx.data["projector_calibration"]``.
    """

    def __init__(self, algorithm: ProjectorCalibrationAlgorithm) -> None:
        super().__init__(CalibrationStageType.POSE_ESTIMATION)
        self.name = "projector_pose_estimation"
        self._algorithm = algorithm

    async def execute(self, ctx: StageContext) -> StageContext:
        correspondences = ctx.data.get("projector_correspondences")
        camera = ctx.data.get("calibrated_camera")
        surface = ctx.data.get("surface_plane")
        raw_resolution = ctx.data.get("projector_resolution")

        if not isinstance(correspondences, CorrespondenceMap):
            msg = "No correspondences in context — run decode first"
            raise StageError(msg)
        if not isinstance(camera, CalibratedCamera):
            msg = "No calibrated camera in context"
            raise StageError(msg)
        if not isinstance(surface, SurfacePlane):
            msg = "No surface plane in context"
            raise StageError(msg)
        if not isinstance(raw_resolution, tuple) or len(raw_resolution) != 2:
            msg = "No projector resolution in context"
            raise StageError(msg)
        resolution = (int(raw_resolution[0]), int(raw_resolution[1]))

        try:
            result = self._algorithm.calibrate(
                correspondences, camera, surface, resolution
            )
        except ProjectorCalibrationError as exc:
            raise StageError(str(exc)) from exc

        ctx.data["projector_calibration"] = result
        _logger.debug(
            "Projector pose: RMS %.3f px, coverage %.1f%%",
            result.reprojection_error,
            result.coverage * 100.0,
        )
        return ctx
