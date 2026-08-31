"""Capture state machine + recovery layer.

Composes :class:`PatternPresentationSession` with a :class:`FrameSource`
to safely turn presented calibration patterns into captured
:class:`CalibrationFrame` objects.

State machine::

    IDLE ──▶ PRESENTING ──▶ WAITING_FOR_FRAME ──▶ CAPTURED ──▶ VALIDATING
                                      │                           │
                                      ▼                           ▼
                                  TIMEOUT                     COMPLETE
                                      │
                                      ▼
                                    FAILED ──▶ RETRYING ──▶ PRESENTING
                                      ▲
                                      │
                                  CANCELLED (at any point)

Design boundaries:
    - Does NOT duplicate :class:`SynchronizedCaptureSession` (Phase 6).
      SynchronizedCaptureSession handles per-pattern presentation barrier,
      latency checks, and monotonicity validation at the single-frame level.
      This module handles sequence-level lifecycle, disconnect recovery,
      partial sequence preservation, and enhanced metrics.
    - Does NOT duplicate :class:`ProductionWorkflow` (Phase 7.1).
      Capture state maps to workflow stage externally via the ``state``
      property.  No parallel safety state machine is created.
    - Preserves ``BEST_EFFORT_TIMESTAMP`` semantics throughout.
      Presentation timestamps are ``time.monotonic_ns()`` approximations,
      NOT hardware-vsync boundaries.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from projectionai.core.errors import CameraError, ProjectionAIError
from projectionai.domain.calibration_session import (
    CalibrationFrame,
    CalibrationPattern,
    CalibrationSequence,
)
from projectionai.services.camera import Frame
from projectionai.services.pattern_presentation import (
    PatternPresentationSession,
)
from projectionai.services.projector_calibration import FrameSource

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CaptureError(ProjectionAIError):
    """Raised when the capture sequence encounters a fatal error."""


class CameraDisconnectError(CaptureError):
    """Raised when the camera disconnects mid-sequence."""


class FrameRejectionError(CaptureError):
    """Raised when a captured frame fails acceptance criteria."""


class CaptureTimeoutError(CaptureError):
    """Raised when a capture operation times out."""


# ---------------------------------------------------------------------------
# Capture state machine
# ---------------------------------------------------------------------------


class CaptureState(StrEnum):
    """Explicit capture lifecycle states.

    Scoped to capture behavior only.  Does NOT duplicate
    :class:`ProductionWorkflow`'s global state machine.

    Mapping to production workflow (external):
        IDLE          → WorkflowStage.IDLE
        PRESENTING    → WorkflowStage.CAPTURING (presentation phase)
        WAITING       → WorkflowStage.CAPTURING (capture phase)
        CAPTURED      → WorkflowStage.CAPTURING (frame received)
        VALIDATING    → WorkflowStage.CAPTURING (validation phase)
        COMPLETE      → WorkflowStage.CALIBRATING
        FAILED        → WorkflowStage.FAILED
        TIMEOUT       → WorkflowStage.FAILED
        CANCELLED     → WorkflowStage.CANCELLED
    """

    IDLE = "idle"
    """No capture in progress."""

    PRESENTING = "presenting"
    """Pattern is being displayed on the projector."""

    WAITING = "waiting"
    """Waiting for a camera frame after presentation."""

    CAPTURED = "captured"
    """Frame received from camera, not yet validated."""

    VALIDATING = "validating"
    """Validating frame acceptance criteria."""

    COMPLETE = "complete"
    """All patterns in the sequence captured successfully."""

    FAILED = "failed"
    """Capture failed (retries exhausted or unrecoverable error)."""

    TIMEOUT = "timeout"
    """Capture timed out."""

    CANCELLED = "cancelled"
    """Capture was cancelled by the caller."""


# ---------------------------------------------------------------------------
# Capture configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureConfig:
    """Configuration for a capture session.

    Attributes:
        min_settle_ms: Milliseconds to wait after presentation before
            capturing, allowing the display to settle.
        max_capture_latency_ms: Maximum allowed latency between
            presentation and capture.  Frames exceeding this are rejected.
        capture_timeout: Seconds to wait for a camera frame before
            raising a timeout.
        presentation_timeout: Seconds to wait for the presentation to
            complete before raising a timeout.
        retry_count: Number of retry attempts for a failed pattern.
        warmup_frames: Number of warmup frames to capture before the
            first pattern, to flush the camera pipeline.
        max_stale_frames: Maximum number of consecutive stale frames
            (wrong sequence_id or pattern_id) before treating as a
            disconnect.  0 = reject any stale frame immediately.
    """

    min_settle_ms: float = 20.0
    max_capture_latency_ms: float = 500.0
    capture_timeout: float = 5.0
    presentation_timeout: float = 2.0
    retry_count: int = 1
    warmup_frames: int = 1
    max_stale_frames: int = 0


# ---------------------------------------------------------------------------
# Frame acceptance protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FrameAcceptancePolicy(Protocol):
    """Protocol for frame acceptance strategies.

    Implementations decide whether a captured frame is valid for the
    given pattern.  This allows swapping acceptance criteria without
    changing the capture session.
    """

    def accept(
        self,
        frame: Frame,
        pattern: CalibrationPattern,
        sequence: CalibrationSequence,
    ) -> None:
        """Validate frame acceptance criteria.

        Args:
            frame: The captured frame.
            pattern: The expected pattern.
            sequence: The full sequence.

        Raises:
            FrameRejectionError: If the frame fails acceptance criteria.
        """
        ...

    def reset(self) -> None:
        """Reset any per-sequence tracking state."""
        ...


class DefaultFrameAcceptance:
    """Default frame acceptance criteria.

    Validates:
    - Frame is not None (camera returned data)
    - Image shape is (H, W, 3) RGB uint8
    - Frame sequence_id matches expected sequence (if set on frame)
    - Frame pattern_id matches expected pattern (if set on frame)
    - Capture latency within bounds
    - Presentation timestamp is monotonic (if multiple frames captured)
    """

    def __init__(self, config: CaptureConfig | None = None) -> None:
        self._config = config or CaptureConfig()
        self._prev_capture_ts: int | None = None
        self._prev_presentation_ts: int | None = None

    def accept(
        self,
        frame: Frame,
        pattern: CalibrationPattern,
        sequence: CalibrationSequence,
    ) -> None:
        """Validate frame against default acceptance criteria."""
        if frame is None:
            raise FrameRejectionError("Frame is None — camera returned no data")

        # Image shape validation
        if frame.image.ndim not in (2, 3):
            raise FrameRejectionError(
                f"Invalid image dimensions: {frame.image.ndim} (expected 2 or 3)"
            )
        if frame.image.ndim == 3 and frame.image.shape[2] != 3:
            raise FrameRejectionError(
                f"Invalid image channels: {frame.image.shape[2]} (expected 3)"
            )
        if frame.image.dtype.name != "uint8":
            raise FrameRejectionError(
                f"Invalid image dtype: {frame.image.dtype} (expected uint8)"
            )

        # Sequence ID match (if frame carries sequence metadata)
        if (
            frame.sequence_id is not None
            and frame.sequence_id != ""
            and frame.sequence_id != sequence.sequence_id
        ):
            raise FrameRejectionError(
                f"sequence_id mismatch: frame={frame.sequence_id!r} "
                f"expected={sequence.sequence_id!r}"
            )

        # Pattern ID match (if frame carries pattern metadata)
        if (
            frame.pattern_id is not None
            and frame.pattern_id != -1
            and frame.pattern_id != pattern.pattern_id
        ):
            raise FrameRejectionError(
                f"pattern_id mismatch: frame={frame.pattern_id} "
                f"expected={pattern.pattern_id}"
            )

        # Capture latency bounds (if latency metadata present)
        if frame.capture_latency_ms is not None:
            if frame.capture_latency_ms < 0:
                raise FrameRejectionError(
                    f"Negative capture latency: {frame.capture_latency_ms:.2f}ms"
                )
            if frame.capture_latency_ms > self._config.max_capture_latency_ms:
                raise FrameRejectionError(
                    f"Capture latency {frame.capture_latency_ms:.2f}ms "
                    f"exceeds max {self._config.max_capture_latency_ms}ms"
                )

        if (
            frame.presentation_timestamp_ns is not None
            and self._prev_presentation_ts is not None
            and frame.presentation_timestamp_ns < self._prev_presentation_ts
        ):
            raise FrameRejectionError(
                "Presentation timestamps non-monotonic: "
                f"{frame.presentation_timestamp_ns} < "
                f"{self._prev_presentation_ts}"
            )
        if frame.presentation_timestamp_ns is not None:
            self._prev_presentation_ts = frame.presentation_timestamp_ns

        if (
            frame.timestamp_ns is not None
            and self._prev_capture_ts is not None
            and frame.timestamp_ns < self._prev_capture_ts
        ):
            raise FrameRejectionError(
                "Capture timestamps non-monotonic: "
                f"{frame.timestamp_ns} < {self._prev_capture_ts}"
            )
        if frame.timestamp_ns is not None:
            self._prev_capture_ts = frame.timestamp_ns

    def reset(self) -> None:
        """Reset monotonicity tracking for a new sequence."""
        self._prev_capture_ts = None
        self._prev_presentation_ts = None


# ---------------------------------------------------------------------------
# Capture metrics
# ---------------------------------------------------------------------------


@dataclass
class CaptureMetrics:
    """Enhanced capture metrics for the sequence.

    Tracks per-sequence statistics beyond what SynchronizedCaptureSession
    provides (which is per-frame latency and retry counts).
    """

    frames_attempted: int = 0
    """Total frames attempted (including retries)."""

    frames_accepted: int = 0
    """Frames that passed acceptance criteria."""

    frames_rejected: int = 0
    """Frames that failed acceptance criteria."""

    stale_frames: int = 0
    """Frames rejected due to sequence/pattern ID mismatch."""

    timeouts: int = 0
    """Number of timeout events."""

    camera_errors: int = 0
    """Number of camera errors (disconnect, read failure)."""

    retries: int = 0
    """Number of retry attempts across all patterns."""

    latencies_ms: list[float] = field(default_factory=list)
    """Per-frame capture latencies in milliseconds."""

    @property
    def p50(self) -> float | None:
        """Median capture latency."""
        return _percentile(self.latencies_ms, 50)

    @property
    def p95(self) -> float | None:
        """95th percentile capture latency."""
        return _percentile(self.latencies_ms, 95)

    @property
    def p99(self) -> float | None:
        """99th percentile capture latency."""
        return _percentile(self.latencies_ms, 99)

    @property
    def max_latency(self) -> float | None:
        """Maximum capture latency."""
        if not self.latencies_ms:
            return None
        return max(self.latencies_ms)

    @property
    def success_rate(self) -> float:
        """Fraction of attempted frames that were accepted."""
        if self.frames_attempted == 0:
            return 0.0
        return self.frames_accepted / self.frames_attempted


def _percentile(data: list[float], p: int) -> float | None:
    """Compute the p-th percentile of a list of values."""
    if not data:
        return None
    sorted_data = sorted(data)
    k = int((p / 100) * (len(sorted_data) - 1))
    return float(sorted_data[k])


# ---------------------------------------------------------------------------
# Capture result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureResult:
    """Result of a capture sequence attempt.

    On success, ``frames`` contains all captured frames in order.
    On failure, ``partial_frames`` preserves any valid frames captured
    before the failure point.
    """

    state: CaptureState
    """Final state of the capture session."""

    frames: tuple[CalibrationFrame, ...]
    """All captured frames (empty on total failure)."""

    partial_frames: tuple[CalibrationFrame, ...]
    """Frames captured before failure (same as ``frames`` on success)."""

    metrics: CaptureMetrics
    """Capture metrics for the sequence."""

    failed_pattern_index: int | None = None
    """Index of the pattern that failed (if applicable)."""

    failed_pattern_id: int | None = None
    """ID of the pattern that failed (if applicable)."""

    error: str | None = None
    """Error message if the sequence failed."""

    @property
    def success(self) -> bool:
        """Return True if the capture completed successfully."""
        return self.state == CaptureState.COMPLETE


# ---------------------------------------------------------------------------
# Capture session
# ---------------------------------------------------------------------------


class CaptureSession:
    """High-level capture orchestrator with state machine, disconnect
    recovery, partial sequence support, and enhanced metrics.

    Composes :class:`PatternPresentationSession` (display lifecycle)
    with a :class:`FrameSource` (camera capture) to safely turn presented
    calibration patterns into :class:`CalibrationFrame` objects.

    Lifecycle::

        session = CaptureSession(presentation, frame_source, "cam0")
        result = await session.capture_sequence(sequence)

    On success, ``result.frames`` contains the frames in order.
    On failure, ``result.partial_frames`` preserves valid frames.

    Does NOT duplicate :class:`SynchronizedCaptureSession` or
    :class:`ProductionWorkflow`.

    Usage::

        target = QTPatternPresentationTarget(projector)
        presentation = PatternPresentationSession(target)
        session = CaptureSession(presentation, camera_manager, "cam0")
        result = await session.capture_sequence(sequence)
        if result.success:
            # process result.frames
        else:
            # use result.partial_frames or handle result.error
    """

    def __init__(
        self,
        presentation: PatternPresentationSession,
        frame_source: FrameSource,
        camera_id: str,
        config: CaptureConfig | None = None,
        acceptance: FrameAcceptancePolicy | None = None,
    ) -> None:
        """Initialize the capture session.

        Args:
            presentation: Pattern presentation session for display control.
            frame_source: Camera frame source (satisfies FrameSource protocol).
            camera_id: Camera device identifier.
            config: Capture configuration (uses defaults if None).
            acceptance: Frame acceptance policy (uses DefaultFrameAcceptance if None).
        """
        self._presentation = presentation
        self._frame_source = frame_source
        self._camera_id = camera_id
        self._config = config or CaptureConfig()
        self._acceptance = acceptance or DefaultFrameAcceptance(self._config)
        self._state = CaptureState.IDLE
        self._metrics = CaptureMetrics()
        self._cancelled = False
        self._lock = asyncio.Lock()

    # -- Properties --------------------------------------------------------

    @property
    def state(self) -> CaptureState:
        """Current capture state."""
        return self._state

    @property
    def metrics(self) -> CaptureMetrics:
        """Current capture metrics."""
        return self._metrics

    # -- Public API --------------------------------------------------------

    def cancel(self) -> None:
        """Request cooperative cancellation.

        The capture will stop at the next safe cancellation point
        (between patterns, not mid-capture).
        """
        self._cancelled = True

    async def capture_sequence(self, sequence: CalibrationSequence) -> CaptureResult:
        """Present and capture an entire calibration sequence.

        Returns a :class:`CaptureResult` with frames (or partial frames
        on failure).  Safe to call multiple times — each call resets
        metrics and state.

        The session presents each pattern via the presentation session,
        captures the corresponding camera frame, validates acceptance
        criteria, and collects results.  On failure, valid frames
        captured before the failure are preserved in ``partial_frames``.

        Args:
            sequence: The calibration sequence to capture.

        Returns:
            CaptureResult with frames, metrics, and final state.
        """
        async with self._lock:
            if self._cancelled:
                self._state = CaptureState.CANCELLED
                return CaptureResult(
                    state=self._state,
                    frames=(),
                    partial_frames=(),
                    metrics=self._metrics,
                    error="Capture cancelled before start",
                )

            if self._state not in (
                CaptureState.IDLE,
                CaptureState.COMPLETE,
                CaptureState.FAILED,
                CaptureState.TIMEOUT,
                CaptureState.CANCELLED,
            ):
                raise CaptureError(f"Cannot start capture in state {self._state}")

            self._cancelled = False
            self._metrics = CaptureMetrics()
            self._acceptance.reset()
            self._state = CaptureState.IDLE

            accepted_frames: list[CalibrationFrame] = []

            try:
                # Warmup: drain camera pipeline for steady-state capture
                await self._warmup()

                # Capture each pattern in the sequence
                for idx, pattern in enumerate(sequence.patterns):
                    # Cooperative cancellation check
                    if self._cancelled:
                        self._state = CaptureState.CANCELLED
                        return CaptureResult(
                            state=self._state,
                            frames=tuple(accepted_frames),
                            partial_frames=tuple(accepted_frames),
                            metrics=self._metrics,
                            error="Capture cancelled during sequence",
                        )

                    # Capture one pattern with retries
                    cf, _retries, last_err = await self._capture_one_with_retry(
                        pattern, sequence, idx
                    )

                    # Check cancel between patterns (retry may have detected it)
                    if self._cancelled:
                        self._state = CaptureState.CANCELLED
                        return CaptureResult(
                            state=self._state,
                            frames=tuple(accepted_frames),
                            partial_frames=tuple(accepted_frames),
                            metrics=self._metrics,
                            error="Capture cancelled during retry",
                        )

                    if cf is not None:
                        accepted_frames.append(cf)
                    else:
                        # All retries exhausted — preserve partial results
                        self._state = CaptureState.FAILED
                        return CaptureResult(
                            state=self._state,
                            frames=(),
                            partial_frames=tuple(accepted_frames),
                            metrics=self._metrics,
                            failed_pattern_index=idx,
                            failed_pattern_id=pattern.pattern_id,
                            error=(
                                f"Capture failed for pattern {idx}"
                                f" ({pattern.pattern_id!r}) after retries"
                                + (f": {last_err}" if last_err else "")
                            ),
                        )

                # All patterns captured successfully
                self._state = CaptureState.COMPLETE
                return CaptureResult(
                    state=self._state,
                    frames=tuple(accepted_frames),
                    partial_frames=tuple(accepted_frames),
                    metrics=self._metrics,
                )

            except asyncio.CancelledError:
                self._state = CaptureState.CANCELLED
                return CaptureResult(
                    state=self._state,
                    frames=tuple(accepted_frames),
                    partial_frames=tuple(accepted_frames),
                    metrics=self._metrics,
                    error="Capture cancelled",
                )
            except CameraDisconnectError as exc:
                self._state = CaptureState.FAILED
                return CaptureResult(
                    state=self._state,
                    frames=tuple(accepted_frames),
                    partial_frames=tuple(accepted_frames),
                    metrics=self._metrics,
                    error=str(exc),
                )
            except CaptureTimeoutError as exc:
                self._state = CaptureState.TIMEOUT
                return CaptureResult(
                    state=self._state,
                    frames=tuple(accepted_frames),
                    partial_frames=tuple(accepted_frames),
                    metrics=self._metrics,
                    error=str(exc),
                )
            except Exception as exc:
                _logger.exception("Unexpected capture error")
                self._state = CaptureState.FAILED
                return CaptureResult(
                    state=self._state,
                    frames=(),
                    partial_frames=tuple(accepted_frames),
                    metrics=self._metrics,
                    error=str(exc),
                )
            finally:
                # Safe stop: hide display and exit presentation
                with contextlib.suppress(Exception):
                    await self._presentation.hide()

    # -- Private helpers ---------------------------------------------------

    async def _warmup(self) -> None:
        """Drain warmup frames for camera settling."""
        for _ in range(self._config.warmup_frames):
            try:
                await asyncio.wait_for(
                    self._frame_source.capture_frame(self._camera_id),
                    timeout=self._config.capture_timeout,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                self._metrics.timeouts += 1
                raise CaptureTimeoutError(
                    f"Warmup capture timed out after {self._config.capture_timeout}s"
                ) from exc
            except CameraError as exc:
                self._metrics.camera_errors += 1
                raise CameraDisconnectError(f"Warmup camera error: {exc}") from exc

    async def _capture_one_with_retry(
        self,
        pattern: CalibrationPattern,
        sequence: CalibrationSequence,
        pattern_index: int,
    ) -> tuple[CalibrationFrame | None, int, Exception | None]:
        """Capture a single pattern with bounded retries.

        Returns:
            Tuple of (frame_or_None, retry_count, last_error).
            frame_or_None is None if all retries exhausted.
        """
        last_error: Exception | None = None
        retries = 0

        for attempt in range(self._config.retry_count + 1):
            if self._cancelled:
                return None, retries, None

            try:
                if attempt > 0:
                    retries += 1
                    self._metrics.retries += 1
                    _logger.info(
                        "Retrying pattern %d (attempt %d/%d)",
                        pattern_index,
                        attempt + 1,
                        self._config.retry_count + 1,
                    )

                cf = await self._present_and_capture(pattern, sequence, pattern_index)
                self._metrics.frames_accepted += 1
                return cf, retries, None

            except asyncio.CancelledError:
                raise
            except FrameRejectionError as exc:
                if self._cancelled:
                    return None, retries, None
                last_error = exc
                self._metrics.frames_rejected += 1
                if "mismatch" in str(exc).lower():
                    self._metrics.stale_frames += 1
                    # Check stale frame threshold
                    if (
                        self._config.max_stale_frames > 0
                        and self._metrics.stale_frames > self._config.max_stale_frames
                    ):
                        self._metrics.camera_errors += 1
                        raise CameraDisconnectError(
                            f"Too many stale frames "
                            f"({self._metrics.stale_frames}) — "
                            f"possible camera disconnect"
                        ) from exc
                _logger.warning(
                    "Frame rejected for pattern %d: %s",
                    pattern_index,
                    exc,
                )

            except CameraDisconnectError:
                self._metrics.camera_errors += 1
                raise

            except CaptureTimeoutError as exc:
                if self._cancelled:
                    return None, retries, None
                self._metrics.timeouts += 1
                last_error = exc

            except CaptureError as exc:
                if self._cancelled:
                    return None, retries, None
                last_error = exc

        _logger.warning(
            "Pattern %d failed after %d retries: %s",
            pattern_index,
            self._config.retry_count,
            last_error,
        )
        if isinstance(last_error, CaptureTimeoutError):
            raise last_error
        return None, retries, last_error

    async def _present_and_capture(
        self,
        pattern: CalibrationPattern,
        sequence: CalibrationSequence,
        pattern_index: int,
    ) -> CalibrationFrame:
        """Present a pattern and capture the corresponding frame.

        This is the core per-pattern operation:
        1. Present the pattern via PatternPresentationSession
        2. Record the presentation timestamp (best-effort)
        3. Wait for settle time
        4. Capture the camera frame
        5. Validate frame acceptance criteria
        6. Stamp and return the CalibrationFrame
        """
        # Phase 1: Present pattern
        self._state = CaptureState.PRESENTING
        self._metrics.frames_attempted += 1

        try:
            await asyncio.wait_for(
                self._presentation.show_single(pattern),
                timeout=self._config.presentation_timeout,
            )
        except TimeoutError as exc:
            raise CaptureTimeoutError(
                f"Presentation timed out after {self._config.presentation_timeout}s"
            ) from exc
        except Exception as exc:
            raise CaptureError(f"Presentation failed: {exc}") from exc

        # Read presentation timestamp from session state
        presentation_ns = self._presentation.state.timestamp_ns
        if presentation_ns is None:
            # Fallback: should not happen with well-behaved presentation
            presentation_ns = time.monotonic_ns()
            _logger.warning(
                "Presentation returned no timestamp, using monotonic fallback"
            )

        # Phase 2: Settle time
        if self._config.min_settle_ms > 0:
            await asyncio.sleep(self._config.min_settle_ms / 1000.0)

        # Phase 3: Capture frame
        self._state = CaptureState.WAITING

        try:
            frame: Frame = await asyncio.wait_for(
                self._frame_source.capture_frame(self._camera_id),
                timeout=self._config.capture_timeout,
            )
        except TimeoutError as exc:
            raise CaptureTimeoutError(
                f"Frame capture timed out after {self._config.capture_timeout}s"
            ) from exc
        except CameraError as exc:
            raise CameraDisconnectError(f"Camera error: {exc}") from exc

        # Phase 4: Frame received
        self._state = CaptureState.CAPTURED

        # Phase 5: Validate acceptance
        self._state = CaptureState.VALIDATING
        self._acceptance.accept(frame, pattern, sequence)

        # Phase 6: Compute timestamps and latency
        capture_ns = (
            frame.timestamp_ns
            if frame.timestamp_ns is not None
            else time.monotonic_ns()
        )
        latency_ms = (capture_ns - presentation_ns) / 1_000_000

        # Build stamped Frame with presentation metadata
        stamped = Frame(
            image=frame.image,
            timestamp=frame.timestamp,
            camera_id=frame.camera_id,
            frame_number=frame.frame_number,
            timestamp_ns=capture_ns,
            presentation_timestamp_ns=presentation_ns,
            sequence_id=sequence.sequence_id,
            pattern_id=pattern.pattern_id,
            capture_latency_ms=float(latency_ms),
            exposure_ms=frame.exposure_ms,
            gain=frame.gain,
            projector_state=f"pattern_{pattern.pattern_id}",
        )

        # Record latency metric
        self._metrics.latencies_ms.append(float(latency_ms))

        # Convert to domain CalibrationFrame
        cc = stamped.to_camera_capture()
        return CalibrationFrame(capture=cc, pattern=pattern)
