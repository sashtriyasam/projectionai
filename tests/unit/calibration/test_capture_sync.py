from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from projectionai.domain.calibration_session import (
    CalibrationSequence,
)
from projectionai.infrastructure.projector_calibration.sync import (
    CaptureMetrics,
    SyncConfig,
    SynchronizedCaptureSession,
)
from projectionai.services.camera import Frame
from projectionai.services.pattern_engine import PatternEngine
from projectionai.services.projector_calibration import ProjectorCalibrationError


class FakeProjector:
    def __init__(self, fail_on_show: bool = False, vsync_delay: float = 0.0) -> None:
        self.shown: list[int] = []
        self.hidden = 0
        self.fail_on_show = fail_on_show
        self.vsync_delay = vsync_delay

    async def show(self, image) -> None:  # type: ignore[no-untyped-def]
        if self.fail_on_show:
            raise RuntimeError("projector failed")
        self.shown.append(1)
        if self.vsync_delay:
            await asyncio.sleep(self.vsync_delay)

    async def hide(self) -> None:
        self.hidden += 1

    async def vsync(self) -> int:
        return time.monotonic_ns()


class FakeFrameSource:
    def __init__(
        self,
        fail: bool = False,
        delay: float = 0.0,
        wrong_seq: bool = False,
        wrong_pat: bool = False,
    ) -> None:
        self.calls = 0
        self.fail = fail
        self.delay = delay
        self.wrong_seq = wrong_seq
        self.wrong_pat = wrong_pat

    async def capture_frame(self, camera_id: str) -> Frame:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("camera failed")
        if self.delay:
            await asyncio.sleep(self.delay)
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        return Frame(
            image=img,
            timestamp=time.monotonic(),
            timestamp_ns=time.monotonic_ns(),
            camera_id=camera_id,
            frame_number=self.calls,
            sequence_id="WRONG" if self.wrong_seq else None,
            pattern_id=999 if self.wrong_pat else None,
        )


def _seq(w: int = 8, h: int = 6) -> CalibrationSequence:
    PatternEngine.clear_cache()
    return PatternEngine().generate(w, h)


@pytest.mark.asyncio
async def test_pairs_pattern_n_with_frame_n() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=0)
    )
    frames = await sess.capture_sequence(seq)
    assert len(frames) == len(seq.patterns)
    for pat, cf in zip(seq.patterns, frames, strict=True):
        assert cf.capture.sequence_id == seq.sequence_id
        assert cf.capture.pattern_id == pat.pattern_id
        assert cf.capture.presentation_timestamp_ns is not None
        assert cf.capture.capture_latency_ms is not None


@pytest.mark.asyncio
async def test_wrong_sequence_detected() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource(wrong_seq=True)
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=0)
    )
    with pytest.raises(ProjectorCalibrationError, match="sequence_id mismatch"):
        await sess.capture_sequence(seq)


@pytest.mark.asyncio
async def test_wrong_pattern_detected() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource(wrong_pat=True)
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=0)
    )
    with pytest.raises(ProjectorCalibrationError, match="pattern_id mismatch"):
        await sess.capture_sequence(seq)


@pytest.mark.asyncio
async def test_frame_timeout() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource(delay=0.3)
    sess = SynchronizedCaptureSession(
        src,
        "cam-0",
        proj,
        SyncConfig(
            min_settle_ms=0, capture_timeout=0.05, retry_count=0, warmup_frames=0
        ),
    )
    with pytest.raises(ProjectorCalibrationError, match="timed out"):
        await sess.capture_sequence(seq)


@pytest.mark.asyncio
async def test_presentation_timeout() -> None:
    seq = _seq(8, 6)

    class SlowVsync(FakeProjector):
        async def vsync(self) -> int:  # type: ignore[override]
            await asyncio.sleep(0.3)
            return time.monotonic_ns()

    proj = SlowVsync()
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(
        src,
        "cam-0",
        proj,
        SyncConfig(min_settle_ms=0, presentation_timeout=0.05, retry_count=0),
    )
    with pytest.raises(ProjectorCalibrationError, match="Presentation barrier timeout"):
        await sess.capture_sequence(seq)


@pytest.mark.asyncio
async def test_bounded_retry_exhausted() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource(wrong_pat=True)
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=1)
    )
    with pytest.raises(ProjectorCalibrationError):
        await sess.capture_sequence(seq)
    assert sess.metrics.mismatches >= 1


@pytest.mark.asyncio
async def test_retry_succeeds() -> None:
    seq = _seq(8, 6)

    class FlakySource:
        def __init__(self) -> None:
            self.calls = 0

        async def capture_frame(self, camera_id: str) -> Frame:  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 2:  # first pattern capture (call 1 is warmup drain)
                return Frame(
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                    timestamp=time.monotonic(),
                    timestamp_ns=time.monotonic_ns(),
                    camera_id=camera_id,
                    frame_number=1,
                    sequence_id="WRONG",
                    pattern_id=0,
                )
            return Frame(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                timestamp=time.monotonic(),
                timestamp_ns=time.monotonic_ns(),
                camera_id=camera_id,
                frame_number=2,
            )

    proj = FakeProjector()
    src = FlakySource()  # type: ignore[arg-type]
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=1)
    )  # type: ignore[arg-type]
    frames = await sess.capture_sequence(
        seq
    )  # should retry first pattern once and succeed overall? first pattern fails then retry succeeds, but second pattern etc need also succeed
    # Flaky only fails first call, so first pattern retry succeeds, remaining patterns succeed
    assert len(frames) == len(seq.patterns)
    assert sess.metrics.retries >= 1


@pytest.mark.asyncio
async def test_monotonic_timestamps() -> None:
    seq = _seq(16, 12)
    proj = FakeProjector()
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(src, "cam-0", proj, SyncConfig(min_settle_ms=0))
    await sess.capture_sequence(seq)
    pts = sess.metrics.presentation_timestamps_ns
    cts = sess.metrics.capture_timestamps_ns
    assert pts == sorted(pts)
    assert cts == sorted(cts)
    assert len(pts) == len(seq.patterns)


@pytest.mark.asyncio
async def test_latency_calculation() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(src, "cam-0", proj, SyncConfig(min_settle_ms=5))
    frames = await sess.capture_sequence(seq)
    for cf in frames:
        assert cf.capture.capture_latency_ms is not None
        assert cf.capture.capture_latency_ms >= 0.0
        assert cf.capture.presentation_timestamp_ns is not None
        assert cf.capture.timestamp_ns >= cf.capture.presentation_timestamp_ns  # type: ignore[operator]


@pytest.mark.asyncio
async def test_cancellation_during_capture() -> None:
    seq = _seq(8, 6)

    class SlowSource:
        async def capture_frame(self, camera_id: str) -> Frame:  # type: ignore[no-untyped-def]
            await asyncio.sleep(1.0)
            return Frame(
                image=np.zeros((4, 4, 3), dtype=np.uint8),
                timestamp=time.monotonic(),
                timestamp_ns=time.monotonic_ns(),
                camera_id=camera_id,
                frame_number=1,
            )

    proj = FakeProjector()
    src = SlowSource()  # type: ignore[arg-type]
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, capture_timeout=5.0)
    )
    task = asyncio.create_task(sess.capture_sequence(seq))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_projector_failure() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector(fail_on_show=True)
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(src, "cam-0", proj, SyncConfig(min_settle_ms=0))
    with pytest.raises(ProjectorCalibrationError):
        await sess.capture_sequence(seq)
    assert proj.hidden == 1


@pytest.mark.asyncio
async def test_camera_failure() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource(fail=True)
    sess = SynchronizedCaptureSession(src, "cam-0", proj, SyncConfig(min_settle_ms=0))
    with pytest.raises(ProjectorCalibrationError):
        await sess.capture_sequence(seq)


@pytest.mark.asyncio
async def test_metrics_percentiles() -> None:
    m = CaptureMetrics(latencies_ms=[10, 20, 30, 40, 50])
    assert m.p50 == 30
    assert m.p95 is not None
    assert m.p99 is not None


@pytest.mark.asyncio
async def test_warmup_drains_frame_before_sequence() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=0, warmup_frames=1)
    )
    frames = await sess.capture_sequence(seq)
    assert len(frames) == len(seq.patterns)
    # one warmup drain frame plus one capture per pattern
    assert src.calls == len(seq.patterns) + 1


@pytest.mark.asyncio
async def test_warmup_zero_disables_drain() -> None:
    seq = _seq(8, 6)
    proj = FakeProjector()
    src = FakeFrameSource()
    sess = SynchronizedCaptureSession(
        src, "cam-0", proj, SyncConfig(min_settle_ms=0, retry_count=0, warmup_frames=0)
    )
    await sess.capture_sequence(seq)
    assert src.calls == len(seq.patterns)
