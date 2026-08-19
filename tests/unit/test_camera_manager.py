"""Tests for the camera manager and mock camera backend."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from projectionai.core.errors import (
    CameraCaptureError,
    CameraDisconnectedError,
    CameraNotFoundError,
    CameraUnavailableError,
    ManagerNotInitializedError,
)
from projectionai.core.events import (
    CameraCaptureFailed,
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
from projectionai.infrastructure.camera import MockCamera, MockCameraProvider
from projectionai.managers.camera_manager import CameraManager
from projectionai.managers.job_manager import JobManager, JobStatus
from projectionai.services.camera import (
    Camera,
    CameraInfo,
    CameraProperty,
    CameraProviderFactory,
    Frame,
)
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


class _SlowProvider:
    """CameraProvider whose open() suspends until released (race tests)."""

    def __init__(self) -> None:
        self.open_calls = 0
        self.release = asyncio.Event()
        self.last_camera: MockCamera | None = None

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        return ()

    async def open(self, camera_id: str) -> Camera:
        self.open_calls += 1
        await self.release.wait()
        info = CameraInfo(
            camera_id=camera_id,
            name=f"Camera {camera_id}",
            backend="mock",
            interface="virtual",
            max_resolution=(640, 480),
        )
        camera = MockCamera(info)
        await camera.open()
        self.last_camera = camera
        return camera


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
    CameraProviderFactory.create("mock")
    CameraProviderFactory.create("opencv")
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
    original_capture = camera.capture
    fail = {"value": True}

    async def _flaky() -> Frame:
        if fail["value"]:
            raise CameraDisconnectedError("device unplugged")
        return await original_capture()

    monkeypatch.setattr(camera, "capture", _flaky)
    await camera_manager.start_capture("mock-0", fps=30)
    await _wait_for(
        lambda: any(isinstance(ev, CameraDisconnected) for ev in event_bus.emitted)
    )
    event_bus.assert_event_emitted(CameraDisconnected)
    # The loop has exited; restarting must start a fresh loop (regression:
    # a finished-but-not-yet-popped task used to block the restart).
    fail["value"] = False
    await camera_manager.start_capture("mock-0", fps=30)
    frames_before = _frame_event_count(event_bus)
    await _wait_for(lambda: _frame_event_count(event_bus) >= frames_before + 2)
    await camera_manager.stop_capture("mock-0")


async def test_capture_error_emits_failed_event_and_recovers(
    camera_manager: CameraManager,
    event_bus: FakeEventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = await camera_manager.open_camera("mock-0")
    original_capture = camera.capture
    fail = {"value": True}

    async def _flaky() -> Frame:
        if fail["value"]:
            raise CameraCaptureError("sensor hiccup")
        return await original_capture()

    monkeypatch.setattr(camera, "capture", _flaky)
    await camera_manager.start_capture("mock-0", fps=30)
    await _wait_for(
        lambda: any(isinstance(ev, CameraCaptureFailed) for ev in event_bus.emitted)
    )
    failed = [ev for ev in event_bus.emitted if isinstance(ev, CameraCaptureFailed)]
    assert failed[-1].camera_id == "mock-0"
    assert "sensor hiccup" in failed[-1].reason
    fail["value"] = False
    frames_before = _frame_event_count(event_bus)
    await _wait_for(lambda: _frame_event_count(event_bus) >= frames_before + 2)
    await camera_manager.stop_capture("mock-0")


async def test_concurrent_start_capture_single_loop(
    camera_manager: CameraManager,
    event_bus: FakeEventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent start_capture calls must not spawn two loops.

    A slow set_fps widens the interleaving window so both calls reach
    the in-flight check before either registers its task.
    """
    camera = await camera_manager.open_camera("mock-0")

    async def _slow_set_fps(fps: int) -> bool:
        await asyncio.sleep(0.05)
        return True

    monkeypatch.setattr(camera, "set_fps", _slow_set_fps)
    await asyncio.gather(
        camera_manager.start_capture("mock-0", fps=30),
        camera_manager.start_capture("mock-0", fps=30),
    )
    await _wait_for(lambda: _frame_event_count(event_bus) >= 2)
    await camera_manager.stop_capture("mock-0")
    count = _frame_event_count(event_bus)
    await asyncio.sleep(0.15)
    assert _frame_event_count(event_bus) == count


# -- Startup/shutdown races -------------------------------------------------


async def test_concurrent_open_camera_opens_once(event_bus: FakeEventBus) -> None:
    """Two concurrent open_camera calls must open the device exactly once."""
    provider = _SlowProvider()
    manager = CameraManager(event_bus, provider=provider)
    await manager.initialize()
    try:
        first = asyncio.create_task(manager.open_camera("mock-0"))
        second = asyncio.create_task(manager.open_camera("mock-0"))
        for _ in range(200):
            if provider.open_calls >= 1:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)  # give the second call time to reach open
        assert provider.open_calls == 1  # second call blocked on the lock

        provider.release.set()
        cameras = await asyncio.gather(first, second)
        assert cameras[0] is cameras[1]
        assert manager.is_open("mock-0")
    finally:
        await manager.shutdown()


async def test_stop_capture_during_open_wins(event_bus: FakeEventBus) -> None:
    """A start_capture suspended in provider.open must not register a
    capture loop after stop_capture returns (no zombie loop)."""
    provider = _SlowProvider()
    manager = CameraManager(event_bus, provider=provider)
    await manager.initialize()
    try:
        start = asyncio.create_task(manager.start_capture("mock-0", fps=30))
        for _ in range(200):
            if provider.open_calls >= 1:
                break
            await asyncio.sleep(0.01)
        assert provider.open_calls == 1

        stop = asyncio.create_task(manager.stop_capture("mock-0"))
        await asyncio.sleep(0.05)
        assert not stop.done()  # waiting on the per-camera lock

        provider.release.set()
        await start
        await asyncio.wait_for(stop, timeout=2)

        count = _frame_event_count(event_bus)
        await asyncio.sleep(0.15)
        assert _frame_event_count(event_bus) == count  # no zombie loop
    finally:
        await manager.shutdown()


async def test_shutdown_during_open_raises_and_closes_camera(
    event_bus: FakeEventBus,
) -> None:
    """Shutdown while start_capture is suspended in provider.open must
    reject the late registration and close the freshly opened camera."""
    provider = _SlowProvider()
    manager = CameraManager(event_bus, provider=provider)
    await manager.initialize()
    start = asyncio.create_task(manager.start_capture("mock-0", fps=30))
    for _ in range(200):
        if provider.open_calls >= 1:
            break
        await asyncio.sleep(0.01)
    assert provider.open_calls == 1

    shutdown = asyncio.create_task(manager.shutdown())
    await asyncio.sleep(0.05)

    provider.release.set()
    with pytest.raises(ManagerNotInitializedError):
        await start
    await asyncio.wait_for(shutdown, timeout=2)

    assert provider.last_camera is not None
    assert not provider.last_camera.is_open  # opened camera was closed again
    assert not manager.is_open("mock-0")


async def test_operations_after_shutdown_raise(event_bus: FakeEventBus) -> None:
    """Manager calls after shutdown must fail fast (no partial states)."""
    manager = CameraManager(event_bus, provider=MockCameraProvider(camera_count=1))
    await manager.initialize()
    await manager.shutdown()

    with pytest.raises(ManagerNotInitializedError):
        await manager.open_camera("mock-0")
    with pytest.raises(ManagerNotInitializedError):
        await manager.start_capture("mock-0")


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


async def test_capture_frame_delivers_to_subscribers(
    camera_manager: CameraManager,
) -> None:
    """Direct single-frame captures must reach subscribe_frames() handlers."""
    received: list[Frame] = []
    camera_manager.subscribe_frames("mock-0", received.append)
    await camera_manager.open_camera("mock-0")

    frame = await camera_manager.capture_frame("mock-0")

    assert received == [frame]
    assert camera_manager.frame_subscriber_count("mock-0") == 1


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
    received: list[Frame] = []
    manager.subscribe_frames("mock-0", received.append)

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
    # One-shot snapshots do not stream to frame subscribers.
    assert received == []
    assert not any(isinstance(ev, CameraFrameCaptured) for ev in event_bus.emitted)


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
