"""Integration tests for projector calibration through CalibrationManager."""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from projectionai.calibration import CalibrationManager
from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.types import CalibrationStatus
from projectionai.core.errors import CameraCaptureError
from projectionai.core.events import (
    CalibrationComplete,
    CalibrationFailed,
    CalibrationProgress,
    CalibrationStarted,
)
from projectionai.infrastructure.projector_calibration.gray_code import (
    GrayCodeProjectorCalibration,
)
from projectionai.managers.job_manager import JobManager, JobStatus
from projectionai.services.camera import Frame
from tests.conftest import FakeEventBus
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_PLANE,
    SYNTHETIC_PROJECTOR_RESOLUTION,
    render_capture,
    synthetic_sequence,
)

_NUM_PATTERNS = len(synthetic_sequence().patterns)


class FakeProjector:
    """Duck-typed PatternProjector that records what it displays."""

    def __init__(self) -> None:
        self.shown: np.ndarray | None = None
        self.show_count = 0
        self.hide_count = 0

    async def show(self, image: np.ndarray) -> None:
        self.shown = image.copy()
        self.show_count += 1

    async def hide(self) -> None:
        self.shown = None
        self.hide_count += 1


class FakeCameraManager:
    """Duck-typed CameraManager that renders the currently shown pattern."""

    def __init__(self, projector: FakeProjector, fail_on: int | None = None) -> None:
        self._projector = projector
        self._fail_on = fail_on
        self._captures = 0

    async def capture_frame(self, camera_id: str) -> Frame:
        if self._fail_on is not None and self._captures >= self._fail_on:
            raise CameraCaptureError("device disconnected")
        if self._projector.shown is None:
            raise CameraCaptureError("no pattern projected")
        image = render_capture(self._projector.shown)
        frame = Frame(
            image=image,
            timestamp=float(self._captures),
            camera_id=camera_id,
            frame_number=self._captures,
        )
        self._captures += 1
        return frame


def _manager(
    event_bus: FakeEventBus,
    *,
    fail_on: int | None = None,
    job_manager: JobManager | None = None,
) -> tuple[CalibrationManager, FakeProjector]:
    projector = FakeProjector()
    camera_manager = FakeCameraManager(projector, fail_on=fail_on)
    mgr = CalibrationManager(
        event_bus, camera_manager=camera_manager, job_manager=job_manager
    )
    return mgr, projector


async def _run(mgr: CalibrationManager, projector: FakeProjector) -> CalibrationSession:
    return await mgr.run_projector_calibration(
        "cam-0",
        GrayCodeProjectorCalibration(),
        projector,
        projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
        camera=SYNTHETIC_CAMERA,
        surface=SYNTHETIC_PLANE,
        settle_seconds=0.0,
    )


async def _wait_for_event(
    event_bus: FakeEventBus,
    event_type: type,
    timeout: float = 5.0,
) -> None:
    """Poll *event_bus* until *event_type* is emitted or *timeout* elapses.

    Manager events are emitted fire-and-forget on background tasks, so
    callers must yield to the loop until the event is observed.
    """
    deadline = time.monotonic() + timeout
    while not any(isinstance(e, event_type) for e in event_bus.emitted):
        if time.monotonic() >= deadline:
            pytest.fail(f"Timed out waiting for {event_type.__name__}")
        await asyncio.sleep(0.01)


class TestRunProjectorCalibration:
    async def test_successful_run_persists_projector_result(
        self, event_bus: FakeEventBus
    ) -> None:
        mgr, projector = _manager(event_bus)
        session = await _run(mgr, projector)

        # Progress/complete events are emitted fire-and-forget; wait for
        # the completion event before asserting on result/event state.
        await _wait_for_event(event_bus, CalibrationComplete)

        assert session.result is not None
        assert session.result.success
        assert session.state.status == CalibrationStatus.COMPLETED
        assert projector.show_count == _NUM_PATTERNS
        assert projector.hide_count == 1

        pose = session.result.data.projector_pose["projector-1"]
        assert len(pose["projector_matrix"]) == 3
        assert len(pose["pose"]) == 4
        assert pose["width"] == SYNTHETIC_PROJECTOR_RESOLUTION[0]
        assert pose["height"] == SYNTHETIC_PROJECTOR_RESOLUTION[1]
        # fx/fy recovered from the synthetic scene.
        assert pose["projector_matrix"][0][0] == pytest.approx(2000.0, rel=0.01)
        assert session.result.data.reprojection_error < 1.0
        assert session.result.data.confidence > 0.5
        assert session.result.data.num_samples > 0.8 * (
            SYNTHETIC_PROJECTOR_RESOLUTION[0] * SYNTHETIC_PROJECTOR_RESOLUTION[1]
        )

        event_bus.assert_event_emitted(CalibrationStarted)
        event_bus.assert_event_emitted(CalibrationProgress)
        event_bus.assert_event_emitted(CalibrationComplete)
        assert not any(isinstance(e, CalibrationFailed) for e in event_bus.emitted)

    async def test_successful_run_writes_history_entry(
        self, event_bus: FakeEventBus
    ) -> None:
        mgr, projector = _manager(event_bus)
        session = await _run(mgr, projector)
        assert len(session.history.entries) == 1
        assert session.history.entries[0].result.success
        assert session.history.entries[0].session_name == "Projector Calibration"

    async def test_capture_failure_fails_session(self, event_bus: FakeEventBus) -> None:
        mgr, projector = _manager(event_bus, fail_on=0)
        session = await _run(mgr, projector)
        assert session.result is not None
        assert not session.result.success
        assert session.state.status == CalibrationStatus.FAILED
        event_bus.assert_event_emitted(CalibrationFailed)
        assert not any(isinstance(e, CalibrationComplete) for e in event_bus.emitted)

    async def test_invalid_resolution_raises(self, event_bus: FakeEventBus) -> None:
        mgr, projector = _manager(event_bus)
        with pytest.raises(ValueError, match="positive"):
            await mgr.run_projector_calibration(
                "cam-0",
                GrayCodeProjectorCalibration(),
                projector,
                projector_resolution=(0, 720),
                camera=SYNTHETIC_CAMERA,
                surface=SYNTHETIC_PLANE,
            )

    async def test_missing_camera_manager_raises(self, event_bus: FakeEventBus) -> None:
        mgr = CalibrationManager(event_bus)
        with pytest.raises(RuntimeError, match="no camera manager"):
            await mgr.run_projector_calibration(
                "cam-0",
                GrayCodeProjectorCalibration(),
                FakeProjector(),
                projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
                camera=SYNTHETIC_CAMERA,
                surface=SYNTHETIC_PLANE,
            )


class TestEnqueueProjectorCalibration:
    async def test_returns_none_without_job_manager(
        self, event_bus: FakeEventBus
    ) -> None:
        mgr, projector = _manager(event_bus)
        assert (
            mgr.enqueue_projector_calibration(
                "cam-0",
                GrayCodeProjectorCalibration(),
                projector,
                projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
                camera=SYNTHETIC_CAMERA,
                surface=SYNTHETIC_PLANE,
            )
            is None
        )

    async def test_enqueues_and_completes_background_job(
        self, event_bus: FakeEventBus
    ) -> None:
        job_mgr = JobManager(event_bus)
        await job_mgr.initialize()
        try:
            mgr, projector = _manager(event_bus, job_manager=job_mgr)
            info = mgr.enqueue_projector_calibration(
                "cam-0",
                GrayCodeProjectorCalibration(),
                projector,
                projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
                camera=SYNTHETIC_CAMERA,
                surface=SYNTHETIC_PLANE,
            )
            assert info is not None
            assert info.job_id.startswith("projector-calibration-")

            deadline = time.monotonic() + 20.0
            job = job_mgr.get_job(info.job_id)
            while (
                job is not None
                and job.status in (JobStatus.PENDING, JobStatus.RUNNING)
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.05)
                job = job_mgr.get_job(info.job_id)

            assert job is not None
            assert job.status == JobStatus.COMPLETED
            assert job.result is not None
            assert job.result.result is not None
            assert job.result.result.success
        finally:
            await job_mgr.shutdown()
