"""Integration tests for camera calibration through CalibrationManager."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest

from projectionai.calibration import CalibrationManager
from projectionai.calibration.types import CalibrationStatus
from projectionai.core.errors import CameraCaptureError
from projectionai.core.events import (
    CalibrationComplete,
    CalibrationFailed,
    CalibrationProgress,
    CalibrationStarted,
)
from projectionai.infrastructure.calibration.chessboard import (
    ChessboardCalibrationAlgorithm,
)
from projectionai.managers.job_manager import JobManager, JobStatus
from projectionai.services.camera import Frame
from tests.conftest import FakeEventBus
from tests.unit.calibration._synthetic_board import SYNTHETIC_CONFIG, synthetic_frame


class FakeCameraManager:
    """Duck-typed CameraManager that serves synthetic board frames."""

    def __init__(
        self,
        frames: list[Frame] | None = None,
        fail_on: int | None = None,
    ) -> None:
        self._frames = frames or [synthetic_frame(i) for i in range(9)]
        self._fail_on = fail_on
        self._captures = 0

    async def capture_frame(self, camera_id: str) -> Frame:
        if self._fail_on is not None and self._captures >= self._fail_on:
            raise CameraCaptureError("device disconnected")
        frame = self._frames[self._captures % len(self._frames)]
        self._captures += 1
        return frame


class TestRunCameraCalibration:
    async def test_successful_run_persists_intrinsics(
        self, event_bus: FakeEventBus
    ) -> None:
        algorithm = ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        mgr = CalibrationManager(event_bus, camera_manager=FakeCameraManager())
        session = await mgr.run_camera_calibration("cam-0", algorithm, num_frames=9)

        # Progress/complete events are emitted fire-and-forget; yield to the
        # event loop once so the scheduled emissions land before we assert.
        await asyncio.sleep(0)

        assert session.result is not None
        assert session.result.success
        assert session.state.status == CalibrationStatus.COMPLETED

        pose = session.result.data.camera_pose["cam-0"]
        assert len(pose["camera_matrix"]) == 3
        assert len(pose["distortion_coeffs"]) == 5
        assert pose["width"] == 1280
        assert pose["height"] == 720
        assert session.result.data.reprojection_error > 0.0
        assert session.result.data.num_samples == 9

        event_bus.assert_event_emitted(CalibrationStarted)
        event_bus.assert_event_emitted(CalibrationProgress)
        event_bus.assert_event_emitted(CalibrationComplete)
        assert not any(isinstance(e, CalibrationFailed) for e in event_bus.emitted)

    async def test_successful_run_writes_history_entry(
        self, event_bus: FakeEventBus
    ) -> None:
        mgr = CalibrationManager(event_bus, camera_manager=FakeCameraManager())
        session = await mgr.run_camera_calibration(
            "cam-0", ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG), num_frames=9
        )
        assert len(session.history.entries) == 1
        assert session.history.entries[0].result.success
        assert session.history.entries[0].session_name == "Camera Calibration"

    async def test_result_exports_via_opencv_exporter(
        self, event_bus: FakeEventBus, tmp_path: Path
    ) -> None:
        mgr = CalibrationManager(event_bus, camera_manager=FakeCameraManager())
        session = await mgr.run_camera_calibration(
            "cam-0", ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG), num_frames=9
        )
        path = tmp_path / "intrinsics.json"
        data = mgr.export(session, "open_cv", path)

        assert data["camera_matrix"][0][0] == pytest.approx(1000.0, rel=0.02)
        assert data["image_width"] == 1280
        assert data["image_height"] == 720
        exported = json.loads(path.read_text(encoding="utf-8"))
        assert exported["camera_matrix"][0][0] == pytest.approx(1000.0, rel=0.02)

    async def test_capture_failure_fails_session(self, event_bus: FakeEventBus) -> None:
        mgr = CalibrationManager(event_bus, camera_manager=FakeCameraManager(fail_on=0))
        session = await mgr.run_camera_calibration(
            "cam-0", ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
        )
        assert session.result is not None
        assert not session.result.success
        assert session.state.status == CalibrationStatus.FAILED
        event_bus.assert_event_emitted(CalibrationFailed)
        assert not any(isinstance(e, CalibrationComplete) for e in event_bus.emitted)

    async def test_no_board_views_fails_session(self, event_bus: FakeEventBus) -> None:
        noise = [
            Frame(
                image=np.full((720, 1280, 3), 128, np.uint8),
                timestamp=float(index),
                camera_id="cam-0",
                frame_number=index,
            )
            for index in range(9)
        ]
        mgr = CalibrationManager(
            event_bus, camera_manager=FakeCameraManager(frames=noise)
        )
        session = await mgr.run_camera_calibration(
            "cam-0", ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG), num_frames=9
        )
        assert session.result is not None
        assert not session.result.success
        event_bus.assert_event_emitted(CalibrationFailed)

    async def test_missing_camera_manager_raises(self, event_bus: FakeEventBus) -> None:
        mgr = CalibrationManager(event_bus)
        with pytest.raises(RuntimeError, match="no camera manager"):
            await mgr.run_camera_calibration(
                "cam-0", ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
            )


class TestEnqueueCameraCalibration:
    async def test_returns_none_without_job_manager(
        self, event_bus: FakeEventBus
    ) -> None:
        mgr = CalibrationManager(event_bus, camera_manager=FakeCameraManager())
        assert (
            mgr.enqueue_camera_calibration(
                "cam-0", ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG)
            )
            is None
        )

    async def test_enqueues_and_completes_background_job(
        self, event_bus: FakeEventBus
    ) -> None:
        job_mgr = JobManager(event_bus)
        await job_mgr.initialize()
        try:
            mgr = CalibrationManager(
                event_bus, camera_manager=FakeCameraManager(), job_manager=job_mgr
            )
            info = mgr.enqueue_camera_calibration(
                "cam-0",
                ChessboardCalibrationAlgorithm(SYNTHETIC_CONFIG),
                num_frames=9,
            )
            assert info is not None
            assert info.job_id.startswith("camera-calibration-")

            deadline = time.monotonic() + 15.0
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
