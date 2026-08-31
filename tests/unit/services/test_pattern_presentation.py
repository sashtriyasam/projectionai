"""Tests for PatternPresentationSession, PresentationConfig, and QTPatternPresentationTarget.

Phase 7.5 — Pattern Presentation Integration.

Covers:
- PresentationConfig validation (4 tests)
- PatternPresentationState fields (1 test)
- PatternPresentationSession lifecycle (10 tests)
- QTPatternPresentationTarget via QtPatternProjector (3 tests)

Total: 18 tests.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.domain.calibration_session import (
    CalibrationMethod,
    CalibrationPattern,
    CalibrationSequence,
    PatternAxis,
)
from projectionai.services.pattern_presentation import (
    PatternPresentationSession,
    PatternPresentationState,
    PresentationConfig,
    PresentationError,
    PresentationMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeTarget:
    """Fake presentation target for unit tests."""

    def __init__(
        self,
        resolution: tuple[int, int] = (1920, 1080),
        fail_on_show: bool = False,
        fail_on_enter: bool = False,
    ) -> None:
        self._resolution = resolution
        self.enter_called = False
        self.exit_called = False
        self.hidden = 0
        self.shown_patterns: list[int] = []
        self._fail_on_show = fail_on_show
        self._fail_on_enter = fail_on_enter

    async def enter_fullscreen(self) -> None:
        if self._fail_on_enter:
            raise RuntimeError("enter fullscreen failed")
        self.enter_called = True

    async def show_pattern(self, pattern: CalibrationPattern) -> int:
        if self._fail_on_show:
            raise RuntimeError("show pattern failed")
        self.shown_patterns.append(pattern.pattern_id)
        return time.monotonic_ns()

    async def hide(self) -> None:
        self.hidden += 1

    async def exit_fullscreen(self) -> None:
        self.exit_called = True

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution


class FailTarget:
    """Target that fails on every operation."""

    async def enter_fullscreen(self) -> None:
        raise RuntimeError("enter failed")

    async def show_pattern(self, pattern: CalibrationPattern) -> int:
        raise RuntimeError("show failed")

    async def hide(self) -> None:
        raise RuntimeError("hide failed")

    async def exit_fullscreen(self) -> None:
        raise RuntimeError("exit failed")

    @property
    def resolution(self) -> tuple[int, int]:
        return (0, 0)


def _make_sequence(
    width: int = 8,
    height: int = 6,
    count: int = 4,
) -> CalibrationSequence:
    """Create a test CalibrationSequence with *count* patterns."""
    patterns = []
    for i in range(count):
        img = np.zeros((height, width), dtype=np.uint8)
        img[:] = i * 64
        patterns.append(
            CalibrationPattern(
                pattern_id=i,
                sequence_id="test-seq",
                axis=PatternAxis.COLUMN if i < count // 2 else PatternAxis.ROW,
                bit_index=i,
                bit_value=i % 2,
                image=img,
                width=width,
                height=height,
            )
        )
    return CalibrationSequence(
        sequence_id="test-seq",
        method=CalibrationMethod.GRAY_CODE,
        patterns=tuple(patterns),
        width=width,
        height=height,
        bits_x=count // 2,
        bits_y=count - count // 2,
    )


# ---------------------------------------------------------------------------
# PresentationConfig
# ---------------------------------------------------------------------------


class TestPresentationConfig:
    def test_default_config(self) -> None:
        cfg = PresentationConfig()
        assert cfg.mode is PresentationMode.FULL_SEQUENCE
        assert cfg.pattern_index is None
        assert cfg.settle_ms == 20.0
        assert cfg.presentation_timeout == 2.0

    def test_single_pattern_requires_index(self) -> None:
        with pytest.raises(ValueError, match="requires pattern_index"):
            PresentationConfig(mode=PresentationMode.SINGLE_PATTERN)

    def test_negative_pattern_index_raises(self) -> None:
        with pytest.raises(ValueError, match="pattern_index"):
            PresentationConfig(mode=PresentationMode.SINGLE_PATTERN, pattern_index=-1)

    def test_negative_settle_ms_raises(self) -> None:
        with pytest.raises(ValueError, match="settle_ms"):
            PresentationConfig(settle_ms=-1.0)

    def test_zero_timeout_raises(self) -> None:
        with pytest.raises(ValueError, match="presentation_timeout"):
            PresentationConfig(presentation_timeout=0.0)

    def test_valid_single_pattern_config(self) -> None:
        cfg = PresentationConfig(mode=PresentationMode.SINGLE_PATTERN, pattern_index=2)
        assert cfg.mode is PresentationMode.SINGLE_PATTERN
        assert cfg.pattern_index == 2

    def test_valid_black_config(self) -> None:
        cfg = PresentationConfig(mode=PresentationMode.BLACK)
        assert cfg.mode is PresentationMode.BLACK


# ---------------------------------------------------------------------------
# PatternPresentationState
# ---------------------------------------------------------------------------


class TestPatternPresentationState:
    def test_state_fields(self) -> None:
        from projectionai.services.pattern_presentation import TimestampKind

        state = PatternPresentationState(
            pattern_index=2,
            total_patterns=8,
            mode=PresentationMode.FULL_SEQUENCE,
            timestamp_ns=12345,
            timestamp_kind=TimestampKind.BEST_EFFORT,
            is_complete=True,
        )
        assert state.pattern_index == 2
        assert state.total_patterns == 8
        assert state.mode is PresentationMode.FULL_SEQUENCE
        assert state.timestamp_ns == 12345
        assert state.timestamp_kind is TimestampKind.BEST_EFFORT
        assert state.is_complete is True

    def test_initial_state(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        state = session.state
        assert state.pattern_index is None
        assert state.total_patterns == 0
        assert state.is_complete is False
        assert state.timestamp_ns is None
        assert state.timestamp_kind is None


# ---------------------------------------------------------------------------
# PatternPresentationSession
# ---------------------------------------------------------------------------


class TestPatternPresentationSession:
    @pytest.mark.asyncio
    async def test_creates_with_defaults(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        assert session.state.mode is PresentationMode.FULL_SEQUENCE

    @pytest.mark.asyncio
    async def test_start_enters_fullscreen(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        await session.start()
        assert target.enter_called is True

    @pytest.mark.asyncio
    async def test_show_full_sequence(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        seq = _make_sequence(count=4)
        await session.show(seq)
        assert target.shown_patterns == [0, 1, 2, 3]
        state = session.state
        assert state.is_complete is True
        assert state.pattern_index == 3
        assert state.total_patterns == 4
        assert state.timestamp_ns is not None

    @pytest.mark.asyncio
    async def test_show_single_pattern(self) -> None:
        target = FakeTarget()
        cfg = PresentationConfig(mode=PresentationMode.SINGLE_PATTERN, pattern_index=2)
        session = PatternPresentationSession(target, config=cfg)
        seq = _make_sequence(count=4)
        await session.show(seq)
        assert target.shown_patterns == [2]
        assert session.state.pattern_index == 2
        assert session.state.is_complete is True

    @pytest.mark.asyncio
    async def test_show_single_out_of_range_raises(self) -> None:
        target = FakeTarget()
        cfg = PresentationConfig(mode=PresentationMode.SINGLE_PATTERN, pattern_index=10)
        session = PatternPresentationSession(target, config=cfg)
        seq = _make_sequence(count=4)
        with pytest.raises(PresentationError, match="out of range"):
            await session.show(seq)

    @pytest.mark.asyncio
    async def test_hide_blanks_display(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        await session.hide()
        assert target.hidden == 1
        assert session.state.timestamp_ns is not None

    @pytest.mark.asyncio
    async def test_stop_hides_and_exits(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        await session.stop()
        assert target.hidden == 1
        assert target.exit_called is True

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        await session.stop()
        await session.stop()
        # Should not raise — both hide and exit are safe to call twice
        assert target.hidden >= 1
        assert target.exit_called is True

    @pytest.mark.asyncio
    async def test_show_single_directly(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        seq = _make_sequence(count=4)
        await session.show_single(seq.patterns[1])
        assert target.shown_patterns == [1]
        assert session.state.pattern_index == 0
        assert session.state.total_patterns == 1
        assert session.state.is_complete is True

    @pytest.mark.asyncio
    async def test_target_failure_wrapped_in_presentation_error(self) -> None:
        target = FakeTarget(fail_on_show=True)
        session = PatternPresentationSession(target)
        seq = _make_sequence(count=2)
        with pytest.raises(PresentationError, match="Failed to present pattern 0"):
            await session.show(seq)

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        seq = _make_sequence(count=4)

        # Run show in a task so we can cancel it
        task = asyncio.create_task(session.show(seq))
        await asyncio.sleep(0.005)  # let it start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_black_mode(self) -> None:
        target = FakeTarget()
        cfg = PresentationConfig(mode=PresentationMode.BLACK)
        session = PatternPresentationSession(target, config=cfg)
        seq = _make_sequence(count=2)
        await session.show(seq)
        assert target.hidden == 1
        assert target.shown_patterns == []
        assert session.state.is_complete is True

    @pytest.mark.asyncio
    async def test_hide_mode(self) -> None:
        target = FakeTarget()
        cfg = PresentationConfig(mode=PresentationMode.HIDE)
        session = PatternPresentationSession(target, config=cfg)
        seq = _make_sequence(count=2)
        await session.show(seq)
        assert target.hidden == 1
        assert session.state.is_complete is True

    @pytest.mark.asyncio
    async def test_enter_failure_propagates(self) -> None:
        target = FakeTarget(fail_on_enter=True)
        session = PatternPresentationSession(target)
        with pytest.raises(RuntimeError, match="enter fullscreen failed"):
            await session.start()

    @pytest.mark.asyncio
    async def test_state_timestamp_after_show(self) -> None:
        target = FakeTarget()
        session = PatternPresentationSession(target)
        seq = _make_sequence(count=2)
        before = time.monotonic_ns()
        await session.show(seq)
        after = time.monotonic_ns()
        ts = session.state.timestamp_ns
        assert ts is not None
        assert before <= ts <= after

    @pytest.mark.asyncio
    async def test_resolution_from_target(self) -> None:
        target = FakeTarget(resolution=(1280, 720))
        assert target.resolution == (1280, 720)


# ---------------------------------------------------------------------------
# QTPatternPresentationTarget (requires PySide6 offscreen)
# ---------------------------------------------------------------------------


class TestQTPatternPresentationTarget:
    @pytest.fixture()
    def qt_target(self):
        from projectionai.infrastructure.display.qt import (
            QTPatternPresentationTarget,
            QtPatternProjector,
        )

        projector = QtPatternProjector(screen_index=0)
        target = QTPatternPresentationTarget(projector)
        yield target, projector
        projector.close()

    @pytest.mark.asyncio
    async def test_qt_target_shows_pattern(self, qt_target: tuple[Any, Any]) -> None:
        target, projector = qt_target
        w, h = projector.resolution
        img = np.zeros((h, w), dtype=np.uint8)
        pattern = CalibrationPattern(
            pattern_id=0,
            sequence_id="qt-test",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=img,
            width=w,
            height=h,
        )
        ts = await target.show_pattern(pattern)
        assert isinstance(ts, int)
        assert ts > 0

    @pytest.mark.asyncio
    async def test_qt_target_rejects_resolution_mismatch(
        self, qt_target: tuple[Any, Any]
    ) -> None:
        target, _projector = qt_target
        img = np.zeros((100, 100), dtype=np.uint8)
        pattern = CalibrationPattern(
            pattern_id=0,
            sequence_id="qt-test",
            axis=PatternAxis.COLUMN,
            bit_index=0,
            bit_value=0,
            image=img,
            width=100,
            height=100,
        )
        from projectionai.infrastructure.display.qt import DisplayError

        with pytest.raises(DisplayError, match="does not match"):
            await target.show_pattern(pattern)

    @pytest.mark.asyncio
    async def test_qt_target_resolution(self, qt_target: tuple[Any, Any]) -> None:
        target, _projector = qt_target
        res = target.resolution
        assert isinstance(res, tuple)
        assert len(res) == 2
        assert res[0] > 0
        assert res[1] > 0

    @pytest.mark.asyncio
    async def test_qt_target_hide_and_exit(self, qt_target: tuple[Any, Any]) -> None:
        target, _projector = qt_target
        # hide and exit should not raise even if window was never shown
        await target.hide()
        await target.exit_fullscreen()
