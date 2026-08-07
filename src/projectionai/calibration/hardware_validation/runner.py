"""Hardware validation runner — the 9-step real-hardware workflow.

Orchestrates the *existing* projector calibration pipeline on physical
hardware and packages the outcome into a self-contained
:class:`CalibrationReport`. No new algorithms: the runner composes the
reusable building blocks — ``GrayCodeProjectorCalibration``
(``build_sequence`` -> ``decode`` -> ``calibrate``),
``PatternCaptureSession``, a camera manager, ``ReprojectionValidator``,
and ``ProjectorCornerEstimator``.

Workflow steps:

1. ``connect_camera`` — enumerate cameras and open the selected one.
2. ``connect_projector`` — establish the pattern projection backend.
3. ``detect_displays`` — enumerate connected displays.
4. ``select_projector`` — pick the display and resolve its resolution.
5. ``build_sequence`` — generate the full-screen gray-code sequence.
6. ``capture`` — project each pattern and capture one frame per pattern.
7. ``decode`` — convert captures into a dense correspondence map.
8. ``calibrate`` — estimate projector intrinsics/pose and validate.
9. ``report`` — assemble the :class:`CalibrationReport`.

Hardware independence: the runner depends on small structural seams
(:class:`CameraAccess`, :class:`PatternProjector`, a calibration-input
callable) so the same code drives real devices, the offscreen Qt
platform in CI, and synthetic scenes in tests. Failures anywhere in the
workflow are captured into the report rather than escaping: a run always
produces a :class:`CalibrationReport` whose ``status`` reflects the
outcome.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, TypeVar

import numpy as np
from numpy.typing import NDArray

from projectionai.calibration.hardware_validation.environment import (
    EnvironmentInfo,
    collect_environment,
)
from projectionai.calibration.hardware_validation.models import (
    CalibrationReport,
    CaptureSequence,
    HardwareValidationError,
    HardwareValidationSession,
    ValidationMetrics,
)
from projectionai.calibration.types import CalibrationStatus
from projectionai.infrastructure.display import (
    DisplayError,
    DisplayInfo,
    QtPatternProjector,
    list_displays,
)
from projectionai.infrastructure.projector_calibration.capture import (
    PatternCaptureSession,
)
from projectionai.infrastructure.projector_calibration.estimators import (
    CameraProjectorTransform,
    ProjectorCornerEstimator,
)
from projectionai.infrastructure.projector_calibration.validation import (
    ReprojectionValidator,
    ValidationReport,
)
from projectionai.services.camera import Camera, CameraInfo, Frame
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    CorrespondenceMap,
    FrameSource,
    PatternProjector,
    PatternSequence,
    ProjectorCalibrationAlgorithm,
    ProjectorCalibrationResult,
    SurfacePlane,
)

_logger = logging.getLogger(__name__)

_DEFAULT_SETTLE_SECONDS = 0.1
_DEFAULT_CAPTURE_TIMEOUT = 10.0

# Quality gates matching the MVP pipeline defaults (gray_code.py).
_MAX_RMS_PX = 2.0
_MIN_COVERAGE = 0.5

_T = TypeVar("_T")


class CameraAccess(Protocol):
    """Minimal camera seam satisfied by ``CameraManager``.

    Declares only the operations the workflow needs: enumeration, open,
    one-shot capture (also serving as :class:`FrameSource`), and close.
    """

    async def list_cameras(self) -> tuple[CameraInfo, ...]:
        """Return metadata for all detected cameras."""
        ...

    async def open_camera(self, camera_id: str) -> Camera:
        """Open the camera identified by *camera_id*."""
        ...

    async def capture_frame(self, camera_id: str) -> Frame:
        """Capture a single frame from *camera_id*."""
        ...

    async def close_camera(self, camera_id: str) -> None:
        """Close the camera identified by *camera_id*."""
        ...


class _ValidationCancelledError(HardwareValidationError):
    """Internal signal raised when ``cancel()`` was requested.

    Caught by :meth:`ValidationRunner.run` in a dedicated branch so a
    cooperative cancellation yields a ``CANCELLED`` report instead of
    falling through to the generic failure handler (which would mark the
    run ``FAILED``).
    """


class ValidationRunner:
    """Runs the 9-step hardware validation workflow.

    Args:
        camera: Camera enumeration/opening/capture seam (typically a
            ``CameraManager``; the test suite injects a stub).
        camera_calibration: Callable producing the :class:`CalibratedCamera`
            for a detected device — the intrinsic calibration obtained
            from a prior camera-calibration run.
        surface: The planar :class:`SurfacePlane` (camera coordinates)
            the patterns are projected onto.
        camera_id: Specific camera to use. Defaults to the first camera
            reported by *camera*.
        screen_index: Display index to project onto. Defaults to ``0``
            (the primary display).
        projector: An existing :class:`PatternProjector` instance.
            Mutually exclusive with *projector_factory*.
        projector_factory: Callable ``(screen_index) -> PatternProjector``
            used to create the projector lazily.
        projector_resolution: Projector ``(width, height)`` override.
            Required when the projector/display resolution cannot be
            read (e.g. injected projectors without a ``resolution``).
        algorithm: The calibration algorithm; defaults to
            :class:`GrayCodeProjectorCalibration`.
        validator: Quality gate; defaults to RMS <= 2 px and coverage
            >= 0.5 (matching the MVP pipeline).
        corner_estimator: Estimates where known 3D points land in the
            projector image (used for the corner-error metric).
        expected_corner_points: ``(N, 3)`` camera-frame points whose
            projector pixels are known (e.g. surface corners). When both
            this and *expected_corner_pixels* are given, the report
            carries a corner RMS error; otherwise ``corner_error`` is
            ``None``.
        expected_corner_pixels: Ground-truth ``(N, 2)`` projector pixels
            of *expected_corner_points*.
        settle_seconds: Delay after each pattern display before capture.
        capture_timeout: Per-frame capture timeout in seconds.
    """

    def __init__(
        self,
        camera: CameraAccess,
        camera_calibration: Callable[[CameraInfo], CalibratedCamera],
        surface: SurfacePlane,
        *,
        camera_id: str | None = None,
        screen_index: int = 0,
        projector: PatternProjector | None = None,
        projector_factory: Callable[[int], PatternProjector] | None = None,
        projector_resolution: tuple[int, int] | None = None,
        algorithm: ProjectorCalibrationAlgorithm | None = None,
        validator: ReprojectionValidator | None = None,
        corner_estimator: ProjectorCornerEstimator | None = None,
        expected_corner_points: NDArray[np.float64] | None = None,
        expected_corner_pixels: NDArray[np.float64] | None = None,
        settle_seconds: float = _DEFAULT_SETTLE_SECONDS,
        capture_timeout: float = _DEFAULT_CAPTURE_TIMEOUT,
    ) -> None:
        self._camera = camera
        self._camera_calibration = camera_calibration
        self._surface = surface
        self._configured_camera_id = camera_id
        self._camera_id: str | None = None
        self._screen_index = screen_index
        self._injected_projector = projector
        self._projector_factory = projector_factory
        self._projector_resolution = projector_resolution
        if algorithm is None:
            # Imported lazily to avoid a module-level import cycle: the
            # gray-code algorithm imports ``calibration.types``, which
            # triggers ``calibration/__init__`` and therefore this
            # package while ``gray_code`` is still initialising.
            from projectionai.infrastructure.projector_calibration.gray_code import (
                GrayCodeProjectorCalibration,
            )

            algorithm = GrayCodeProjectorCalibration()
        self._algorithm = algorithm
        self._validator = validator or ReprojectionValidator(
            max_rms=_MAX_RMS_PX, min_coverage=_MIN_COVERAGE
        )
        self._corner_estimator = corner_estimator or ProjectorCornerEstimator()
        self._expected_corner_points = expected_corner_points
        self._expected_corner_pixels = expected_corner_pixels
        self._settle_seconds = settle_seconds
        self._capture_timeout = capture_timeout

        self._session: HardwareValidationSession = HardwareValidationSession(
            session_id=""
        )
        self._environment: EnvironmentInfo = collect_environment()
        self._cancelled = False
        self._camera_opened = False

        # Intermediate state populated as the workflow advances.
        self._projector: PatternProjector | None = None
        self._camera_info: CameraInfo | None = None
        self._displays: list[DisplayInfo] = []
        self._selected_display: DisplayInfo | None = None
        self._resolution: tuple[int, int] | None = None
        self._sequence: PatternSequence | None = None
        self._capture_sequence: CaptureSequence | None = None
        self._correspondences: CorrespondenceMap | None = None
        self._calibration: ProjectorCalibrationResult | None = None
        self._calibration_seconds: float = 0.0
        self._validation: ValidationReport | None = None
        self._corner_error: float | None = None

    @property
    def session(self) -> HardwareValidationSession:
        """The live session state (progress, status, intermediate results)."""
        return self._session

    def cancel(self) -> None:
        """Request cancellation; the runner stops at the next step boundary."""
        self._cancelled = True

    async def run(self) -> CalibrationReport:
        """Execute the 9-step workflow and return the final report.

        A report is always returned — on success ``status`` is
        ``COMPLETED``; on failure or cooperative cancellation (via
        :meth:`cancel`) the report carries the ``FAILED``/``CANCELLED``
        status and the collected errors. External task cancellation
        (``asyncio.CancelledError``) is recorded on the session as
        ``CANCELLED`` and re-raised, so the awaiting task still observes
        the cancellation.
        """
        self._session = HardwareValidationSession(
            session_id=f"hwval-{uuid.uuid4().hex[:12]}"
        )
        session = self._session
        session.started_at = time.monotonic()
        self._environment = collect_environment()

        # Reset run-scoped state so a reused runner never carries results
        # from a previous run into this run's report when execution fails
        # before the calibrate step (metrics/artifacts would otherwise be
        # rebuilt from the prior run's intermediate results).
        self._projector = None
        self._camera_info = None
        self._displays = []
        self._selected_display = None
        self._resolution = None
        self._sequence = None
        self._capture_sequence = None
        self._correspondences = None
        self._calibration = None
        self._calibration_seconds = 0.0
        self._validation = None
        self._corner_error = None
        self._camera_id = None

        try:
            await self._step_wrapper(
                session,
                "connect_camera",
                "Connecting camera",
                CalibrationStatus.PREPARING,
                0.1,
                self._connect_camera(),
            )
            await self._step_wrapper(
                session,
                "connect_projector",
                "Connecting projector",
                CalibrationStatus.PREPARING,
                0.2,
                self._connect_projector(),
            )
            await self._step_wrapper(
                session,
                "detect_displays",
                "Detecting displays",
                CalibrationStatus.PREPARING,
                0.3,
                self._detect_displays(),
            )
            await self._step_wrapper(
                session,
                "select_projector",
                "Selecting projector display",
                CalibrationStatus.PREPARING,
                0.4,
                self._select_projector(),
            )
            await self._step_wrapper(
                session,
                "build_sequence",
                "Building gray-code sequence",
                CalibrationStatus.PREPARING,
                0.5,
                self._build_sequence(),
            )
            await self._step_wrapper(
                session,
                "capture",
                "Projecting patterns and capturing",
                CalibrationStatus.ACQUIRING,
                0.7,
                self._capture(),
            )
            await self._step_wrapper(
                session,
                "decode",
                "Decoding correspondences",
                CalibrationStatus.PROCESSING,
                0.8,
                self._decode(),
            )
            await self._step_wrapper(
                session,
                "calibrate",
                "Calibrating projector",
                CalibrationStatus.VALIDATING,
                0.9,
                self._calibrate(),
            )

            session.status = CalibrationStatus.COMPLETED
            session.progress = 1.0
            session.current_step = "Building report"
            session.status_text = "Building report"
            start = time.monotonic()
            report = self._build_report()
            session.step_times["report"] = time.monotonic() - start
            # The report snapshot is taken before the timing above, so patch
            # it to include the "report" step.
            return replace(report, step_times=dict(session.step_times))
        except _ValidationCancelledError:
            _logger.warning("Hardware validation cancelled")
            session.errors.append("Hardware validation cancelled")
            session.status = CalibrationStatus.CANCELLED
            return self._build_report()
        except asyncio.CancelledError:
            # External task cancellation: record the session outcome, then
            # propagate so the awaiting task observes the cancellation.
            _logger.warning("Hardware validation task cancelled externally")
            session.errors.append("Hardware validation cancelled")
            session.status = CalibrationStatus.CANCELLED
            self._build_report()
            raise
        except Exception as exc:
            _logger.exception("Hardware validation failed")
            session.errors.append(str(exc))
            session.status = CalibrationStatus.FAILED
            return self._build_report()
        finally:
            await self._release_camera()
            self._cancelled = False

    # -- Steps --------------------------------------------------------------

    async def _connect_camera(self) -> None:
        self._raise_if_cancelled()
        infos = await self._camera.list_cameras()
        if not infos:
            raise HardwareValidationError("No cameras detected on this system")
        camera_id = self._configured_camera_id or infos[0].camera_id
        info = next((i for i in infos if i.camera_id == camera_id), None)
        if info is None:
            raise HardwareValidationError(f"Camera {camera_id!r} not found")
        await self._camera.open_camera(camera_id)
        self._camera_id = camera_id
        self._camera_info = info
        self._session.camera_id = camera_id
        self._camera_opened = True

    async def _release_camera(self) -> None:
        """Close the camera if it was opened by this run.

        Cleanup failures are logged but never raised, so they cannot
        mask the run's result or cancellation.
        """
        if not self._camera_opened:
            return
        camera_id = self._camera_id
        if camera_id is None:
            self._camera_opened = False
            return
        try:
            await self._camera.close_camera(camera_id)
        except Exception as exc:
            _logger.warning(
                "Failed to close camera %r during cleanup: %s",
                camera_id,
                exc,
            )
        finally:
            self._camera_opened = False

    async def _connect_projector(self) -> None:
        self._raise_if_cancelled()
        if self._injected_projector is not None:
            self._projector = self._injected_projector
        elif self._projector_factory is not None:
            self._projector = self._projector_factory(self._screen_index)
        else:
            self._projector = QtPatternProjector(self._screen_index)

    async def _detect_displays(self) -> None:
        self._raise_if_cancelled()
        try:
            displays = list_displays()
        except DisplayError as exc:
            self._session.warnings.append(f"Display enumeration failed: {exc}")
            displays = []
        self._displays = displays
        if not displays:
            self._session.warnings.append("No displays detected")
            return
        if not 0 <= self._screen_index < len(displays):
            self._session.warnings.append(
                f"screen_index {self._screen_index} out of range "
                f"(0..{len(displays) - 1})"
            )
            return
        self._selected_display = displays[self._screen_index]

    async def _select_projector(self) -> None:
        self._raise_if_cancelled()
        if self._projector_resolution is not None:
            self._resolution = self._projector_resolution
            return
        if self._selected_display is not None:
            self._resolution = self._selected_display.resolution
            self._session.screen_index = self._selected_display.index
            return
        raise HardwareValidationError(
            "Could not determine projector resolution: provide "
            "projector_resolution or a detectable display"
        )

    async def _build_sequence(self) -> None:
        self._raise_if_cancelled()
        self._sequence = self._algorithm.build_sequence(self._require_resolution())

    async def _capture(self) -> None:
        self._raise_if_cancelled()
        projector = self._require_projector()
        timed = _TimedFrameSource(self._camera)
        capture_session = PatternCaptureSession(
            timed,
            self._session.camera_id,
            projector,
            settle_seconds=self._settle_seconds,
            capture_timeout=self._capture_timeout,
        )
        start = time.monotonic()
        frames = await capture_session.capture_sequence(self._require_sequence())
        total_seconds = time.monotonic() - start
        if not frames:
            raise HardwareValidationError("Capture produced no frames")

        # Read the first two axes explicitly so grayscale (H, W) and
        # color (H, W, 3) frames both work; camera_resolution stays (W, H).
        height, width = frames[0].shape[:2]
        capture = CaptureSequence(
            camera_id=self._session.camera_id,
            projector_resolution=self._require_resolution(),
            camera_resolution=(width, height),
            num_patterns=len(frames),
            captured_frames=tuple(frames),
            capture_times=timed.capture_times,
            total_capture_seconds=total_seconds,
        )
        self._capture_sequence = capture
        self._session.capture = capture

    async def _decode(self) -> None:
        self._raise_if_cancelled()
        correspondences = self._algorithm.decode(
            self._require_capture().captured_frames, self._require_sequence()
        )
        self._correspondences = correspondences
        self._session.correspondences = correspondences

    async def _calibrate(self) -> None:
        self._raise_if_cancelled()
        if self._camera_info is None:
            raise HardwareValidationError("Camera was not connected")
        camera = self._camera_calibration(self._camera_info)
        if camera.image_size != self._require_correspondences().image_size:
            self._session.warnings.append(
                f"Calibrated camera image size {camera.image_size} differs from "
                f"capture size {self._require_correspondences().image_size}"
            )

        start = time.monotonic()
        result = self._algorithm.calibrate(
            self._require_correspondences(),
            camera,
            self._surface,
            self._require_resolution(),
        )
        self._calibration_seconds = time.monotonic() - start
        self._calibration = result
        self._session.calibration = result
        self._session.status_text = "Validating calibration"

        validation = self._validator.validate(
            self._require_correspondences(),
            camera,
            self._surface,
            result.projector_intrinsics,
            result.projector_pose,
            self._require_resolution(),
        )
        self._validation = validation
        self._session.validation = validation
        self._corner_error = self._compute_corner_error(result)

    # -- Report -------------------------------------------------------------

    def _build_report(self) -> CalibrationReport:
        session = self._session
        metrics = self._metrics()
        session.metrics = metrics

        elapsed = time.monotonic() - session.started_at
        session.elapsed_seconds = elapsed
        environment = replace(self._environment, duration_seconds=elapsed)

        report = CalibrationReport(
            session_id=session.session_id,
            created_at=datetime.now(UTC).isoformat(),
            camera_id=session.camera_id,
            camera_model=self._camera_info.model if self._camera_info else "",
            projector_display=self._selected_display,
            projector_resolution=self._resolution,
            environment=environment,
            capture=session.capture,
            correspondences=session.correspondences,
            calibration=session.calibration,
            validation=session.validation,
            metrics=metrics,
            status=session.status,
            step_times=dict(session.step_times),
            warnings=tuple(session.warnings),
            errors=tuple(session.errors),
            total_seconds=elapsed,
        )
        _logger.info(
            "Hardware validation %s: status=%s, RMS %.3f px, coverage %.1f%%",
            session.session_id,
            session.status.value,
            metrics.rms_error if metrics else float("nan"),
            (metrics.coverage * 100.0) if metrics else float("nan"),
        )
        return report

    def _metrics(self) -> ValidationMetrics | None:
        validation = self._validation
        calibration = self._calibration
        correspondences = self._correspondences
        if validation is None or calibration is None or correspondences is None:
            return None
        return ValidationMetrics(
            rms_error=validation.rms_error,
            mean_error=validation.mean_error,
            max_error=validation.max_error,
            inlier_ratio=validation.inlier_ratio,
            coverage=validation.coverage,
            corner_error=self._corner_error,
            confidence=calibration.confidence,
            num_correspondences=correspondences.num_correspondences,
            missing_correspondences=_missing_correspondences(correspondences),
            num_calibration_images=len(self._require_capture().captured_frames),
            calibration_seconds=self._calibration_seconds,
            per_point_errors=validation.per_point_errors,
            passed=validation.passed,
        )

    def _compute_corner_error(self, result: ProjectorCalibrationResult) -> float | None:
        """RMS projector-pixel error of known 3D points, or ``None``."""
        points = self._expected_corner_points
        expected = self._expected_corner_pixels
        if points is None or expected is None or len(points) == 0:
            return None
        transform = CameraProjectorTransform(
            intrinsics=result.projector_intrinsics,
            resolution=result.projector_resolution,
            pose=result.projector_pose,
        )
        estimated = self._corner_estimator.estimate(points, transform)
        errors = np.linalg.norm(estimated - expected, axis=1)
        rms_error = float(np.sqrt(np.mean(np.square(errors))))
        # Degenerate inputs can yield NaN; keep the serialized metric
        # finite (None means "could not be estimated").
        return rms_error if np.isfinite(rms_error) else None

    # -- Internal helpers ---------------------------------------------------

    async def _step_wrapper(
        self,
        session: HardwareValidationSession,
        name: str,
        label: str,
        status: CalibrationStatus,
        progress: float,
        coro: Awaitable[_T],
    ) -> _T:
        session.current_step = label
        session.status_text = label
        session.status = status
        session.progress = progress
        start = time.monotonic()
        try:
            return await coro
        finally:
            session.step_times[name] = time.monotonic() - start

    def _raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise _ValidationCancelledError("Hardware validation cancelled")

    def _require_projector(self) -> PatternProjector:
        if self._projector is None:
            raise HardwareValidationError("Projector was not connected")
        return self._projector

    def _require_resolution(self) -> tuple[int, int]:
        if self._resolution is None:
            raise HardwareValidationError("Projector resolution not selected")
        return self._resolution

    def _require_sequence(self) -> PatternSequence:
        if self._sequence is None:
            raise HardwareValidationError("Pattern sequence was not built")
        return self._sequence

    def _require_capture(self) -> CaptureSequence:
        if self._capture_sequence is None:
            raise HardwareValidationError("Capture step did not complete")
        return self._capture_sequence

    def _require_correspondences(self) -> CorrespondenceMap:
        if self._correspondences is None:
            raise HardwareValidationError("Decode step did not complete")
        return self._correspondences


class _TimedFrameSource:
    """Wraps a :class:`FrameSource` recording per-capture wall times.

    Used to fill :attr:`CaptureSequence.capture_times` with the observed
    per-pattern projection/capture duration.
    """

    def __init__(self, source: FrameSource) -> None:
        self._source = source
        self._times: list[float] = []

    @property
    def capture_times(self) -> tuple[float, ...]:
        """Recorded per-capture durations in seconds."""
        return tuple(self._times)

    async def capture_frame(self, camera_id: str) -> Frame:
        """Capture a frame and record the actual capture duration."""
        start = time.monotonic()
        frame = await self._source.capture_frame(camera_id)
        self._times.append(time.monotonic() - start)
        return frame


def _missing_correspondences(correspondences: CorrespondenceMap) -> int:
    """Camera pixels with no valid decode."""
    width, height = correspondences.image_size
    total = width * height
    return max(0, total - correspondences.num_correspondences)
