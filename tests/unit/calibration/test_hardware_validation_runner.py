"""End-to-end tests for the hardware validation runner.

Drives the full 9-step workflow with a synthetic scene: a stub camera
renders what a calibrated camera would see of each projected gray-code
pattern (via ``tests.unit.calibration._synthetic_scene``) and a stub
projector records every shown pattern. The runner must produce a
complete ``COMPLETED`` report whose metrics match the known ground truth
(RMS < 1 px, coverage > 0.8, corner error < 2 px) — proving the real
hardware workflow is correctly orchestrated without any physical device.
"""

from __future__ import annotations

import asyncio
import os
import time

import numpy as np
import pytest

from projectionai.calibration.hardware_validation.models import (
    CalibrationReport,
    HardwareValidationError,
)
from projectionai.calibration.hardware_validation.runner import ValidationRunner
from projectionai.calibration.types import CalibrationStatus
from projectionai.infrastructure.projector_calibration.estimators import (
    CameraProjectorTransform,
)
from projectionai.services.camera import Camera, CameraInfo, CameraProperty, Frame
from projectionai.services.projector_calibration import SurfacePlane
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_PLANE,
    SYNTHETIC_PROJECTOR_MATRIX,
    SYNTHETIC_PROJECTOR_RESOLUTION,
    projector_pose_matrix,
    render_capture,
)

# The offscreen Qt platform keeps the runner's display enumeration and
# any stray window creation headless on every OS, including CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_W, _H = SYNTHETIC_PROJECTOR_RESOLUTION


class _StubProjector:
    """PatternProjector stub that records every shown pattern."""

    def __init__(self) -> None:
        self.shown: list[np.ndarray] = []
        self.current: np.ndarray | None = None
        self.hidden = False

    async def show(self, image: np.ndarray) -> None:
        self.shown.append(image)
        self.current = image

    async def hide(self) -> None:
        self.hidden = True
        self.current = None


class _DummyCamera(Camera):
    """Minimal Camera satisfying the ABC; the runner never uses it."""

    @property
    def info(self) -> CameraInfo:
        return CameraInfo(camera_id="dummy", name="dummy")

    @property
    def is_open(self) -> bool:
        return True

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def capture(self) -> Frame:
        raise NotImplementedError

    async def set_resolution(self, width: int, height: int) -> bool:
        return True

    async def set_fps(self, fps: int) -> bool:
        return True

    async def get_property(self, prop: CameraProperty) -> float | None:
        return None

    async def set_property(self, prop: CameraProperty, value: float) -> bool:
        return False


class _StubCamera:
    """CameraAccess stub rendering the synthetic scene for each pattern."""

    def __init__(
        self, projector: _StubProjector, camera_id: str = "synthetic-0"
    ) -> None:
        self._projector = projector
        self.info = CameraInfo(
            camera_id=camera_id,
            name="Synthetic Camera",
            backend="mock",
            model="Synthetic",
        )
        self.frame_number = 0
        self.opened: list[str] = []
        self.closed: list[str] = []

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        return (self.info,)

    async def open_camera(self, camera_id: str) -> Camera:
        self.opened.append(camera_id)
        return _DummyCamera()

    async def capture_frame(self, camera_id: str) -> Frame:
        if self._projector.current is None:
            raise AssertionError("capture_frame called before any pattern shown")
        self.frame_number += 1
        return Frame(
            image=render_capture(self._projector.current),
            timestamp=time.monotonic(),
            camera_id=camera_id,
            frame_number=self.frame_number,
        )

    async def close_camera(self, camera_id: str) -> None:
        self.closed.append(camera_id)


class _BlockingCamera(_StubCamera):
    """Camera that blocks in capture until an event is released."""

    def __init__(self, projector: _StubProjector, gate: asyncio.Event) -> None:
        super().__init__(projector)
        self._gate = gate
        self.capture_started = asyncio.Event()

    async def capture_frame(self, camera_id: str) -> Frame:
        self.capture_started.set()
        await self._gate.wait()
        return await super().capture_frame(camera_id)


class _EmptyCamera(_StubCamera):
    """Camera enumeration returns no devices."""

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        return ()


class _FlippableCamera(_EmptyCamera):
    """Camera enumeration that can stop reporting devices mid-test."""

    def __init__(self, projector: _StubProjector, available: bool = True) -> None:
        super().__init__(projector)
        self.available = available

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        if self.available:
            return (self.info,)
        return ()


class _RotatingCamera(_StubCamera):
    """Camera enumeration whose available devices change between runs."""

    def __init__(self, projector: _StubProjector) -> None:
        super().__init__(projector, camera_id="camera-0")
        self.ids: list[str] = ["camera-0"]

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        return tuple(
            CameraInfo(
                camera_id=camera_id,
                name=f"camera-{camera_id}",
                backend="mock",
                model="Synthetic",
            )
            for camera_id in self.ids
        )


def _runner(
    camera: _StubCamera,
    projector: _StubProjector,
    *,
    settle_seconds: float = 0.0,
    camera_id: str | None = None,
    expected_corner_points: np.ndarray | None = None,
    expected_corner_pixels: np.ndarray | None = None,
) -> ValidationRunner:
    return ValidationRunner(
        camera,
        lambda _info: SYNTHETIC_CAMERA,
        SYNTHETIC_PLANE,
        camera_id=camera_id,
        projector=projector,
        projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
        expected_corner_points=expected_corner_points,
        expected_corner_pixels=expected_corner_pixels,
        settle_seconds=settle_seconds,
    )


class TestRunnerHappyPath:
    async def test_full_workflow_completes(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)

        report = await runner.run()

        assert isinstance(report, CalibrationReport)
        assert report.status is CalibrationStatus.COMPLETED
        assert report.session_id.startswith("hwval-")
        assert report.camera_id == "synthetic-0"
        assert report.camera_model == "Synthetic"
        assert report.projector_resolution == SYNTHETIC_PROJECTOR_RESOLUTION
        assert report.errors == ()
        assert not report.warnings

    async def test_all_steps_are_timed(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)

        report = await runner.run()

        expected = {
            "connect_camera",
            "connect_projector",
            "detect_displays",
            "select_projector",
            "build_sequence",
            "capture",
            "decode",
            "calibrate",
            "report",
        }
        assert expected <= set(report.step_times)
        for seconds in report.step_times.values():
            assert seconds >= 0.0

    async def test_metrics_match_ground_truth(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)

        report = await runner.run()
        metrics = report.metrics
        assert metrics is not None

        assert metrics.passed is True
        assert metrics.rms_error < 1.0
        assert metrics.coverage > 0.8
        assert metrics.num_correspondences > 0.8 * _W * _H
        assert metrics.num_calibration_images == 21
        assert metrics.calibration_seconds > 0.0
        assert metrics.missing_correspondences < 0.2 * _W * _H
        assert metrics.per_point_errors

    async def test_capture_and_calibration_artifacts_present(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)

        report = await runner.run()

        assert report.capture is not None
        assert report.capture.num_patterns == 21
        assert report.capture.camera_id == "synthetic-0"
        assert len(report.capture.capture_times) == 21
        assert report.correspondences is not None
        assert report.correspondences.image_size == (1280, 720)
        assert report.calibration is not None
        assert report.calibration.projector_resolution == SYNTHETIC_PROJECTOR_RESOLUTION
        assert report.validation is not None
        assert report.validation.passed is True

    async def test_corner_error_matches_ground_truth(self) -> None:
        # Four points on the synthetic plane (z = 1500) inside the lit quad.
        corner_points = np.array(
            [
                [-200.0, -120.0, 1500.0],
                [200.0, -120.0, 1500.0],
                [-200.0, 120.0, 1500.0],
                [200.0, 120.0, 1500.0],
            ],
            dtype=np.float64,
        )
        transform = CameraProjectorTransform(
            intrinsics=SYNTHETIC_PROJECTOR_MATRIX,
            resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
            pose=projector_pose_matrix(),
        )
        expected_pixels = transform.project(corner_points)

        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(
            camera,
            projector,
            expected_corner_points=corner_points,
            expected_corner_pixels=expected_pixels,
        )

        report = await runner.run()
        assert report.metrics is not None
        assert report.metrics.corner_error is not None
        assert report.metrics.corner_error < 2.0

    async def test_empty_corner_points_yield_none_corner_error(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(
            camera,
            projector,
            expected_corner_points=np.empty((0, 3), dtype=np.float64),
            expected_corner_pixels=np.empty((0, 2), dtype=np.float64),
        )

        report = await runner.run()
        assert report.metrics is not None
        assert report.metrics.corner_error is None

    async def test_projector_shown_all_patterns_and_blanked(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)

        await runner.run()

        assert len(projector.shown) == 21
        assert projector.hidden is True
        assert camera.opened == ["synthetic-0"]
        assert camera.closed == ["synthetic-0"]

    async def test_session_state_after_completion(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)

        await runner.run()

        session = runner.session
        assert session.status is CalibrationStatus.COMPLETED
        assert session.progress == 1.0
        assert session.camera_id == "synthetic-0"
        assert session.capture is not None
        assert session.correspondences is not None
        assert session.calibration is not None
        assert session.validation is not None
        assert session.metrics is not None
        assert session.elapsed_seconds > 0.0


class TestRunnerFailurePaths:
    async def test_no_cameras_fails_cleanly(self) -> None:
        projector = _StubProjector()
        camera = _EmptyCamera(projector)
        runner = _runner(camera, projector)

        report = await runner.run()

        assert report.status is CalibrationStatus.FAILED
        assert report.metrics is None
        assert report.capture is None
        assert report.correspondences is None
        assert report.calibration is None
        assert any("No cameras" in error for error in report.errors)

    async def test_unknown_camera_id_fails_cleanly(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector, camera_id="missing")

        report = await runner.run()

        assert report.status is CalibrationStatus.FAILED
        assert any("missing" in error for error in report.errors)

    async def test_reused_runner_does_not_leak_prior_results(self) -> None:
        projector = _StubProjector()
        camera = _FlippableCamera(projector)
        runner = _runner(camera, projector)

        first = await runner.run()
        assert first.status is CalibrationStatus.COMPLETED
        assert first.metrics is not None

        # The second run fails at connect_camera, before _calibrate():
        # its report must not carry the first run's intermediate results.
        camera.available = False
        second = await runner.run()

        assert second.status is CalibrationStatus.FAILED
        assert any("No cameras" in error for error in second.errors)
        assert second.metrics is None
        assert second.capture is None
        assert second.correspondences is None
        assert second.calibration is None
        assert second.validation is None
        assert second.camera_model == ""

    async def test_reused_runner_falls_back_to_first_camera_after_selection_disconnects(
        self,
    ) -> None:
        projector = _StubProjector()
        camera = _RotatingCamera(projector)
        runner = _runner(camera, projector)  # no configured camera_id

        first = await runner.run()
        assert first.status is CalibrationStatus.COMPLETED
        assert first.camera_id == "camera-0"

        # The prior run selected camera-0; it disconnects. A reused
        # runner must drop the stale selection and fall back to the
        # current first camera instead of failing on "camera-0".
        camera.ids = ["camera-1"]
        second = await runner.run()

        assert second.status is CalibrationStatus.COMPLETED
        assert second.camera_id == "camera-1"
        assert camera.opened == ["camera-0", "camera-1"]

    async def test_cancel_before_run_aborts_at_first_step(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)
        runner.cancel()

        report = await runner.run()

        assert report.status is CalibrationStatus.CANCELLED
        assert any("cancelled" in error.lower() for error in report.errors)
        assert not camera.opened

    async def test_task_cancellation_propagates_to_awaiting_task(self) -> None:
        gate = asyncio.Event()
        projector = _StubProjector()
        camera = _BlockingCamera(projector, gate)
        runner = ValidationRunner(
            camera,
            lambda _info: SYNTHETIC_CAMERA,
            SYNTHETIC_PLANE,
            projector=projector,
            projector_resolution=SYNTHETIC_PROJECTOR_RESOLUTION,
            settle_seconds=0.0,
            capture_timeout=30.0,
        )

        task = asyncio.create_task(runner.run())
        await camera.capture_started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # The session outcome is recorded even though the exception
        # propagates, so callers can inspect the cancellation.
        assert runner.session.status is CalibrationStatus.CANCELLED
        assert any("cancelled" in error.lower() for error in runner.session.errors)
        assert runner.session.metrics is None


class TestRunnerDefaults:
    def test_default_algorithm_is_gray_code(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)
        assert runner._algorithm.method.value == "gray_code"  # type: ignore[attr-defined]

    def test_surface_is_stored(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)
        assert isinstance(runner._surface, SurfacePlane)

    def test_session_starts_idle(self) -> None:
        projector = _StubProjector()
        camera = _StubCamera(projector)
        runner = _runner(camera, projector)
        assert runner.session.status is CalibrationStatus.IDLE
        assert runner.session.session_id == ""


class TestHardwareValidationError:
    def test_raise(self) -> None:
        with pytest.raises(HardwareValidationError):
            raise HardwareValidationError("boom")
