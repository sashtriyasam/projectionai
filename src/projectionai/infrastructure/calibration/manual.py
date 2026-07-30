"""Manual calibration implementation."""

from __future__ import annotations

import logging
from typing import override

from projectionai.domain.calibration import CalibrationPoint, CalibrationResult
from projectionai.domain.geometry import Mesh
from projectionai.services.calibration import CalibrationGuide, Calibrator

_logger = logging.getLogger(__name__)


class ManualCalibrator(Calibrator):
    """Manual point-correspondence calibration."""

    def __init__(self) -> None:
        self._points: list[CalibrationPoint] = []

    @override
    async def initialize(self) -> None:
        _logger.debug("Manual calibrator initialized")

    @override
    async def shutdown(self) -> None:
        self._points.clear()

    @override
    async def start_calibration(
        self,
        reference_mesh: Mesh | None = None,
    ) -> CalibrationGuide:
        self._points.clear()
        return CalibrationGuide(
            points=(), instructions="Click corresponding points", step=0, total_steps=4
        )

    @override
    async def add_correspondence(
        self,
        image_point: tuple[float, float],
        model_point: tuple[float, float, float],
        confidence: float = 1.0,
    ) -> CalibrationGuide:
        pt = CalibrationPoint(
            image_x=image_point[0],
            image_y=image_point[1],
            world_x=model_point[0],
            world_y=model_point[1],
            world_z=model_point[2],
            confidence=confidence,
        )
        self._points.append(pt)
        return CalibrationGuide(
            points=tuple(self._points),
            step=len(self._points),
            total_steps=4,
        )

    @override
    async def compute_calibration(self) -> CalibrationResult:
        raise NotImplementedError

    @override
    async def auto_calibrate(
        self,
        source_mesh: Mesh,
        target_mesh: Mesh,
        max_iterations: int = 100,
    ) -> CalibrationResult:
        raise NotImplementedError

    @override
    async def refine_calibration(
        self,
        current: CalibrationResult,
        observations: tuple[CalibrationPoint, ...],
    ) -> CalibrationResult:
        return current
