"""Automatic calibration using ICP and structured light."""

from __future__ import annotations

import logging
from typing import override

from projectionai.domain.calibration import CalibrationPoint, CalibrationResult
from projectionai.domain.geometry import Mesh
from projectionai.services.calibration import CalibrationGuide, Calibrator

_logger = logging.getLogger(__name__)


class AutomaticCalibrator(Calibrator):
    """Automatic calibration using Iterative Closest Point (ICP)
    registration between structured-light scans and the reference mesh."""

    @override
    async def initialize(self) -> None: ...

    @override
    async def shutdown(self) -> None: ...

    @override
    async def start_calibration(
        self,
        reference_mesh: Mesh | None = None,
    ) -> CalibrationGuide:
        raise NotImplementedError

    @override
    async def add_correspondence(
        self,
        image_point: tuple[float, float],
        model_point: tuple[float, float, float],
        confidence: float = 1.0,
    ) -> CalibrationGuide:
        raise NotImplementedError

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
        raise NotImplementedError
