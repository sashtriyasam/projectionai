"""OpenCV-backed camera provider wrapping ``cv2.VideoCapture``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import cv2
import numpy as np

from projectionai.core.errors import (
    CameraCaptureError,
    CameraDisconnectedError,
    CameraNotFoundError,
    CameraOpenError,
    CameraUnavailableError,
)
from projectionai.services.camera import (
    Camera,
    CameraInfo,
    CameraProperty,
    CameraProvider,
    CameraProviderFactory,
    Frame,
)

_logger = logging.getLogger(__name__)

_MAX_PROBE_INDICES = 8
_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 720
_DEFAULT_FPS = 30

_PROPERTY_IDS: dict[CameraProperty, int] = {
    CameraProperty.FOCUS: cv2.CAP_PROP_FOCUS,
    CameraProperty.EXPOSURE: cv2.CAP_PROP_EXPOSURE,
    CameraProperty.GAIN: cv2.CAP_PROP_GAIN,
    CameraProperty.WHITE_BALANCE: cv2.CAP_PROP_WB_TEMPERATURE,
}

_READ_DRAIN_TIMEOUT = 2.0


class OpenCVCamera(Camera):
    """Camera backed by a ``cv2.VideoCapture`` device."""

    def __init__(self, info: CameraInfo, source: int | str) -> None:
        self._info = info
        self._source: int | str = source
        self._cap: cv2.VideoCapture | None = None
        self._frame_number: int = 0
        self._width: int = _DEFAULT_WIDTH
        self._height: int = _DEFAULT_HEIGHT
        self._fps: int = _DEFAULT_FPS
        self._pending_properties: dict[CameraProperty, float] = {}
        self._read_future: asyncio.Future[tuple[bool, cv2.typing.MatLike]] | None = None

    @property
    def info(self) -> CameraInfo:
        return self._info

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    async def open(self) -> None:
        if self.is_open:
            return
        cap = cv2.VideoCapture(self._source)
        if not cap.isOpened():
            cap.release()
            raise CameraOpenError(f"Could not open camera {self._source!r}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        for prop, value in self._pending_properties.items():
            cap.set(_PROPERTY_IDS[prop], value)
        self._pending_properties.clear()
        self._cap = cap
        _logger.debug(
            "Opened camera %s (source=%r)", self._info.camera_id, self._source
        )

    async def close(self) -> None:
        future = self._read_future
        if future is not None and not future.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(future), timeout=_READ_DRAIN_TIMEOUT
                )
            except (asyncio.CancelledError, Exception):
                _logger.warning(
                    "Camera %s read still in flight after %.1fs; releasing anyway",
                    self._info.camera_id,
                    _READ_DRAIN_TIMEOUT,
                )
        if future is not None and future.done() and not future.cancelled():
            # A wedged read may still fail after the drain; consume its
            # exception so the loop does not warn about an unretrieved one.
            with contextlib.suppress(asyncio.InvalidStateError):
                future.exception()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._read_future = None

    async def capture(self) -> Frame:
        cap = self._require_cap()
        previous = self._read_future
        if previous is not None and not previous.done():
            with contextlib.suppress(Exception):
                await asyncio.shield(previous)
            cap = self._require_cap()
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, cap.read)
        self._read_future = future
        try:
            ok, frame = await asyncio.shield(future)
        except asyncio.CancelledError:
            # The executor read keeps running; close() drains it with a
            # bounded wait before releasing the capture.
            raise
        self._read_future = None
        if not ok or frame is None:
            if not cap.isOpened():
                raise CameraDisconnectedError(
                    f"Camera {self._info.camera_id!r} disconnected"
                )
            raise CameraCaptureError(
                f"Failed to capture frame from camera {self._info.camera_id!r}"
            )
        self._frame_number += 1
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.uint8)
        return Frame(
            image=rgb,
            timestamp=time.monotonic(),
            camera_id=self._info.camera_id,
            frame_number=self._frame_number,
        )

    async def set_resolution(self, width: int, height: int) -> bool:
        self._width = width
        self._height = height
        if not self.is_open:
            return True
        cap = self._require_cap()
        return bool(
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            and cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        )

    async def set_fps(self, fps: int) -> bool:
        self._fps = fps
        if not self.is_open:
            return True
        cap = self._require_cap()
        return bool(cap.set(cv2.CAP_PROP_FPS, fps))

    async def get_property(self, prop: CameraProperty) -> float | None:
        if not self.is_open:
            return None
        cap = self._require_cap()
        value = cap.get(_PROPERTY_IDS[prop])
        return value if value >= 0 else None

    async def set_property(self, prop: CameraProperty, value: float) -> bool:
        if prop not in _PROPERTY_IDS:
            return False
        if not self.is_open:
            self._pending_properties[prop] = value
            return True
        cap = self._require_cap()
        return bool(cap.set(_PROPERTY_IDS[prop], value))

    def _require_cap(self) -> cv2.VideoCapture:
        if self._cap is None or not self._cap.isOpened():
            raise CameraUnavailableError(f"Camera {self._info.camera_id!r} is not open")
        return self._cap


class OpenCVCameraProvider(CameraProvider):
    """Discovers and opens OpenCV-compatible camera devices."""

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        def _probe() -> list[CameraInfo]:
            found: list[CameraInfo] = []
            for index in range(_MAX_PROBE_INDICES):
                cap = cv2.VideoCapture(index)
                try:
                    if not cap.isOpened():
                        continue
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or _DEFAULT_WIDTH
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or _DEFAULT_HEIGHT
                    backend = cap.getBackendName()
                    found.append(
                        CameraInfo(
                            camera_id=str(index),
                            name=f"Camera {index} ({backend})",
                            backend="opencv",
                            interface="usb",
                            max_resolution=(width, height),
                            supported_properties=tuple(_PROPERTY_IDS),
                        )
                    )
                finally:
                    cap.release()
            return found

        return tuple(await asyncio.to_thread(_probe))

    async def open(self, camera_id: str) -> Camera:
        try:
            index = int(camera_id)
        except ValueError as exc:
            raise CameraNotFoundError(f"Unknown camera id: {camera_id!r}") from exc
        info = CameraInfo(
            camera_id=camera_id,
            name=f"Camera {index}",
            backend="opencv",
            interface="usb",
            max_resolution=(_DEFAULT_WIDTH, _DEFAULT_HEIGHT),
            supported_properties=tuple(_PROPERTY_IDS),
        )
        camera = OpenCVCamera(info, source=index)
        await camera.open()
        return camera


CameraProviderFactory.register("opencv", OpenCVCameraProvider)
