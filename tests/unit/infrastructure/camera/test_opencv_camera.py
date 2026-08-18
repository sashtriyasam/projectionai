"""Tests for OpenCVCamera capture lifecycle and error mapping."""

from __future__ import annotations

import asyncio
import threading

import numpy as np
import pytest

pytest.importorskip("cv2")

from projectionai.core.errors import (
    CameraCaptureError,
    CameraDisconnectedError,
)
from projectionai.infrastructure.camera.opencv_camera import OpenCVCamera
from projectionai.services.camera import CameraInfo


class _FakeCap:
    """Duck-typed cv2.VideoCapture stand-in with a controllable read()."""

    def __init__(self) -> None:
        self.released = False
        self.fail_read = False
        self.disconnect_on_fail = False
        self.read_started = threading.Event()
        self._release_read = threading.Event()

    def read(self) -> tuple[bool, np.ndarray | None]:
        self.read_started.set()
        if not self._release_read.wait(timeout=5):
            raise AssertionError("read() was never released")
        if self.fail_read:
            if self.disconnect_on_fail:
                self.released = True
            return (False, None)
        return (True, np.zeros((480, 640, 3), dtype=np.uint8))

    def isOpened(self) -> bool:
        return not self.released

    def release(self) -> None:
        self.released = True


def _camera(cap: _FakeCap) -> OpenCVCamera:
    camera = OpenCVCamera.__new__(OpenCVCamera)
    camera._info = CameraInfo(
        camera_id="0",
        name="Camera 0",
        backend="opencv",
        interface="usb",
        max_resolution=(640, 480),
        supported_properties=(),
    )
    camera._source = 0
    camera._cap = cap
    camera._frame_number = 0
    camera._width = 640
    camera._height = 480
    camera._fps = 30
    camera._pending_properties = {}
    return camera


async def test_capture_returns_frame() -> None:
    cap = _FakeCap()
    cap._release_read.set()
    camera = _camera(cap)

    frame = await camera.capture()

    assert frame.camera_id == "0"
    assert frame.frame_number == 1
    assert frame.width == 640
    assert frame.height == 480
    assert frame.image.shape == (480, 640, 3)


async def test_cancel_during_read_joins_thread_before_close() -> None:
    cap = _FakeCap()
    camera = _camera(cap)

    task = asyncio.create_task(camera.capture())
    for _ in range(200):
        if cap.read_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert cap.read_started.is_set()
    task.cancel()
    _, pending = await asyncio.wait({task}, timeout=0.05)
    assert task in pending  # read thread still blocked; capture() joins it
    cap._release_read.set()
    done, _ = await asyncio.wait({task}, timeout=2)
    assert task in done
    assert task.cancelled()
    await camera.close()
    assert cap.released


async def test_read_failure_raises_capture_error() -> None:
    cap = _FakeCap()
    cap.fail_read = True
    cap._release_read.set()
    camera = _camera(cap)

    with pytest.raises(CameraCaptureError):
        await camera.capture()

    assert not cap.released
    assert camera.is_open


async def test_disconnect_during_read_raises_disconnected() -> None:
    cap = _FakeCap()
    cap.fail_read = True
    cap.disconnect_on_fail = True
    cap._release_read.set()
    camera = _camera(cap)

    with pytest.raises(CameraDisconnectedError):
        await camera.capture()

    assert not camera.is_open
