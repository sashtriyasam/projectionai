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
        self.read_calls = 0

    def read(self) -> tuple[bool, np.ndarray | None]:
        self.read_calls += 1
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
    camera._read_future = None
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


async def test_cancel_during_read_returns_promptly_and_close_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling capture() must not block on a wedged read thread.

    The executor read keeps running after cancellation; close() drains
    it with a bounded wait before releasing the capture (regression:
    the old join-on-cancel hung shutdown forever when cap.read()
    blocked).
    """
    monkeypatch.setattr(
        "projectionai.infrastructure.camera.opencv_camera._READ_DRAIN_TIMEOUT",
        0.05,
    )
    cap = _FakeCap()
    camera = _camera(cap)

    task = asyncio.create_task(camera.capture())
    for _ in range(200):
        if cap.read_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert cap.read_started.is_set()

    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=0.1)
    assert task in done  # prompt cancellation: no join on the wedged read
    assert task.cancelled()

    # close() must still release the capture despite the wedged read.
    await asyncio.wait_for(camera.close(), timeout=1)
    assert cap.released
    assert not camera.is_open

    # Let the wedged read finish so the executor thread can exit.
    cap._release_read.set()


async def test_concurrent_captures_serialize_reads() -> None:
    """A second capture() must not start a read while the first is in flight."""
    cap = _FakeCap()
    camera = _camera(cap)

    first = asyncio.create_task(camera.capture())
    for _ in range(200):
        if cap.read_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert cap.read_started.is_set()
    assert cap.read_calls == 1

    second = asyncio.create_task(camera.capture())
    await asyncio.sleep(0.05)
    assert cap.read_calls == 1  # second capture serialized behind first read

    cap._release_read.set()
    frame1 = await first
    frame2 = await second
    assert frame1.frame_number == 1
    assert frame2.frame_number == 2
    assert cap.read_calls == 2


async def test_close_drains_in_flight_read() -> None:
    """close() must wait for an in-flight read before releasing."""
    cap = _FakeCap()
    camera = _camera(cap)

    capture_task = asyncio.create_task(camera.capture())
    for _ in range(200):
        if cap.read_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert cap.read_started.is_set()

    close_task = asyncio.create_task(camera.close())
    await asyncio.sleep(0.05)
    assert not close_task.done()  # still draining the wedged read
    assert not cap.released

    cap._release_read.set()
    frame = await capture_task
    assert frame.frame_number == 1
    await asyncio.wait_for(close_task, timeout=1)
    assert cap.released
    assert not camera.is_open


async def test_close_bounded_drain_on_wedged_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close() must not hang forever when the read never returns."""
    monkeypatch.setattr(
        "projectionai.infrastructure.camera.opencv_camera._READ_DRAIN_TIMEOUT",
        0.05,
    )
    cap = _FakeCap()
    camera = _camera(cap)

    task = asyncio.create_task(camera.capture())
    for _ in range(200):
        if cap.read_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert cap.read_started.is_set()

    # The read never returns: close() must time out and release anyway.
    await asyncio.wait_for(camera.close(), timeout=1)
    assert cap.released
    assert not camera.is_open

    task.cancel()
    await asyncio.wait({task}, timeout=1)
    # The executor read is still wedged; let it finish so the thread exits.
    cap._release_read.set()


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
