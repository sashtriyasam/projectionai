from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field

from projectionai.core.errors import CameraError
from projectionai.domain.calibration_session import (
    CalibrationFrame,
    CalibrationPattern,
    CalibrationSequence,
)
from projectionai.services.camera import Frame
from projectionai.services.projector_calibration import (
    FrameSource,
    PatternMismatchError,
    PatternProjector,
    ProjectorCalibrationError,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncConfig:
    min_settle_ms: float = 20.0
    max_capture_latency_ms: float = 500.0
    capture_timeout: float = 5.0
    presentation_timeout: float = 2.0
    retry_count: int = 1
    projector_state_prefix: str = "pattern_"
    warmup_frames: int = 1


@dataclass
class CaptureMetrics:
    latencies_ms: list[float] = field(default_factory=list)
    presentation_timestamps_ns: list[int] = field(default_factory=list)
    capture_timestamps_ns: list[int] = field(default_factory=list)
    retries: int = 0
    mismatches: int = 0
    dropped: int = 0

    @property
    def p50(self) -> float | None:
        return _percentile(self.latencies_ms, 50)

    @property
    def p95(self) -> float | None:
        return _percentile(self.latencies_ms, 95)

    @property
    def p99(self) -> float | None:
        return _percentile(self.latencies_ms, 99)


def _percentile(data: list[float], p: int) -> float | None:
    if not data:
        return None
    s = sorted(data)
    k = int((p / 100) * (len(s) - 1))
    return float(s[k])


class SynchronizedCaptureSession:
    def __init__(
        self,
        frame_source: FrameSource,
        camera_id: str,
        projector: PatternProjector,
        config: SyncConfig | None = None,
    ) -> None:
        self._source = frame_source
        self._camera_id = camera_id
        self._projector = projector
        self._config = config or SyncConfig()
        self._metrics = CaptureMetrics()

    @property
    def metrics(self) -> CaptureMetrics:
        return self._metrics

    async def capture_sequence(
        self, sequence: CalibrationSequence
    ) -> tuple[CalibrationFrame, ...]:
        frames: list[CalibrationFrame] = []
        self._metrics = CaptureMetrics()
        try:
            await self._warmup()
            for pattern in sequence.patterns:
                cf = await self._capture_one(pattern, sequence)
                frames.append(cf)
        finally:
            with contextlib.suppress(Exception):
                await self._projector.hide()
        return tuple(frames)

    async def _warmup(self) -> None:
        """Drain ``warmup_frames`` frames so the first pattern capture runs
        at steady-state (auto-exposure settled, driver buffer flushed) instead
        of paying the first-frame latency inside the sequence."""
        for _ in range(self._config.warmup_frames):
            try:
                await asyncio.wait_for(
                    self._source.capture_frame(self._camera_id),
                    timeout=self._config.capture_timeout,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                raise ProjectorCalibrationError(
                    f"Warmup capture timed out after {self._config.capture_timeout}s"
                ) from exc
            except Exception as exc:
                raise ProjectorCalibrationError(
                    f"Warmup capture failed: {exc}"
                ) from exc

    async def _capture_one(
        self, pattern: CalibrationPattern, sequence: CalibrationSequence
    ) -> CalibrationFrame:
        last_error: Exception | None = None
        for attempt in range(self._config.retry_count + 1):
            try:
                return await self._try_capture(pattern, sequence, attempt)
            except ProjectorCalibrationError as exc:
                last_error = exc
                if isinstance(exc, PatternMismatchError):
                    self._metrics.mismatches += 1
                if attempt < self._config.retry_count:
                    self._metrics.retries += 1
                    continue
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._config.retry_count:
                    self._metrics.retries += 1
                    continue
                raise ProjectorCalibrationError(f"Capture failed: {exc}") from exc
        raise ProjectorCalibrationError(
            f"Capture exhausted retries: {last_error}"
        ) from last_error

    async def _try_capture(
        self, pattern: CalibrationPattern, sequence: CalibrationSequence, attempt: int
    ) -> CalibrationFrame:
        await self._projector.show(pattern.image)
        try:
            presentation_ns = await self._presentation_barrier()
        except TimeoutError as exc:
            raise ProjectorCalibrationError(
                f"Presentation barrier timeout after {self._config.presentation_timeout}s"
            ) from exc
        except Exception as exc:
            raise ProjectorCalibrationError(f"Presentation failed: {exc}") from exc

        if self._config.min_settle_ms > 0:
            await asyncio.sleep(self._config.min_settle_ms / 1000.0)

        try:
            frame: Frame = await asyncio.wait_for(
                self._source.capture_frame(self._camera_id),
                timeout=self._config.capture_timeout,
            )
        except CameraError as exc:
            raise ProjectorCalibrationError(f"Frame capture failed: {exc}") from exc
        except TimeoutError as exc:
            raise ProjectorCalibrationError(
                f"Frame capture timed out after {self._config.capture_timeout}s"
            ) from exc

        capture_ns = (
            frame.timestamp_ns
            if frame.timestamp_ns is not None
            else time.monotonic_ns()
        )
        capture_ts = frame.timestamp if frame.timestamp else capture_ns / 1_000_000_000
        # Both capture_ns and presentation_ns are in the same monotonic clock
        # domain (time.monotonic_ns()), per the Frame timestamp contract.
        # When timestamp_ns is absent, the fallback to time.monotonic_ns() at
        # capture time preserves this compatibility.
        latency_ms = (capture_ns - presentation_ns) / 1_000_000

        if latency_ms < -1.0:
            raise ProjectorCalibrationError(
                f"Negative latency {latency_ms:.2f}ms — non-monotonic clocks"
            )
        if latency_ms > self._config.max_capture_latency_ms:
            if attempt < self._config.retry_count:
                raise ProjectorCalibrationError(
                    f"Capture latency {latency_ms:.2f}ms exceeds {self._config.max_capture_latency_ms}ms"
                )
            self._metrics.dropped += 1
            raise ProjectorCalibrationError(
                f"Capture latency {latency_ms:.2f}ms exceeds {self._config.max_capture_latency_ms}ms (exhausted retries)"
            )

        self._metrics.latencies_ms.append(float(latency_ms))
        self._metrics.presentation_timestamps_ns.append(int(presentation_ns))
        self._metrics.capture_timestamps_ns.append(int(capture_ns))

        if len(self._metrics.capture_timestamps_ns) >= 2:
            if (
                self._metrics.capture_timestamps_ns[-1]
                < self._metrics.capture_timestamps_ns[-2]
            ):
                raise ProjectorCalibrationError("Capture timestamps non-monotonic")
            if (
                self._metrics.presentation_timestamps_ns[-1]
                < self._metrics.presentation_timestamps_ns[-2]
            ):
                raise ProjectorCalibrationError("Presentation timestamps non-monotonic")

        if frame.sequence_id is not None and frame.sequence_id != sequence.sequence_id:
            raise PatternMismatchError(
                f"sequence_id mismatch: got {frame.sequence_id!r} expected {sequence.sequence_id!r}"
            )
        if frame.pattern_id is not None and frame.pattern_id != pattern.pattern_id:
            raise PatternMismatchError(
                f"pattern_id mismatch: got {frame.pattern_id} expected {pattern.pattern_id}"
            )

        stamped = Frame(
            image=frame.image,
            timestamp=capture_ts,
            timestamp_ns=capture_ns,
            presentation_timestamp_ns=presentation_ns,
            camera_id=frame.camera_id,
            frame_number=frame.frame_number,
            sequence_id=sequence.sequence_id,
            pattern_id=pattern.pattern_id,
            capture_latency_ms=float(latency_ms),
            exposure_ms=frame.exposure_ms,
            gain=frame.gain,
            projector_state=f"{self._config.projector_state_prefix}{pattern.pattern_id}",
        )
        cc = stamped.to_camera_capture()
        try:
            cf = CalibrationFrame(capture=cc, pattern=pattern)
        except ValueError as exc:
            raise ProjectorCalibrationError(str(exc)) from exc
        return cf

    async def _presentation_barrier(self) -> int:
        from typing import Any as _Any

        proj: _Any = self._projector
        vsync = getattr(proj, "vsync", None)
        if vsync is not None and callable(vsync):
            try:
                coro = vsync()
                result = await asyncio.wait_for(
                    coro, timeout=self._config.presentation_timeout
                )
                if isinstance(result, int):
                    return result
                return int(time.monotonic_ns())
            except TimeoutError:
                raise
            except Exception as exc:
                _logger.warning(
                    "Projector %r vsync() failed (%s), falling back to monotonic clock",
                    getattr(proj, "name", None)
                    or getattr(proj, "projector_id", None)
                    or type(proj).__name__,
                    exc,
                )
                return int(time.monotonic_ns())
        return int(time.monotonic_ns())
