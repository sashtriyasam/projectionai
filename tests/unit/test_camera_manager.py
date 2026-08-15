"""Tests for the camera manager and mock camera backend."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from projectionai.core.errors import (
    CameraDisconnectedError,
    CameraNotFoundError,
    CameraUnavailableError,
    ManagerNotInitializedError,
)
from projectionai.core.events import (
    CameraClosed,
    CameraDisconnected,
    CameraFrameCaptured,
    CameraListRefreshed,
    CameraOpened,
    CameraPropertyChanged,
    JobCompleted,
    JobQueued,
    JobStarted,
)
from projectionai.infrastructure.camera import MockCameraProvider
from projectionai.managers.camera_manager import CameraManager
from projectionai.managers.job_manager import JobManager, JobStatus
from projectionai.services.camera import CameraProperty, CameraProviderFactory, Frame
from tests.conftest import FakeEventBus


async def _flush() -> None:
    """Yield control so fire-and-forget emit tasks can run."""
    await asyncio.sleep(0)


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until *predicate* returns True or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for condition")


def _frame_event_count(event_bus: FakeEventBus) -> int:
    return sum(isinstance(ev, CameraFrameCaptured) for ev in event_bus.emitted)


@pytest.fixture
async def camera_manager(
    event_bus: FakeEventBus,
) -> AsyncIterator[CameraManager]:
    """Return an initialized CameraManager backed by mock cameras."""
    manager = CameraManager(event_bus, provider=MockCameraProvider(camera_count=2))
    await manager.initialize()
    yield manager
    await manager.shutdown()


@pytest.fixture
async def job_manager(event_bus: FakeEventBus) -> AsyncIterator[JobManager]:
    """Return an initialized JobManager."""
    manager = JobManager(event_bus)
    await manager.initialize()
    yield manager
    await manager.shutdown()


# -- Factory and provider ---------------------------------------------------


def test_factory_has_registered_providers() -> None:
    available = CameraProviderFactory.available()
    assert "mock" in available
    assert "opencv" in available


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown camera provider"):
        CameraProviderFactory.create("nonexistent")


# -- Enumeration ------------------------------------------------------------


async def test_initialize_emits_list_refreshed(
    camera_manager: CameraManager, event_bus: FakeEventBus
) -> None:
    await _flush()
    event_bus.assert_event_emitted(CameraListRefreshed)
    events = [ev for ev in event_bus.emitted if isinstance(ev, CameraListRefreshed)]
    assert events[-1].camera_ids == ("mock-0", "mock-1")


async def test_list_cameras_returns_mock_devices(
    camera_manager: CameraManager,
) -> None:
    infos = await camera_manager.list_cameras()
    assert [info.camera_id for info in infos] == ["mock-0", "mock-1"]
    assert all(info.backend == "mock" for info in infos)


# -- Lifecycle --------------------------------------------------------------


async def test_open_camera_is_idempotent_and_emits_event(
    camera_manager: CameraManager, event_bus: FakeEventBus
) -> None:
    camera = await camera_manager.open_camera("mock-0")
    again = await camera_manager.open_camera("mock-0")
    await _flush()
    event_bus.assert_event_emitted(CameraOpened)
    assert again is camera
    assert camera_manager.is_open("mock-0")


async def test_close_camera_emits_event_and_releases(
    camera_manager: CameraManager, event_bus: FakeEventBus
) -> None:
    await camera_manager.open_camera("mock-0")
    await camera_manager.close_camera("mock-0")
    await _flush()
    event_bus.assert_event_emitted(CameraClosed)
    assert not camera_manager.is_open("mock-0")
    await camera_manager.close_camera("mock-0")


# -- Capture ----------------------------------------------------------------


async def test_capture_frame_returns_rgb_frame(
    camera_manager: CameraManager, event_bus: FakeEventBus
) -> None:
    await camera_manager.open_camera("mock-0")
    frame = await camera_manager.capture_frame("mock-0")
    await _flush()
    assert isinstance(frame, Frame)
    assert frame.camera_id == "mock-0"
    assert frame.frame_number == 1
    assert frame.width == 640
    assert frame.height == 480
    assert frame.image.shape == (480, 640, 3)
    assert frame.image.dtype == np.uint8
    event_bus.assert_event_emitted(CameraFrameCaptured)


async def test_capture_frame_requires_open_camera(
    camera_manager: CameraManager,
) -> None:
    with pytest.raises(CameraNotFoundError, match="not open"):
        await camera_manager.capture_frame("mock-0")


async def test_capture_frames_differ_and_number_increases(
    camera_manager: CameraManager,
) -> None:
    await camera_manager.open_camera("mock-0")
    first = await camera_manager.capture_frame("mock-0")
    second = await camera_manager.capture_frame("mock-0")
    assert second.frame_number == 2
    assert not np.array_equal(first.image, second.image)


async def test_start_stop_capture_emits_frames(
    camera_manager: CameraManager, event_bus: FakeEventBus
) -> None:
    await camera_manager.start_capture("mock-0", fps=60)
    await _wait_for(lambda: _frame_event_count(event_bus) >= 2)
    await camera_manager.stop_capture("mock-0")
    await _flush()
    frames = [ev for ev in event_bus.emitted if isinstance(ev, CameraFrameCaptured)]
    assert len(frames) >= 2
    numbers = [ev.frame_number for ev in frames]
    assert numbers == sorted(numbers)


async def test_disconnect_emits_event_and_stops_loop(
    camera_manager: CameraManager,
    event_bus: FakeEventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await camera_manager.open_camera("mock-0")

    async def _boom() -> Frame:
        raise CameraDisconnectedError("device unplugged")

    monkeypatch.setattr(camera, "capture", _boom)
    await camera_manager.start_capture("mock-0", fps=30)
    await _wait_for(
        lambda: any(isinstance(ev, CameraDisconnected) for ev in event_bus.emitted)
    )
    await _wait_for(lambda: "mock-0" not in camera_manager._capture_tasks)
    event_bus.assert_event_emitted(CameraDisconnected)


# -- Frame subscribers ------------------------------------------------------


def _noop_frame_handler(_frame: Frame) -> None:
    """Frame handler that ignores its input (used for registry checks)."""


def _exploding_frame_handler(_frame: Frame) -> None:
    """Frame handler that raises, to prove failures are isolated."""
    raise RuntimeError("handler boom")


async def test_subscribe_frames_receives_captured_frames(
    camera_manager: CameraManager,
) -> None:
    received: list[Frame] = []
    camera_manager.subscribe_frames("mock-0", received.append)
    await camera_manager.start_capture("mock-0", fps=60)
    await _wait_for(lambda: len(received) >= 2)
    await camera_manager.stop_capture("mock-0")
    assert all(frame.camera_id == "mock-0" for frame in received)
    numbers = [frame.frame_number for frame in received]
    assert numbers == sorted(numbers)


async def test_unsubscribe_stops_frame_delivery(
    camera_manager: CameraManager,
) -> None:
    received: list[Frame] = []
    camera_manager.subscribe_frames("mock-0", received.append)
    await camera_manager.start_capture("mock-0", fps=30)
    await _wait_for(lambda: len(received) >= 2)
    camera_manager.unsubscribe_frames("mock-0", received.append)
    count = len(received)
    await asyncio.sleep(0.15)
    assert len(received) == count
    await camera_manager.stop_capture("mock-0")


async def test_subscribe_same_handler_is_idempotent(
    camera_manager: CameraManager,
) -> None:
    camera_manager.subscribe_frames("mock-0", _noop_frame_handler)
    camera_manager.subscribe_frames("mock-0", _noop_frame_handler)
    assert camera_manager.frame_subscriber_count("mock-0") == 1


async def test_unsubscribe_unknown_camera_is_noop(
    camera_manager: CameraManager,
) -> None:
    camera_manager.unsubscribe_frames("mock-9", _noop_frame_handler)
    assert camera_manager.frame_subscriber_count("mock-9") == 0


async def test_failing_handler_does_not_stop_capture_loop(
    camera_manager: CameraManager,
) -> None:
    received: list[Frame] = []
    camera_manager.subscribe_frames("mock-0", _exploding_frame_handler)
    camera_manager.subscribe_frames("mock-0", received.append)
    await camera_manager.start_capture("mock-0", fps=30)
    await _wait_for(lambda: len(received) >= 2)
    await camera_manager.stop_capture("mock-0")
    assert len(received) >= 2


async def test_close_camera_removes_subscribers(
    camera_manager: CameraManager,
) -> None:
    camera_manager.subscribe_frames("mock-0", _noop_frame_handler)
    assert camera_manager.frame_subscriber_count("mock-0") == 1
    await camera_manager.close_camera("mock-0")
    assert camera_manager.frame_subscriber_count("mock-0") == 0


async def test_subscribe_requires_initialized_manager(
    event_bus: FakeEventBus,
) -> None:
    manager = CameraManager(event_bus, provider=MockCameraProvider(camera_count=1))
    with pytest.raises(ManagerNotInitializedError):
        manager.subscribe_frames("mock-0", _noop_frame_handler)


# -- Properties -------------------------------------------------------------


async def test_property_roundtrip(
    camera_manager: CameraManager, event_bus: FakeEventBus
) -> None:
    await camera_manager.open_camera("mock-0")
    assert await camera_manager.set_property("mock-0", CameraProperty.FOCUS, 12.0)
    await _flush()
    event_bus.assert_event_emitted(CameraPropertyChanged)
    value = await camera_manager.get_property("mock-0", CameraProperty.FOCUS)
    assert value == 12.0


# -- Job integration --------------------------------------------------------


async def test_snapshot_runs_as_job(
    event_bus: FakeEventBus, job_manager: JobManager
) -> None:
    manager = CameraManager(
        event_bus, job_manager=job_manager, provider=MockCameraProvider(camera_count=1)
    )
    await manager.initialize()
    await manager.open_camera("mock-0")

    info = manager.snapshot("mock-0")
    assert info is not None
    assert info.job_id.startswith("snapshot-")

    def _job_completed() -> bool:
        current = job_manager.get_job(info.job_id)
        return current is not None and current.status == JobStatus.COMPLETED

    await _wait_for(_job_completed)
    completed = job_manager.get_job(info.job_id)
    assert completed is not None
    assert isinstance(completed.result, Frame)
    assert completed.result.camera_id == "mock-0"
    event_bus.assert_events_emitted(JobQueued, JobStarted, JobCompleted)


# -- Shutdown ---------------------------------------------------------------


async def test_shutdown_closes_open_cameras(event_bus: FakeEventBus) -> None:
    manager = CameraManager(event_bus, provider=MockCameraProvider(camera_count=1))
    await manager.initialize()
    await manager.open_camera("mock-0")
    await manager.shutdown()
    await _flush()
    event_bus.assert_events_emitted(CameraOpened, CameraClosed)
    assert not manager.is_open("mock-0")


# -- Mock camera backend ----------------------------------------------------


async def test_mock_camera_closed_capture_raises() -> None:
    provider = MockCameraProvider(camera_count=1)
    camera = await provider.open("mock-0")
    await camera.close()
    with pytest.raises(CameraUnavailableError, match="not open"):
        await camera.capture()


async def test_mock_camera_unknown_id_raises() -> None:
    provider = MockCameraProvider(camera_count=1)
    with pytest.raises(CameraNotFoundError, match="Unknown mock camera"):
        await provider.open("mock-9")
