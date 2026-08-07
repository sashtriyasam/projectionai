"""Pattern capture session — projects patterns and captures frames.

Orchestrates the physical projection/capture loop of a structured light
sequence: each pattern is displayed on the projector, the camera is
given a short settle period, and a frame is captured. The session
guarantees the projector is blanked when the loop finishes (success or
failure).

The session is framework-agnostic: it depends only on a minimal
``FrameSource`` protocol (satisfied by ``CameraManager``) and a
``PatternProjector`` protocol (any display backend).
"""

from __future__ import annotations

import asyncio
import logging

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.core.errors import CameraError
from projectionai.services.camera import Frame
from projectionai.services.projector_calibration import (
    FrameSource,
    PatternProjector,
    PatternSequence,
    ProjectorCalibrationError,
)

_logger = logging.getLogger(__name__)

_DEFAULT_SETTLE_SECONDS = 0.1
_DEFAULT_CAPTURE_TIMEOUT = 10.0


class PatternCaptureSession:
    """Orchestrates projecting a pattern sequence while capturing frames.

    Args:
        frame_source: Object providing ``capture_frame`` (e.g.
            ``CameraManager``).
        camera_id: Camera to capture from.
        projector: Device that displays the patterns.
        settle_seconds: Delay after each pattern display before
            capturing, letting the display/camera stabilise.
        capture_timeout: Per-frame capture timeout in seconds.
    """

    def __init__(
        self,
        frame_source: FrameSource,
        camera_id: str,
        projector: PatternProjector,
        settle_seconds: float = _DEFAULT_SETTLE_SECONDS,
        capture_timeout: float = _DEFAULT_CAPTURE_TIMEOUT,
    ) -> None:
        self._frame_source = frame_source
        self._camera_id = camera_id
        self._projector = projector
        self._settle_seconds = settle_seconds
        self._capture_timeout = capture_timeout

    async def capture_sequence(
        self, sequence: PatternSequence
    ) -> tuple[NDArray[np.uint8], ...]:
        """Project *sequence* and capture one grayscale frame per pattern.

        The projector is blanked when the loop finishes, even on error.

        Returns:
            Captured grayscale frames in the sequence's projection order.

        Raises:
            ProjectorCalibrationError: If a capture fails or times out.
        """
        frames: list[NDArray[np.uint8]] = []
        try:
            for pattern in sequence.patterns:
                await self._projector.show(pattern.image)
                await asyncio.sleep(self._settle_seconds)
                frame = await self._capture()
                image = frame.image
                if image.ndim == 2:
                    gray = np.asarray(image, dtype=np.uint8)
                else:
                    gray = np.asarray(
                        cv2.cvtColor(image, cv2.COLOR_RGB2GRAY),
                        dtype=np.uint8,
                    )
                frames.append(gray)
        finally:
            await self._projector.hide()
        return tuple(frames)

    async def __aenter__(self) -> PatternCaptureSession:
        """Enter the session (no-op; projector is blanked on exit)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Blank the projector."""
        await self._projector.hide()

    # -- Internal -----------------------------------------------------------

    async def _capture(self) -> Frame:
        try:
            return await asyncio.wait_for(
                self._frame_source.capture_frame(self._camera_id),
                timeout=self._capture_timeout,
            )
        except CameraError as exc:
            raise ProjectorCalibrationError(f"Frame capture failed: {exc}") from exc
        except TimeoutError as exc:
            raise ProjectorCalibrationError(
                f"Frame capture timed out after {self._capture_timeout}s"
            ) from exc
