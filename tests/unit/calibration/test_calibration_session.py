"""Tests for calibration session."""

from __future__ import annotations

import pytest

from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.types import (
    CalibrationData,
    CalibrationMethod,
    CalibrationStatus,
)
from tests.conftest import FakeEventBus


@pytest.fixture
def session() -> CalibrationSession:
    return CalibrationSession()


@pytest.fixture
def session_with_bus() -> tuple[CalibrationSession, FakeEventBus]:
    bus = FakeEventBus()
    s = CalibrationSession(event_bus=bus)
    return s, bus


class TestCalibrationSession:
    async def test_initial_state(self, session: CalibrationSession) -> None:
        assert session.state.status == CalibrationStatus.IDLE
        assert session.result is None
        assert not session.is_active

    async def test_start_transitions_to_preparing(
        self, session: CalibrationSession
    ) -> None:
        await session.start(CalibrationMethod.ARUCO)
        assert session.state.status == CalibrationStatus.PREPARING
        assert session.state.current_method == CalibrationMethod.ARUCO
        assert session.state.started_at > 0
        assert session.is_active

    async def test_start_raises_if_not_idle(self, session: CalibrationSession) -> None:
        await session.start()
        with pytest.raises(RuntimeError, match="Cannot start"):
            await session.start()

    async def test_cancel(self, session: CalibrationSession) -> None:
        await session.start()
        await session.cancel()
        assert session.state.status == CalibrationStatus.CANCELLED

    async def test_cancel_completed_is_noop(self, session: CalibrationSession) -> None:
        await session.start()
        session.state.status = CalibrationStatus.COMPLETED
        await session.cancel()
        assert session.state.status == CalibrationStatus.COMPLETED

    async def test_fail(self, session: CalibrationSession) -> None:
        await session.start()
        await session.fail("Test error")
        assert session.state.status == CalibrationStatus.FAILED
        assert "Test error" in session.state.errors
        assert session.completed_at > 0

    async def test_finalize_success(self, session: CalibrationSession) -> None:
        await session.start()
        session.state.status = CalibrationStatus.COMPLETED
        result = session.finalize()
        assert result.success
        assert result.data is not None
        assert result.quality_score >= 0.0
        assert session.result is result

    async def test_finalize_failure_no_errors(
        self, session: CalibrationSession
    ) -> None:
        await session.start()
        result = session.finalize()
        assert result.success

    async def test_finalize_with_errors(self, session: CalibrationSession) -> None:
        await session.start()
        session.state.errors.append("Calibration failed")
        result = session.finalize()
        assert not result.success

    async def test_update_progress(self, session: CalibrationSession) -> None:
        await session.start()
        session.update_progress(0.5, "Halfway", "processing")
        assert session.state.progress == 0.5
        assert session.state.status_text == "Halfway"
        assert session.state.current_stage == "processing"

    async def test_update_progress_clamps(self, session: CalibrationSession) -> None:
        await session.start()
        session.update_progress(1.5)
        assert session.state.progress == 1.0
        session.update_progress(-0.5)
        assert session.state.progress == 0.0

    async def test_set_and_get_data(self, session: CalibrationSession) -> None:
        session.set_data("confidence", 0.95)
        assert session.get_data("confidence") == 0.95

    async def test_elapsed_time(self, session: CalibrationSession) -> None:
        assert session.elapsed_seconds == 0.0
        await session.start()
        assert session.elapsed_seconds >= 0.0

    async def test_is_active_false_when_idle(self, session: CalibrationSession) -> None:
        assert not session.is_active

    async def test_is_active_true_when_running(
        self, session: CalibrationSession
    ) -> None:
        await session.start()
        assert session.is_active

    async def test_is_active_false_when_done(self, session: CalibrationSession) -> None:
        await session.start()
        session.state.status = CalibrationStatus.COMPLETED
        assert not session.is_active

    async def test_start_emits_event(self, session_with_bus) -> None:
        session, bus = session_with_bus
        await session.start()
        from projectionai.core.events import CalibrationStarted

        bus.assert_event_emitted(CalibrationStarted)

    async def test_fail_emits_event(self, session_with_bus) -> None:
        session, bus = session_with_bus
        await session.start()
        await session.fail("err")
        from projectionai.core.events import CalibrationFailed

        bus.assert_event_emitted(CalibrationFailed)

    async def test_update_progress_emits_event(self, session_with_bus) -> None:
        import asyncio

        session, bus = session_with_bus
        await session.start()
        session.update_progress(0.3, "Working")
        await asyncio.sleep(0)  # let create_task execute
        from projectionai.core.events import CalibrationProgress

        bus.assert_event_emitted(CalibrationProgress)

    async def test_finalize_adds_to_history(self, session: CalibrationSession) -> None:
        await session.start()
        session.finalize()
        assert session.history.count == 1

    async def test_quality_score_zero_on_empty(
        self, session: CalibrationSession
    ) -> None:
        session.state.data = None  # no calibration data yet
        score = session._compute_quality_score()
        assert score == 0.0

    async def test_quality_score_penalised_by_errors(
        self, session: CalibrationSession
    ) -> None:
        session.state.data = CalibrationData(confidence=1.0, num_samples=5)
        clean_score = session._compute_quality_score()
        session.state.warnings.append("Low confidence")
        penalised_score = session._compute_quality_score()
        assert penalised_score < clean_score

    async def test_id_generated(self, session: CalibrationSession) -> None:
        assert len(session.id) > 0

    async def test_name_default(self, session: CalibrationSession) -> None:
        assert session.name == "Calibration Session"
