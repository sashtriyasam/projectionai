"""Tests for CaptureSession — capture state machine + recovery layer.

Covers:
- Happy-path capture sequence
- Frame acceptance/rejection (sequence_id, pattern_id, image shape/dtype)
- Retry with bounded attempts
- Camera disconnect → partial recovery
- Cooperative cancellation at pattern boundaries
- Partial sequence preservation on mid-sequence failure
- Metrics tracking (latencies, retries, frames_accepted/rejected)
- Timeout handling (capture and presentation)
- State machine transitions
- Warmup frame drain
- DefaultFrameAcceptance monotonicity validation
- Stale frame detection
- CaptureResult properties
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from projectionai.domain.calibration_session import (
    CalibrationMethod,
    CalibrationPattern,
    CalibrationSequence,
    PatternAxis,
)
from projectionai.services.camera import Frame
from projectionai.services.capture_session import (
    CaptureConfig,
    CaptureMetrics,
    CaptureResult,
    CaptureSession,
    CaptureState,
    DefaultFrameAcceptance,
    FrameRejectionError,
)
from projectionai.services.pattern_engine import PatternEngine
from projectionai.services.pattern_presentation import PatternPresentationState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seq(w: int = 8, h: int = 6) -> CalibrationSequence:
    """Generate a small calibration sequence for tests."""
    PatternEngine.clear_cache()
    return PatternEngine().generate(w, h)


def _frame(
    camera_id: str = "cam-0",
    frame_number: int = 1,
    seq_id: str | None = None,
    pat_id: int | None = None,
) -> Frame:
    """Build a minimal valid Frame."""
    return Frame(
        image=np.zeros((4, 4, 3), dtype=np.uint8),
        timestamp=time.monotonic(),
        timestamp_ns=time.monotonic_ns(),
        camera_id=camera_id,
        frame_number=frame_number,
        sequence_id=seq_id,
        pattern_id=pat_id,
    )


class FakePresentation:
    """Minimal PatternPresentationSession stand-in for CaptureSession tests."""

    def __init__(
        self,
        fail_on_show: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.shows: list[str] = []
        self.hides = 0
        self.fail_on_show = fail_on_show
        self.delay = delay
        self._ts_ns: int = 0

    async def show_single(self, pattern: Any) -> None:
        if self.fail_on_show:
            raise RuntimeError("presentation failed")
        if self.delay:
            await asyncio.sleep(self.delay)
        self._ts_ns = time.monotonic_ns()
        self.shows.append(f"pat_{pattern.pattern_id}")

    async def hide(self) -> None:
        self.hides += 1

    @property
    def state(self) -> PatternPresentationState:
        return PatternPresentationState(
            pattern_index=0,
            total_patterns=1,
            mode="single_pattern",
            timestamp_ns=self._ts_ns,
            timestamp_kind="best_effort",
            is_complete=True,
        )


class FakeFrameSource:
    """Minimal FrameSource stand-in for CaptureSession tests."""

    def __init__(
        self,
        fail: bool = False,
        delay: float = 0.0,
        wrong_seq: bool = False,
        wrong_pat: bool = False,
        disconnect_on_pattern: int | None = None,
    ) -> None:
        self.calls = 0
        self.fail = fail
        self.delay = delay
        self.wrong_seq = wrong_seq
        self.wrong_pat = wrong_pat
        self.disconnect_on_pattern = disconnect_on_pattern

    async def capture_frame(self, camera_id: str) -> Frame:
        self.calls += 1
        if self.fail:
            raise RuntimeError("camera failed")
        if self.delay:
            await asyncio.sleep(self.delay)
        return Frame(
            image=np.zeros((4, 4, 3), dtype=np.uint8),
            timestamp=time.monotonic(),
            timestamp_ns=time.monotonic_ns(),
            camera_id=camera_id,
            frame_number=self.calls,
            sequence_id="WRONG" if self.wrong_seq else None,
            pattern_id=999 if self.wrong_pat else None,
        )


def _make_session(
    presentation: Any = None,
    source: Any = None,
    config: CaptureConfig | None = None,
) -> tuple[CaptureSession, Any, Any]:
    """Create a CaptureSession with defaults."""
    pres = presentation or FakePresentation()
    src = source or FakeFrameSource()
    sess = CaptureSession(
        pres, src, "cam-0", config or CaptureConfig(min_settle_ms=0, warmup_frames=0)
    )
    return sess, pres, src


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCaptureSequenceHappyPath:
    """Tests for successful capture of a full sequence."""

    @pytest.mark.asyncio
    async def test_successful_capture_returns_all_frames(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        result = await sess.capture_sequence(seq)
        assert result.success is True
        assert result.state == CaptureState.COMPLETE
        assert len(result.frames) == len(seq.patterns)
        assert len(result.partial_frames) == len(seq.patterns)
        assert result.error is None
        assert result.failed_pattern_index is None
        assert result.failed_pattern_id is None

    @pytest.mark.asyncio
    async def test_frame_metadata_matches_pattern(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        result = await sess.capture_sequence(seq)
        for pat, cf in zip(seq.patterns, result.frames, strict=True):
            assert cf.capture.sequence_id == seq.sequence_id
            assert cf.capture.pattern_id == pat.pattern_id
            assert cf.capture.capture_latency_ms is not None
            assert cf.capture.capture_latency_ms >= 0.0

    @pytest.mark.asyncio
    async def test_presentation_hide_called_on_success(self) -> None:
        seq = _seq(8, 6)
        sess, pres, _ = _make_session()
        await sess.capture_sequence(seq)
        assert pres.hides >= 1

    @pytest.mark.asyncio
    async def test_state_is_idle_before_and_complete_after(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        assert sess.state == CaptureState.IDLE
        await sess.capture_sequence(seq)
        assert sess.state == CaptureState.COMPLETE

    @pytest.mark.asyncio
    async def test_reusable_across_multiple_calls(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        r1 = await sess.capture_sequence(seq)
        assert r1.success
        r2 = await sess.capture_sequence(seq)
        assert r2.success
        assert sess.state == CaptureState.COMPLETE


# ---------------------------------------------------------------------------
# Frame acceptance / rejection
# ---------------------------------------------------------------------------


class TestFrameAcceptance:
    """Tests for frame acceptance criteria."""

    @pytest.mark.asyncio
    async def test_wrong_sequence_id_returns_failed(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(source=FakeFrameSource(wrong_seq=True))
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED
        assert result.error is not None
        assert (
            "sequence_id mismatch" in result.error.lower()
            or "failed" in result.error.lower()
        )
        assert result.frames == ()
        assert result.failed_pattern_index == 0

    @pytest.mark.asyncio
    async def test_wrong_pattern_id_returns_failed(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(source=FakeFrameSource(wrong_pat=True))
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED

    @pytest.mark.asyncio
    async def test_invalid_image_shape_rejected(self) -> None:
        seq = _seq(8, 6)
        bad_source = MagicMock()
        bad_source.capture_frame = AsyncMock(
            return_value=Frame(
                image=np.zeros((4, 1), dtype=np.uint8),
                timestamp=time.monotonic(),
                camera_id="cam-0",
                frame_number=1,
            )
        )
        sess, _, _ = _make_session(source=bad_source)
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.frames == ()

    @pytest.mark.asyncio
    async def test_invalid_image_dtype_rejected(self) -> None:
        seq = _seq(8, 6)
        bad_source = MagicMock()
        bad_source.capture_frame = AsyncMock(
            return_value=Frame(
                image=np.zeros((4, 4, 3), dtype=np.float32),
                timestamp=time.monotonic(),
                camera_id="cam-0",
                frame_number=1,
            )
        )
        sess, _, _ = _make_session(source=bad_source)
        result = await sess.capture_sequence(seq)
        assert not result.success

    @pytest.mark.asyncio
    async def test_zero_settle_ms_skips_sleep(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0)
        )
        result = await sess.capture_sequence(seq)
        assert result.success


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


class TestRetry:
    """Tests for bounded retry behavior."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_initial_failure(self) -> None:
        seq = _seq(8, 6)

        class FlakySource:
            def __init__(self) -> None:
                self.calls = 0

            async def capture_frame(self, camera_id: str) -> Frame:
                self.calls += 1
                if self.calls == 1:  # warmup is disabled, so first call is pattern 0
                    return Frame(
                        image=np.zeros((4, 4, 3), dtype=np.uint8),
                        timestamp=time.monotonic(),
                        timestamp_ns=time.monotonic_ns(),
                        camera_id=camera_id,
                        frame_number=1,
                        sequence_id="WRONG",
                    )
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=self.calls,
                )

        flaky = FlakySource()
        sess, _, _ = _make_session(
            source=flaky,
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=1),
        )
        result = await sess.capture_sequence(seq)
        assert result.success
        assert sess.metrics.retries >= 1
        assert flaky.calls > len(seq.patterns)  # extra calls from retry

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_failed(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=2),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED
        assert sess.metrics.retries >= 2

    @pytest.mark.asyncio
    async def test_zero_retries_fails_immediately(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert sess.metrics.retries == 0


# ---------------------------------------------------------------------------
# Camera disconnect
# ---------------------------------------------------------------------------


class TestCameraDisconnect:
    """Tests for camera error / disconnect handling."""

    @pytest.mark.asyncio
    async def test_camera_error_returns_failed_with_partial(self) -> None:
        seq = _seq(8, 6)

        class DisconnectSource:
            def __init__(self) -> None:
                self.calls = 0

            async def capture_frame(self, camera_id: str) -> Frame:
                self.calls += 1
                if self.calls <= 2:  # first 2 patterns succeed
                    return Frame(
                        image=np.zeros((4, 4, 3), dtype=np.uint8),
                        timestamp=time.monotonic(),
                        timestamp_ns=time.monotonic_ns(),
                        camera_id=camera_id,
                        frame_number=self.calls,
                    )
                raise RuntimeError("camera disconnected")

        src = DisconnectSource()
        sess, _, _ = _make_session(
            source=src,
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED
        assert len(result.partial_frames) > 0
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_camera_error_on_warmup(self) -> None:
        seq = _seq(8, 6)
        fail_src = MagicMock()
        fail_src.capture_frame = AsyncMock(side_effect=RuntimeError("camera down"))
        sess, _, _ = _make_session(
            source=fail_src, config=CaptureConfig(warmup_frames=1)
        )
        result = await sess.capture_sequence(seq)
        assert not result.success

    @pytest.mark.asyncio
    async def test_presentation_error_returns_failed(self) -> None:
        seq = _seq(8, 6)
        pres = FakePresentation(fail_on_show=True)
        sess, _, _ = _make_session(presentation=pres)
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    """Tests for cooperative cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_before_sequence_returns_cancelled(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        sess.cancel()
        result = await sess.capture_sequence(seq)
        assert result.state == CaptureState.CANCELLED
        assert result.error is not None and "cancel" in result.error.lower()

    @pytest.mark.asyncio
    async def test_cancel_between_patterns_preserves_partial(self) -> None:
        seq = _seq(8, 6)
        cancel_after = 2
        shown = 0

        class CancelAfterPres:
            def __init__(self) -> None:
                self._ts_ns = 0
                self.hides = 0

            async def show_single(self, pattern: Any) -> None:
                nonlocal shown
                shown += 1
                self._ts_ns = time.monotonic_ns()

            async def hide(self) -> None:
                self.hides += 1

            @property
            def state(self) -> PatternPresentationState:
                return PatternPresentationState(
                    pattern_index=0,
                    total_patterns=1,
                    mode="single_pattern",
                    timestamp_ns=self._ts_ns,
                    timestamp_kind="best_effort",
                    is_complete=True,
                )

        pres = CancelAfterPres()
        src = FakeFrameSource()
        sess, _, _ = _make_session(presentation=pres, source=src)

        original_capture = sess._capture_one_with_retry

        async def canceller(pattern, seq, idx):
            if idx == cancel_after:
                sess.cancel()
            return await original_capture(pattern, seq, idx)

        sess._capture_one_with_retry = canceller  # type: ignore[method-assign]
        result = await sess.capture_sequence(seq)
        assert result.state == CaptureState.CANCELLED
        assert len(result.partial_frames) >= cancel_after

    @pytest.mark.asyncio
    async def test_cancelled_error_returns_cancelled_result(self) -> None:
        seq = _seq(8, 6)

        class SlowSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                await asyncio.sleep(10.0)
                return _frame(camera_id)

        pres = FakePresentation()
        sess, _, _ = _make_session(presentation=pres, source=SlowSource())
        task = asyncio.create_task(sess.capture_sequence(seq))
        await asyncio.sleep(0.05)
        task.cancel()
        result = await task
        assert result.state == CaptureState.CANCELLED
        assert result.success is False
        assert "cancel" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Partial sequence preservation
# ---------------------------------------------------------------------------


class TestPartialSequence:
    """Tests for partial frame preservation on mid-sequence failure."""

    @pytest.mark.asyncio
    async def test_partial_frames_on_third_pattern_failure(self) -> None:
        seq = _seq(8, 6)

        class FailOnThird:
            def __init__(self) -> None:
                self.calls = 0

            async def capture_frame(self, camera_id: str) -> Frame:
                self.calls += 1
                if self.calls == 3:  # fail on 3rd pattern capture
                    raise RuntimeError("camera died")
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=self.calls,
                )

        src = FailOnThird()
        sess, _, _ = _make_session(
            source=src,
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert len(result.partial_frames) == 2

    @pytest.mark.asyncio
    async def test_no_partial_frames_on_first_failure(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.frames == ()
        assert result.partial_frames == ()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    """Tests for CaptureMetrics tracking."""

    @pytest.mark.asyncio
    async def test_metrics_track_accepted_frames(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        result = await sess.capture_sequence(seq)
        assert result.metrics.frames_attempted == len(seq.patterns)
        assert result.metrics.frames_accepted == len(seq.patterns)
        assert result.metrics.frames_rejected == 0

    @pytest.mark.asyncio
    async def test_metrics_track_rejected_frames(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert result.metrics.frames_rejected >= 1
        assert result.metrics.stale_frames >= 1

    @pytest.mark.asyncio
    async def test_metrics_track_retries(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=2),
        )
        result = await sess.capture_sequence(seq)
        assert result.metrics.retries >= 2

    @pytest.mark.asyncio
    async def test_metrics_latency_values(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            config=CaptureConfig(min_settle_ms=5, warmup_frames=0)
        )
        result = await sess.capture_sequence(seq)
        for lat in result.metrics.latencies_ms:
            assert lat >= 0.0
        assert result.metrics.p50 is not None
        assert result.metrics.max_latency is not None

    @pytest.mark.asyncio
    async def test_metrics_empty_on_no_frames(self) -> None:
        m = CaptureMetrics()
        assert m.p50 is None
        assert m.p95 is None
        assert m.p99 is None
        assert m.max_latency is None
        assert m.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_metrics_success_rate(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        result = await sess.capture_sequence(seq)
        assert result.metrics.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_metrics_reset_on_new_capture(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        r1 = await sess.capture_sequence(seq)
        assert r1.metrics.frames_attempted == len(seq.patterns)
        r2 = await sess.capture_sequence(seq)
        assert r2.metrics.frames_attempted == len(seq.patterns)
        # metrics should be fresh, not cumulative
        assert r2.metrics.frames_rejected == 0


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    """Tests for capture timeout handling."""

    @pytest.mark.asyncio
    async def test_capture_timeout(self) -> None:
        seq = _seq(8, 6)

        class SlowSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                await asyncio.sleep(10.0)
                return _frame(camera_id)

        sess, _, _ = _make_session(
            source=SlowSource(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=0,
                capture_timeout=0.05,
                retry_count=0,
            ),
        )
        result = await sess.capture_sequence(seq)
        assert result.state == CaptureState.TIMEOUT
        assert not result.success

    @pytest.mark.asyncio
    async def test_presentation_timeout(self) -> None:
        seq = _seq(8, 6)

        class SlowPres(FakePresentation):
            async def show_single(self, pattern: Any) -> None:
                await asyncio.sleep(10.0)
                self._ts_ns = time.monotonic_ns()

        sess, _, _ = _make_session(
            presentation=SlowPres(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=0,
                presentation_timeout=0.05,
                retry_count=0,
            ),
        )
        result = await sess.capture_sequence(seq)
        assert result.state == CaptureState.TIMEOUT
        assert not result.success

    @pytest.mark.asyncio
    async def test_warmup_timeout(self) -> None:
        seq = _seq(8, 6)

        class SlowSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                await asyncio.sleep(10.0)
                return _frame(camera_id)

        sess, _, _ = _make_session(
            source=SlowSource(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=1,
                capture_timeout=0.05,
                retry_count=0,
            ),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateMachine:
    """Tests for capture state transitions."""

    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self) -> None:
        sess, _, _ = _make_session()
        assert sess.state == CaptureState.IDLE

    @pytest.mark.asyncio
    async def test_final_state_complete_on_success(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session()
        result = await sess.capture_sequence(seq)
        assert sess.state == CaptureState.COMPLETE
        assert result.state == CaptureState.COMPLETE

    @pytest.mark.asyncio
    async def test_final_state_failed_on_error(self) -> None:
        seq = _seq(8, 6)
        sess, _, _ = _make_session(source=FakeFrameSource(fail=True))
        await sess.capture_sequence(seq)
        assert sess.state == CaptureState.FAILED

    @pytest.mark.asyncio
    async def test_final_state_timeout_on_timeout(self) -> None:
        seq = _seq(8, 6)

        class SlowSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                await asyncio.sleep(10.0)
                return _frame(camera_id)

        sess, _, _ = _make_session(
            source=SlowSource(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=0,
                capture_timeout=0.05,
                retry_count=0,
            ),
        )
        await sess.capture_sequence(seq)
        assert sess.state == CaptureState.TIMEOUT

    @pytest.mark.asyncio
    async def test_reject_concurrent_capture(self) -> None:
        seq = _seq(8, 6)

        class SlowSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                await asyncio.sleep(1.0)
                return _frame(camera_id)

        sess, _, _ = _make_session(
            source=SlowSource(),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, capture_timeout=5.0),
        )
        t1 = asyncio.create_task(sess.capture_sequence(seq))
        await asyncio.sleep(0.05)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sess.capture_sequence(seq), timeout=0.05)
        t1.cancel()
        result = await t1
        assert result.state == CaptureState.CANCELLED


# ---------------------------------------------------------------------------
# Warmup
# ---------------------------------------------------------------------------


class TestWarmup:
    """Tests for warmup frame drain."""

    @pytest.mark.asyncio
    async def test_warmup_drains_frames_before_sequence(self) -> None:
        seq = _seq(8, 6)
        src = FakeFrameSource()
        sess, _, _ = _make_session(
            source=src, config=CaptureConfig(min_settle_ms=0, warmup_frames=2)
        )
        result = await sess.capture_sequence(seq)
        assert result.success
        # 2 warmup + 6 patterns = 8 total calls
        assert src.calls == len(seq.patterns) + 2

    @pytest.mark.asyncio
    async def test_warmup_zero_skips_drain(self) -> None:
        seq = _seq(8, 6)
        src = FakeFrameSource()
        sess, _, _ = _make_session(
            source=src, config=CaptureConfig(min_settle_ms=0, warmup_frames=0)
        )
        result = await sess.capture_sequence(seq)
        assert result.success
        assert src.calls == len(seq.patterns)


# ---------------------------------------------------------------------------
# DefaultFrameAcceptance
# ---------------------------------------------------------------------------


class TestDefaultFrameAcceptance:
    """Tests for the DefaultFrameAcceptance policy."""

    def test_rejects_none_frame(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        with pytest.raises(FrameRejectionError, match="None"):
            acc.accept(None, pat, seq)  # type: ignore[arg-type]

    def test_rejects_invalid_shape(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 1, 3, 1), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
        )
        with pytest.raises(FrameRejectionError, match="dimensions"):
            acc.accept(frame, pat, seq)

    def test_rejects_invalid_channels(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4, 5), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
        )
        with pytest.raises(FrameRejectionError, match="channels"):
            acc.accept(frame, pat, seq)

    def test_rejects_wrong_dtype(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4, 3), dtype=np.float32),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
        )
        with pytest.raises(FrameRejectionError, match="dtype"):
            acc.accept(frame, pat, seq)

    def test_rejects_sequence_id_mismatch(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            sequence_id="WRONG",
        )
        with pytest.raises(FrameRejectionError, match="sequence_id"):
            acc.accept(frame, pat, seq)

    def test_rejects_pattern_id_mismatch(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            pattern_id=999,
        )
        with pytest.raises(FrameRejectionError, match="pattern_id"):
            acc.accept(frame, pat, seq)

    def test_accepts_valid_frame(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
        )
        acc.accept(frame, pat, seq)  # should not raise

    def test_accepts_frame_with_matching_ids(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            sequence_id="seq-0",
            pattern_id=0,
        )
        acc.accept(frame, pat, seq)  # should not raise

    def test_rejects_negative_latency(self) -> None:
        acc = DefaultFrameAcceptance(CaptureConfig(max_capture_latency_ms=500.0))
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            capture_latency_ms=-5.0,
        )
        with pytest.raises(FrameRejectionError, match="Negative"):
            acc.accept(frame, pat, seq)

    def test_rejects_excessive_latency(self) -> None:
        acc = DefaultFrameAcceptance(CaptureConfig(max_capture_latency_ms=100.0))
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        frame = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            capture_latency_ms=999.0,
        )
        with pytest.raises(FrameRejectionError, match="exceeds"):
            acc.accept(frame, pat, seq)

    def test_rejects_non_monotonic_presentation_timestamps(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        f1 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            presentation_timestamp_ns=200,
        )
        f2 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=2,
            presentation_timestamp_ns=100,
        )
        acc.accept(f1, pat, seq)
        with pytest.raises(FrameRejectionError, match="non-monotonic"):
            acc.accept(f2, pat, seq)

    def test_rejects_non_monotonic_capture_timestamps(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        f1 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            timestamp_ns=200,
        )
        f2 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=2,
            timestamp_ns=100,
        )
        acc.accept(f1, pat, seq)
        with pytest.raises(FrameRejectionError, match="non-monotonic"):
            acc.accept(f2, pat, seq)

    def test_reset_clears_monotonicity_tracking(self) -> None:
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        f1 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            timestamp_ns=200,
        )
        acc.accept(f1, pat, seq)
        acc.reset()
        # After reset, a lower timestamp should not fail monotonicity
        f2 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=2,
            timestamp_ns=100,
        )
        acc.accept(f2, pat, seq)  # should not raise


# ---------------------------------------------------------------------------
# CaptureResult
# ---------------------------------------------------------------------------


class TestCaptureResult:
    """Tests for CaptureResult dataclass."""

    def test_success_property(self) -> None:
        r = CaptureResult(
            state=CaptureState.COMPLETE,
            frames=(),
            partial_frames=(),
            metrics=CaptureMetrics(),
        )
        assert r.success is True

    def test_failure_property(self) -> None:
        r = CaptureResult(
            state=CaptureState.FAILED,
            frames=(),
            partial_frames=(),
            metrics=CaptureMetrics(),
            error="test error",
        )
        assert r.success is False

    def test_timeout_property(self) -> None:
        r = CaptureResult(
            state=CaptureState.TIMEOUT,
            frames=(),
            partial_frames=(),
            metrics=CaptureMetrics(),
        )
        assert r.success is False

    def test_cancelled_property(self) -> None:
        r = CaptureResult(
            state=CaptureState.CANCELLED,
            frames=(),
            partial_frames=(),
            metrics=CaptureMetrics(),
        )
        assert r.success is False


# ---------------------------------------------------------------------------
# CaptureConfig validation
# ---------------------------------------------------------------------------


class TestCaptureConfig:
    """Tests for CaptureConfig frozen dataclass."""

    def test_defaults(self) -> None:
        c = CaptureConfig()
        assert c.min_settle_ms == 20.0
        assert c.max_capture_latency_ms == 500.0
        assert c.capture_timeout == 5.0
        assert c.presentation_timeout == 2.0
        assert c.retry_count == 1
        assert c.warmup_frames == 1
        assert c.max_stale_frames == 0

    def test_custom_values(self) -> None:
        c = CaptureConfig(min_settle_ms=0, retry_count=5, warmup_frames=0)
        assert c.min_settle_ms == 0
        assert c.retry_count == 5
        assert c.warmup_frames == 0

    def test_frozen(self) -> None:
        c = CaptureConfig()
        with pytest.raises(AttributeError):
            c.min_settle_ms = 100  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CaptureMetrics percentile edge cases
# ---------------------------------------------------------------------------


class TestCaptureMetricsPercentiles:
    """Tests for CaptureMetrics percentile calculations."""

    def test_single_value_percentiles(self) -> None:
        m = CaptureMetrics(latencies_ms=[10.0])
        assert m.p50 == 10.0
        assert m.p95 == 10.0
        assert m.p99 == 10.0
        assert m.max_latency == 10.0

    def test_empty_latencies(self) -> None:
        m = CaptureMetrics()
        assert m.p50 is None
        assert m.p95 is None
        assert m.p99 is None
        assert m.max_latency is None

    def test_success_rate_calculation(self) -> None:
        m = CaptureMetrics(frames_attempted=10, frames_accepted=7)
        assert m.success_rate == pytest.approx(0.7)

    def test_success_rate_zero_attempted(self) -> None:
        m = CaptureMetrics()
        assert m.success_rate == 0.0


# ---------------------------------------------------------------------------
# GATE 2: Exception classification
# ---------------------------------------------------------------------------


class TestExceptionClassification:
    """GATE 2: Programming errors must NOT be silently converted
    to CameraDisconnectError."""

    @pytest.mark.asyncio
    async def test_programming_error_not_masked_as_disconnect(self) -> None:
        """A programming error (AttributeError) in FrameSource must NOT be
        silently converted to CameraDisconnectError."""

        class BuggySource:
            async def capture_frame(self, camera_id: str) -> Frame:
                raise AttributeError("internal bug: typo in attribute name")

        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=BuggySource(),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        # The error message should contain the original bug details,
        # NOT be prefixed with "camera disconnect"
        assert result.error is not None
        assert "camera disconnect" not in result.error.lower()
        assert "internal bug" in result.error.lower()
        # camera_errors should NOT be incremented for a programming bug
        assert sess.metrics.camera_errors == 0

    @pytest.mark.asyncio
    async def test_camera_error_is_still_classified(self) -> None:
        """A real CameraError (CameraDisconnectError) IS correctly classified."""
        from projectionai.core.errors import CameraError

        class RealCameraError:
            async def capture_frame(self, camera_id: str) -> Frame:
                raise CameraError("device unplugged")

        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=RealCameraError(),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED
        assert sess.metrics.camera_errors == 1


# ---------------------------------------------------------------------------
# GATE 5: Stale frame semantics
# ---------------------------------------------------------------------------


class TestStaleFrameSemantics:
    """GATE 5: Stale frame detection and max_stale_frames behavior."""

    @pytest.mark.asyncio
    async def test_stale_frame_rejected_immediately_with_zero_tolerance(
        self,
    ) -> None:
        """max_stale_frames=0: stale frame is rejected (FrameRejectionError)
        and retried normally — not escalated to disconnect."""
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.state == CaptureState.FAILED
        # Stale frame was counted
        assert sess.metrics.stale_frames >= 1
        assert sess.metrics.frames_rejected >= 1

    @pytest.mark.asyncio
    async def test_stale_frame_escalates_after_threshold(self) -> None:
        """max_stale_frames=2: first 2 stale frames are retried,
        third escalates to CameraDisconnectError."""
        call_count = 0

        class StaleSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                nonlocal call_count
                call_count += 1
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=call_count,
                    sequence_id="WRONG",
                )

        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=StaleSource(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=0,
                retry_count=10,
                max_stale_frames=2,
            ),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        # After 3 stale frames (> threshold), escalated to disconnect
        assert sess.metrics.stale_frames >= 3
        assert sess.metrics.camera_errors >= 1

    @pytest.mark.asyncio
    async def test_correct_ids_but_wrong_dtype_rejected(self) -> None:
        """Frame with correct IDs but wrong dtype is rejected."""
        seq = _seq(8, 6)

        class WrongDtypeSource:
            async def capture_frame(self, camera_id: str) -> Frame:
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.float32),  # wrong dtype
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=1,
                )

        sess, _, _ = _make_session(
            source=WrongDtypeSource(),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        assert result.frames == ()

    @pytest.mark.asyncio
    async def test_stale_timestamp_rejected(self) -> None:
        """Frame with non-monotonic timestamp is rejected."""
        acc = DefaultFrameAcceptance()
        pat = CalibrationPattern(
            pattern_id=0,
            sequence_id="seq-0",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=np.zeros((4, 4), dtype=np.uint8),
            width=4,
            height=4,
        )
        seq_obj = CalibrationSequence(
            sequence_id="seq-0",
            method=CalibrationMethod.GRAY_CODE,
            patterns=(pat,),
            width=4,
            height=4,
            bits_x=1,
            bits_y=0,
        )
        f1 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=1,
            timestamp_ns=200,
        )
        f2 = Frame(
            image=np.zeros((4, 4), dtype=np.uint8),
            timestamp=time.monotonic(),
            camera_id="cam-0",
            frame_number=2,
            timestamp_ns=100,  # older timestamp
        )
        acc.accept(f1, pat, seq_obj)
        with pytest.raises(FrameRejectionError, match="non-monotonic"):
            acc.accept(f2, pat, seq_obj)


# ---------------------------------------------------------------------------
# GATE 7: Partial sequence data integrity
# ---------------------------------------------------------------------------


class TestDataIntegrity:
    """GATE 7: Partial sequence must not be treated as complete."""

    @pytest.mark.asyncio
    async def test_frames_empty_on_failure(self) -> None:
        """On failure, result.frames must be empty (not partial data).
        Partial data is only in result.partial_frames."""
        seq = _seq(8, 6)

        class FailOnThird:
            def __init__(self) -> None:
                self.calls = 0

            async def capture_frame(self, camera_id: str) -> Frame:
                self.calls += 1
                if self.calls == 3:
                    raise RuntimeError("camera died")
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=self.calls,
                )

        src = FailOnThird()
        sess, _, _ = _make_session(
            source=src,
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        result = await sess.capture_sequence(seq)
        assert not result.success
        # frames must be EMPTY on failure — not partial data
        assert result.frames == ()
        # partial_frames preserves valid frames before failure
        assert len(result.partial_frames) == 2

    @pytest.mark.asyncio
    async def test_no_cross_sequence_contamination(self) -> None:
        """Metrics reset between capture_sequence calls."""
        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=FakeFrameSource(wrong_seq=True),
            config=CaptureConfig(min_settle_ms=0, warmup_frames=0, retry_count=0),
        )
        r1 = await sess.capture_sequence(seq)
        assert r1.metrics.stale_frames >= 1
        # Second call resets metrics
        r2 = await sess.capture_sequence(seq)
        assert r2.metrics.stale_frames >= 1
        # Not cumulative — each call starts fresh
        assert r2.metrics.stale_frames == r1.metrics.stale_frames


# ---------------------------------------------------------------------------
# GATE 8: Cancellation stops retry
# ---------------------------------------------------------------------------


class TestCancelStopsRetry:
    """GATE 8: Cancellation during retry must stop the retry loop."""

    @pytest.mark.asyncio
    async def test_cancel_during_retry_stops_loop(self) -> None:
        """Cancel while retrying must not continue to next attempt."""
        attempt_count = 0

        class AlwaysReject:
            async def capture_frame(self, camera_id: str) -> Frame:
                nonlocal attempt_count
                attempt_count += 1
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=attempt_count,
                    sequence_id="WRONG",
                )

        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=AlwaysReject(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=0,
                retry_count=100,
            ),
        )
        # Cancel before starting
        sess.cancel()
        result = await sess.capture_sequence(seq)
        assert result.state == CaptureState.CANCELLED
        # Should not have made many attempts
        assert attempt_count == 0

    @pytest.mark.asyncio
    async def test_cancel_between_retries(self) -> None:
        """sess.cancel() during retry execution stops the loop via _cancelled flag."""
        attempt_count = 0

        class AlwaysReject:
            async def capture_frame(self, camera_id: str) -> Frame:
                nonlocal attempt_count
                attempt_count += 1
                # Yield to event loop so cancel task can run
                await asyncio.sleep(0)
                # Cancel deterministically after 3 attempts
                if attempt_count == 3:
                    sess.cancel()
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=attempt_count,
                    sequence_id="WRONG",
                )

        seq = _seq(8, 6)
        sess, _, _ = _make_session(
            source=AlwaysReject(),
            config=CaptureConfig(
                min_settle_ms=0,
                warmup_frames=0,
                retry_count=100,
                capture_timeout=10.0,
            ),
        )

        result = await sess.capture_sequence(seq)
        assert result.state == CaptureState.CANCELLED
        assert attempt_count == 3
