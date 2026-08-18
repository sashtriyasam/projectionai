"""Tests for DevicesViewModel live preview.

Covers frame streaming, drop counting, error mapping, and the
event-driven teardown on disconnect/close. Uses a real
:class:`~projectionai.core.events.EventBus` (unlike the fake used
elsewhere) so the view model's event listeners actually fire.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from projectionai.core.errors import CameraCaptureError, CameraDisconnectedError
from projectionai.core.events import CameraClosed, CameraDisconnected, EventBus
from projectionai.infrastructure.camera import MockCameraProvider
from projectionai.managers.camera_manager import CameraManager
from projectionai.services.camera import Frame
from projectionai.ui.viewmodels.devices import DevicesViewModel


async def _flush() -> None:
    """Yield control so fire-and-forget tasks can run."""
    await asyncio.sleep(0)


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until *predicate* returns True or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for condition")


def _frame(camera_id: str, frame_number: int, value: int = 0) -> Frame:
    """Return a 640x480 RGB frame with a constant pixel value."""
    image = np.full((480, 640, 3), value, dtype=np.uint8)
    return Frame(
        image=image,
        timestamp=time.monotonic(),
        camera_id=camera_id,
        frame_number=frame_number,
    )


@pytest.fixture
async def setup() -> AsyncIterator[tuple[EventBus, CameraManager, DevicesViewModel]]:
    """Return a real event bus, an initialized manager, and a bound view model."""
    event_bus = EventBus()
    manager = CameraManager(event_bus, provider=MockCameraProvider(camera_count=2))
    await manager.initialize()
    vm = DevicesViewModel(manager)
    yield event_bus, manager, vm
    await manager.shutdown()


async def test_initial_state_is_idle(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, _, vm = setup
    assert vm.preview_camera_id is None
    assert vm.latest_frame() is None
    assert vm.preview_error() is None
    assert vm.frame_count == 0
    assert vm.dropped_count == 0
    assert not vm.is_previewing("mock-0")


async def test_start_preview_streams_frames(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, _, vm = setup
    assert await vm.start_preview("mock-0") is True
    assert vm.is_previewing("mock-0")
    await _wait_for(lambda: vm.frame_count >= 2)
    frame = vm.latest_frame()
    assert frame is not None
    assert frame.camera_id == "mock-0"
    assert frame.width == 640
    assert frame.height == 480
    await vm.stop_preview()


async def test_start_preview_same_camera_is_noop(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, manager, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)
    assert manager.frame_subscriber_count("mock-0") == 1
    assert await vm.start_preview("mock-0") is True
    assert vm.is_previewing("mock-0")
    assert manager.frame_subscriber_count("mock-0") == 1
    assert vm.preview_error() is None
    await vm.stop_preview()


async def test_start_preview_unknown_camera_fails(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, _, vm = setup
    assert await vm.start_preview("mock-9") is False
    assert vm.preview_error() == "Camera not found"
    assert vm.preview_camera_id is None


async def test_switch_camera_stops_previous(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, manager, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 2)
    assert await vm.start_preview("mock-1") is True
    assert vm.is_previewing("mock-1")
    assert not vm.is_previewing("mock-0")
    assert manager.frame_subscriber_count("mock-0") == 0
    await _wait_for(lambda: vm.frame_count >= 2)
    await vm.stop_preview()


async def test_stop_preview_stops_capture_and_resets(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, manager, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)
    await vm.stop_preview()
    assert vm.preview_camera_id is None
    assert vm.latest_frame() is None
    assert vm.frame_count == 0
    assert vm.dropped_count == 0
    assert manager.frame_subscriber_count("mock-0") == 0


async def test_stop_preview_when_idle_is_noop(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, _, vm = setup
    await vm.stop_preview()
    assert vm.preview_camera_id is None


async def test_drop_count_tracks_unrendered_frames(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    _, _, vm = setup
    # Drive _on_frame directly for deterministic drop accounting.
    vm._preview_camera_id = "mock-0"
    vm._reset_preview_state()
    vm._on_frame(_frame("mock-0", 1))
    vm._on_frame(_frame("mock-0", 2))
    vm._on_frame(_frame("mock-0", 3))
    assert vm.dropped_count == 2  # frames 1 and 2 were replaced unrendered
    vm.mark_frame_rendered(3)
    vm._on_frame(_frame("mock-0", 4))
    assert vm.dropped_count == 2  # frame 3 was rendered before being replaced
    vm._on_frame(_frame("mock-0", 5))
    assert vm.dropped_count == 3  # frame 4 was replaced unrendered
    assert vm.frame_count == 5
    frame = vm.latest_frame()
    assert frame is not None
    assert frame.frame_number == 5


async def test_disconnect_clears_preview(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, manager, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)

    camera = await manager.open_camera("mock-0")

    async def _boom() -> Frame:
        raise CameraDisconnectedError("device unplugged")

    monkeypatch.setattr(camera, "capture", _boom)
    await _wait_for(lambda: vm.preview_camera_id is None)
    assert vm.preview_error() == "Camera disconnected"
    assert vm.latest_frame() is None


async def test_close_clears_preview(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    event_bus, _, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)
    await event_bus.emit(CameraClosed(camera_id="mock-0"))
    await _flush()
    assert vm.preview_camera_id is None
    assert vm.preview_error() is None


async def test_unrelated_disconnect_is_ignored(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    event_bus, _, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)
    await event_bus.emit(CameraDisconnected(camera_id="mock-1"))
    await _flush()
    assert vm.is_previewing("mock-0")
    await vm.stop_preview()


async def test_capture_failure_sets_preview_error_and_recovers(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, manager, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)

    camera = await manager.open_camera("mock-0")
    original_capture = camera.capture
    fail = {"value": True}

    async def _flaky() -> Frame:
        if fail["value"]:
            raise CameraCaptureError("sensor hiccup")
        return await original_capture()

    monkeypatch.setattr(camera, "capture", _flaky)
    await _wait_for(lambda: vm.preview_error() == "Frame capture failed")
    assert vm.is_previewing("mock-0")
    fail["value"] = False
    await _wait_for(lambda: vm.preview_error() is None)
    await vm.stop_preview()


async def test_shutdown_unsubscribes_from_camera_events(
    setup: tuple[EventBus, CameraManager, DevicesViewModel],
) -> None:
    event_bus, _, vm = setup
    assert await vm.start_preview("mock-0") is True
    await _wait_for(lambda: vm.frame_count >= 1)
    vm.shutdown()
    vm.shutdown()  # idempotent
    await event_bus.emit(CameraDisconnected(camera_id="mock-0"))
    await _flush()
    assert vm.preview_camera_id == "mock-0"
    assert vm.preview_error() is None
    await vm.stop_preview()
