"""Mock camera provider generating deterministic synthetic RGB frames.

Used by tests and demos when no physical camera is available. The
frames are animated (gradient plus a moving bar) so consecutive
captures are visibly distinct.
"""

from __future__ import annotations

import logging
import time

import numpy as np
from numpy.typing import NDArray

from projectionai.core.errors import CameraNotFoundError, CameraUnavailableError
from projectionai.services.camera import (
    Camera,
    CameraInfo,
    CameraProperty,
    CameraProvider,
    CameraProviderFactory,
    Frame,
)

_logger = logging.getLogger(__name__)

_DEFAULT_WIDTH = 640
_DEFAULT_HEIGHT = 480
_ALL_PROPERTIES = tuple(CameraProperty)


def _make_info(index: int) -> CameraInfo:
    return CameraInfo(
        camera_id=f"mock-{index}",
        name=f"Mock Camera {index}",
        backend="mock",
        interface="virtual",
        max_resolution=(_DEFAULT_WIDTH, _DEFAULT_HEIGHT),
        supported_properties=_ALL_PROPERTIES,
    )


class MockCamera(Camera):
    """Generates an animated RGB test pattern."""

    def __init__(
        self,
        info: CameraInfo,
        *,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
    ) -> None:
        self._info = info
        self._width: int = width
        self._height: int = height
        self._open: bool = False
        self._frame_number: int = 0
        self._properties: dict[CameraProperty, float] = {
            CameraProperty.FOCUS: 0.0,
            CameraProperty.EXPOSURE: 0.0,
            CameraProperty.GAIN: 1.0,
            CameraProperty.WHITE_BALANCE: 5500.0,
        }

    @property
    def info(self) -> CameraInfo:
        return self._info

    @property
    def is_open(self) -> bool:
        return self._open

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False
        self._frame_number = 0

    async def capture(self) -> Frame:
        if not self._open:
            raise CameraUnavailableError(f"Camera {self._info.camera_id!r} is not open")
        self._frame_number += 1
        ts = time.monotonic()
        return Frame(
            image=self._synthesize(),
            timestamp=ts,
            timestamp_ns=time.monotonic_ns(),
            camera_id=self._info.camera_id,
            frame_number=self._frame_number,
        )

    async def set_resolution(self, width: int, height: int) -> bool:
        self._width = width
        self._height = height
        return True

    async def set_fps(self, fps: int) -> bool:
        return True

    async def get_property(self, prop: CameraProperty) -> float | None:
        return self._properties.get(prop)

    async def set_property(self, prop: CameraProperty, value: float) -> bool:
        if prop not in _ALL_PROPERTIES:
            return False
        self._properties[prop] = value
        return True

    def _synthesize(self) -> NDArray[np.uint8]:
        width = max(self._width, 1)
        height = max(self._height, 1)
        x = np.arange(width, dtype=np.int32)
        y = np.arange(height, dtype=np.int32)
        xx, yy = np.meshgrid(x, y)
        red = (xx * 255 // (width - 1)).astype(np.uint8)
        green = (yy * 255 // (height - 1)).astype(np.uint8)
        blue = np.full((height, width), 128, dtype=np.uint8)
        bar_start = (self._frame_number * 4) % width
        bar = np.zeros((height, width), dtype=np.uint8)
        bar[:, bar_start : bar_start + 24] = 255
        frame = np.stack([red, green, blue], axis=-1)
        frame[:, :, 2] = np.maximum(frame[:, :, 2], bar)
        return frame


class MockCameraProvider(CameraProvider):
    """Provider exposing a fixed set of mock cameras ("mock-0", "mock-1", ...)."""

    def __init__(self, camera_count: int = 2) -> None:
        self._camera_count = camera_count
        self._cameras: dict[str, MockCamera] = {}

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        return tuple(_make_info(index) for index in range(self._camera_count))

    async def open(self, camera_id: str) -> Camera:
        try:
            index = int(camera_id.removeprefix("mock-"))
        except ValueError as exc:
            raise CameraNotFoundError(f"Unknown mock camera id: {camera_id!r}") from exc
        if index >= self._camera_count:
            raise CameraNotFoundError(f"Unknown mock camera id: {camera_id!r}")
        camera = self._cameras.get(camera_id)
        if camera is None:
            camera = MockCamera(_make_info(index))
            self._cameras[camera_id] = camera
        await camera.open()
        return camera


CameraProviderFactory.register("mock", MockCameraProvider)
