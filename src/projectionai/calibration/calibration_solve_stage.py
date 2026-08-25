"""Calibration solve stage — consumes reconstructions, produces CalibrationResult."""

from __future__ import annotations

import logging
from typing import Any

from projectionai.calibration.pipeline import CalibrationStage, StageContext, StageError
from projectionai.calibration.solver import CalibrationSolveError, solve_calibration
from projectionai.calibration.types import CalibrationStageType
from projectionai.domain.calibration_session import ReconstructionResult

_logger = logging.getLogger(__name__)


class CalibrationSolveStage(CalibrationStage):
    """Solve projector intrinsics + pose from 2+ reconstructions.

    Reads:
      - reconstructions: tuple[ReconstructionResult, ...]  (preferred)
        or reconstruction: ReconstructionResult (single, will fail diversity guard)
      - projector_resolution: tuple[int,int] (list or tuple, normalized to tuple)
      - calibrated_camera (optional, for metadata)
      - projector_id / camera_id / surface_id (optional)

    Writes:
      - calibration_result: CalibrationResult
    """

    def __init__(
        self,
        projector_resolution: tuple[int, int] | None = None,
        enable_refine: bool = False,
        refine_threshold: float = 2.0,
    ) -> None:
        super().__init__(CalibrationStageType.POSE_ESTIMATION)
        self.name = "calibration_solve"
        self._resolution = projector_resolution
        self._enable_refine = enable_refine
        self._refine_threshold = refine_threshold

    async def execute(self, ctx: StageContext) -> StageContext:
        # Gather reconstructions
        recs: Any = ctx.data.get("reconstructions")
        if recs is None:
            single = ctx.data.get("reconstruction")
            if single is not None:
                recs = (single,)
            else:
                raise StageError(
                    "No reconstructions in context — run reconstruction before calibration solve"
                )
        if isinstance(recs, list):
            recs = tuple(recs)
        if not isinstance(recs, tuple):
            raise StageError(
                f"reconstructions must be tuple[ReconstructionResult], got {type(recs).__name__}"
            )
        for r in recs:
            if not isinstance(r, ReconstructionResult):
                raise StageError(
                    f"reconstructions contains non-ReconstructionResult: {type(r).__name__}"
                )

        # Resolution
        resolution = self._resolution or ctx.data.get("projector_resolution")
        if resolution is None:
            # Try to infer from reconstructions' sequence? Need explicit
            raise StageError(
                "projector_resolution missing — provide via stage or context"
            )
        if not isinstance(resolution, (list, tuple)) or len(resolution) != 2:
            raise StageError(f"Invalid projector_resolution: {resolution!r}")
        try:
            resolution = (int(resolution[0]), int(resolution[1]))
        except Exception as exc:
            raise StageError(f"Invalid projector_resolution: {resolution!r}") from exc

        # Optional metadata
        projector_id = str(ctx.data.get("projector_id", "projector_0"))
        camera_id = str(ctx.data.get("camera_id", "camera_0"))
        surface_id = str(ctx.data.get("surface_id", ""))

        calibrated_camera = ctx.data.get("calibrated_camera")
        camera_matrix = None
        distortion_coeffs = None
        image_size = None
        if calibrated_camera is not None:
            try:
                camera_matrix = calibrated_camera.camera_matrix
                distortion_coeffs = calibrated_camera.distortion_coeffs
                image_size = calibrated_camera.image_size
            except AttributeError:
                pass

        try:
            result = solve_calibration(
                recs,
                projector_resolution=resolution,
                projector_id=projector_id,
                camera_id=camera_id,
                surface_id=surface_id,
                camera_matrix=camera_matrix,
                distortion_coeffs=distortion_coeffs,
                image_size=image_size,
            )
        except CalibrationSolveError as exc:
            raise StageError(str(exc)) from exc

        # Optional refinement
        if self._enable_refine:
            from projectionai.calibration.solver import refine_calibration

            result, was_refined, before, after = refine_calibration(
                recs, result, rms_threshold=self._refine_threshold
            )
            if was_refined:
                _logger.info("Calibration refined: RMS %.3f → %.3f", before, after)

        ctx.data["calibration_result"] = result
        _logger.info(
            "Calibration solved: fx=%.1f fy=%.1f RMS=%.3f planes=%d",
            float(result.projector_intrinsics[0, 0]),
            float(result.projector_intrinsics[1, 1]),
            result.reprojection_error,
            len(recs),
        )
        return ctx
