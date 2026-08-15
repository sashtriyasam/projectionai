"""Tests for the CalibrationViewModel camera-calibration run wrapper.

The wrapper turns an async ``CalibrationManager.run_camera_calibration``
call into observable state (``is_calibration_running`` /
``last_run_status``) plus the board-corner overlay accessor
(``calibration_overlay``). A fake manager with a scripted session is
used so success, failure, and exception paths are covered without a
real camera or OpenCV board detection.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from projectionai.ui.viewmodels.calibration import CalibrationViewModel


class _Result:
    """Minimal stand-in for CalibrationResult."""

    def __init__(self, success: bool, error_message: str | None = None) -> None:
        self.success = success
        self.error_message = error_message


class _Session:
    """Minimal stand-in for CalibrationSession."""

    def __init__(
        self,
        result: _Result | None,
        detections: list[Any] | None = None,
    ) -> None:
        self.result = result
        self.state = _State(detections or [])


class _State:
    """Minimal stand-in for session state."""

    def __init__(self, detections: list[Any]) -> None:
        self.intermediate_results: dict[str, Any] = {"detections": detections}


class _Detection:
    """Minimal stand-in for BoardDetection."""

    def __init__(self, corners: np.ndarray, image_size: tuple[int, int]) -> None:
        self.corners = corners
        self.image_size = image_size


class _CameraManager:
    def __init__(self, camera_ids: tuple[str, ...]) -> None:
        self._camera_ids = camera_ids

    def open_camera_ids(self) -> tuple[str, ...]:
        return self._camera_ids


class _FakeCalibrationManager:
    """Duck-typed stand-in for CalibrationManager."""

    def __init__(
        self,
        session: _Session | None,
        *,
        error: Exception | None = None,
        camera_ids: tuple[str, ...] = (),
    ) -> None:
        self._session = session
        self._error = error
        self.camera_manager = _CameraManager(camera_ids)
        self.called_with: dict[str, Any] = {}

    async def run_camera_calibration(
        self,
        camera_id: str,
        algorithm: Any,
        *,
        session_name: str,
        num_frames: int,
    ) -> _Session:
        self.called_with = {
            "camera_id": camera_id,
            "algorithm": algorithm,
            "session_name": session_name,
            "num_frames": num_frames,
        }
        if self._error is not None:
            raise self._error
        session = self._session
        assert session is not None
        return session


def _corners() -> np.ndarray:
    return np.array([[10, 20], [30, 40], [50, 60]], dtype=np.float32)


class TestRunCameraCalibration:
    async def test_success_sets_status_and_overlay(self) -> None:
        detection = _Detection(_corners(), (640, 480))
        session = _Session(_Result(success=True), [detection])
        vm = CalibrationViewModel(
            _FakeCalibrationManager(session, camera_ids=("cam-0",))
        )

        returned = await vm.run_camera_calibration("cam-0")

        assert returned is session
        assert vm.last_run_status() == "Calibration complete"
        assert vm.is_calibration_running() is False
        assert vm.calibration_overlay() == (
            [(10, 20), (30, 40), (50, 60)],
            (640, 480),
        )

    async def test_failure_with_error_message(self) -> None:
        session = _Session(_Result(success=False, error_message="bad board"))
        vm = CalibrationViewModel(
            _FakeCalibrationManager(session, camera_ids=("cam-0",))
        )

        await vm.run_camera_calibration("cam-0")

        assert vm.last_run_status() == "Calibration failed: bad board"
        assert vm.is_calibration_running() is False
        assert vm.calibration_overlay() == (None, None)

    async def test_failure_without_result_message(self) -> None:
        session = _Session(_Result(success=False, error_message=None))
        vm = CalibrationViewModel(
            _FakeCalibrationManager(session, camera_ids=("cam-0",))
        )

        await vm.run_camera_calibration("cam-0")

        assert vm.last_run_status() == "Calibration failed: no board detected"

    async def test_no_result_session_fails(self) -> None:
        session = _Session(None)
        vm = CalibrationViewModel(
            _FakeCalibrationManager(session, camera_ids=("cam-0",))
        )

        await vm.run_camera_calibration("cam-0")

        assert vm.last_run_status() == "Calibration failed: no board detected"
        assert vm.calibration_overlay() == (None, None)

    async def test_exception_sets_failed_status_and_raises(self) -> None:
        vm = CalibrationViewModel(
            _FakeCalibrationManager(
                None, error=ValueError("boom"), camera_ids=("cam-0",)
            )
        )

        with pytest.raises(RuntimeError, match="did not produce a session"):
            await vm.run_camera_calibration("cam-0")

        assert vm.last_run_status() == "Calibration failed: boom"
        assert vm.is_calibration_running() is False

    async def test_overlay_empty_before_run(self) -> None:
        vm = CalibrationViewModel(_FakeCalibrationManager(None, camera_ids=("cam-0",)))
        assert vm.calibration_overlay() == (None, None)

    async def test_open_camera_ids(self) -> None:
        vm = CalibrationViewModel(
            _FakeCalibrationManager(None, camera_ids=("cam-0", "cam-1"))
        )
        assert vm.open_camera_ids() == ("cam-0", "cam-1")

    async def test_open_camera_ids_empty(self) -> None:
        vm = CalibrationViewModel(_FakeCalibrationManager(None))
        assert vm.open_camera_ids() == ()


class TestStatusTransitions:
    async def test_running_flag_cleared_after_exception(self) -> None:
        vm = CalibrationViewModel(
            _FakeCalibrationManager(
                None, error=RuntimeError("kaboom"), camera_ids=("cam-0",)
            )
        )
        with pytest.raises(RuntimeError):
            await vm.run_camera_calibration("cam-0")
        assert vm.is_calibration_running() is False
