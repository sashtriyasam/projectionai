"""OpenCV-based vision pipeline implementation."""

from __future__ import annotations

import logging
from typing import override

import cv2

from projectionai.domain.geometry import Mesh, Pose
from projectionai.domain.surface import DetectedSurface
from projectionai.services.vision import (
    CalibrationData,
    CameraFrame,
    ScanResult,
    VisionPipeline,
)

_logger = logging.getLogger(__name__)


class OpenCVPipeline(VisionPipeline):
    """Vision pipeline using OpenCV for feature detection, pose estimation,
    and surface detection."""

    def __init__(self) -> None:
        self._initialized: bool = False

    @override
    async def initialize(self) -> None:
        _logger.debug("OpenCV pipeline initialized (version %s)", cv2.__version__)
        self._initialized = True

    @override
    async def shutdown(self) -> None:
        self._initialized = False

    @override
    async def process_frame(self, frame: CameraFrame) -> ScanResult:
        return ScanResult()

    @override
    async def detect_surfaces(
        self,
        frame: CameraFrame,
    ) -> tuple[DetectedSurface, ...]:
        return ()

    @override
    async def estimate_pose(
        self,
        frame: CameraFrame,
        reference_mesh: Mesh,
    ) -> Pose | None:
        return None

    @override
    async def compute_calibration(
        self,
        frames: tuple[CameraFrame, ...],
        pattern_size: tuple[int, int],
    ) -> CalibrationData:
        raise NotImplementedError
