"""Reconstruction pipeline stage.

Consumes a canonical ``CorrespondenceSet`` (with calibrated camera and
surface plane) and produces a domain ``ReconstructionResult`` through the
configured reconstruction backend (reference NumPy or native C++).
"""

from __future__ import annotations

import logging

from projectionai.calibration.pipeline import CalibrationStage, StageContext, StageError
from projectionai.calibration.types import CalibrationStageType
from projectionai.domain.calibration_session import CorrespondenceSet
from projectionai.services.projector_calibration import CalibratedCamera, SurfacePlane
from projectionai.services.reconstruction import (
    BackendMode,
    ReconstructionBackend,
    ReconstructionBackendFactory,
    ReconstructionError,
)

_logger = logging.getLogger(__name__)


class ReconstructionStage(CalibrationStage):
    """Triangulate correspondences into a ReconstructionResult.

    Reads ``ctx.data["correspondence_set"]``, ``ctx.data["calibrated_camera"]``,
    and ``ctx.data["surface_plane"]``; writes ``ctx.data["reconstruction"]``.
    """

    def __init__(
        self,
        backend: ReconstructionBackend | None = None,
        mode: BackendMode = BackendMode.REFERENCE,
        max_points: int = 20_000,
    ) -> None:
        super().__init__(CalibrationStageType.RECONSTRUCTION)
        self.name = "reconstruction"
        self._backend = backend or ReconstructionBackendFactory.create(mode)
        self._max_points = max_points

    @property
    def backend(self) -> ReconstructionBackend:
        return self._backend

    async def execute(self, ctx: StageContext) -> StageContext:
        correspondences = ctx.data.get("correspondence_set")
        camera = ctx.data.get("calibrated_camera")
        surface = ctx.data.get("surface_plane")

        if not isinstance(correspondences, CorrespondenceSet):
            msg = "No correspondence_set in context — run decode before reconstruction"
            raise StageError(msg)
        if not isinstance(camera, CalibratedCamera):
            msg = "No calibrated_camera in context"
            raise StageError(msg)
        if not isinstance(surface, SurfacePlane):
            msg = "No surface_plane in context"
            raise StageError(msg)

        try:
            result = self._backend.reconstruct(
                correspondences, camera, surface, self._max_points
            )
        except ReconstructionError as exc:
            raise StageError(str(exc)) from exc

        ctx.data["reconstruction"] = result
        _logger.debug(
            "Reconstruction (%s): %d points",
            self._backend.name,
            len(result.points_camera),
        )
        return ctx
