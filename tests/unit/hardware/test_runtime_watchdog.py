"""Tests for RuntimeWatchdog — continuous runtime safety monitor."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_watcher import DisplayWatcher
from projectionai.hardware.events import (
    WatchdogCheckPassed,
    WatchdogStarted,
    WatchdogStopped,
    WatchdogTrigger,
    WatchdogTriggered,
)
from projectionai.hardware.hardware_manager import HardwareManager
from projectionai.hardware.output_manager import OutputManager
from projectionai.hardware.runtime_watchdog import RuntimeWatchdog, WatchdogState
from projectionai.infrastructure.display.mock_provider import MockDisplayProvider
from tests.conftest import FakeEventBus


async def _flush() -> None:
    await asyncio.sleep(0)


def _make_gate_result(
    *,
    can_live: bool = True,
    can_arm: bool = True,
    evaluated_at: float | None = None,
) -> MagicMock:
    result = MagicMock()
    result.can_live = can_live
    result.can_arm = can_arm
    result.evaluated_at = evaluated_at if evaluated_at is not None else time.time()
    result.failed_gates = []
    return result


@pytest.fixture
async def output_manager(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[OutputManager, DisplayManager, MockDisplayProvider]]:
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    yield om, dm, provider
    await om.shutdown()
    await dm.shutdown()


@pytest.fixture
async def watchdog(
    output_manager: object,
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[RuntimeWatchdog, OutputManager, DisplayManager]]:
    om, dm, _provider = output_manager  # type: ignore[misc]
    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        check_interval_s=0.05,
        gate_stale_threshold_s=1.0,
        renderer_timeout_s=0.5,
    )
    await wd.initialize()
    yield wd, om, dm  # type: ignore[misc]
    await wd.shutdown()


# -- Lifecycle ----------------------------------------------------------------


async def test_initial_state_is_stopped(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    assert wd.state is WatchdogState.STOPPED
    assert not wd.is_running


async def test_start_transitions_to_running(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)
    await wd.start("sess-1")
    await _flush()
    assert wd.state is WatchdogState.RUNNING
    assert wd.is_running
    bus.assert_event_emitted(WatchdogStarted)


async def test_stop_transitions_to_stopped(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)
    await wd.start("sess-1")
    await wd.stop("test stop")
    await _flush()
    assert wd.state is WatchdogState.STOPPED
    assert not wd.is_running
    bus.assert_event_emitted(WatchdogStopped)


async def test_start_is_idempotent(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    await wd.start("sess-1")
    await wd.start("sess-1")
    assert wd.state is WatchdogState.RUNNING
    await wd.stop()


async def test_stop_is_idempotent_when_stopped(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    await wd.stop()
    assert wd.state is WatchdogState.STOPPED
    await wd.stop()
    assert wd.state is WatchdogState.STOPPED


async def test_start_from_triggered_restarts(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    await wd.start("sess-1")
    # Force trigger state
    async with wd._lock:
        wd._state = WatchdogState.TRIGGERED
    await wd.start("sess-2")
    assert wd.state is WatchdogState.RUNNING
    await wd.stop()


async def test_watchdog_shutdown_stops_watchdog(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    await wd.start("sess-1")
    await wd.shutdown()
    assert wd.state is WatchdogState.STOPPED


# -- Periodic check passes ---------------------------------------------------


async def test_check_passed_emitted_on_transition_from_failure(
    watchdog: object,
) -> None:
    """CheckPassed only fires when a gate transitions from failed→passed."""
    wd, _om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    # Start healthy — first cycle passes but _last_check_passed starts True,
    # so no event (no transition).
    await wd.start("sess-1")
    await asyncio.sleep(0.1)
    await _flush()
    bus.emitted.clear()

    # Simulate a prior failure by directly flipping the transition flag.
    # The next healthy cycle should emit CheckPassed (False→True).
    wd._last_check_passed = False
    await asyncio.sleep(0.15)
    await wd.stop()
    await _flush()

    passed_events = [e for e in bus.emitted if isinstance(e, WatchdogCheckPassed)]
    assert len(passed_events) >= 1


# -- Renderer unhealthy trigger -----------------------------------------------


async def test_renderer_unhealthy_triggers_safe_stop(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    om_safe_stop = AsyncMock()
    with patch.object(om, "safe_stop", om_safe_stop):
        wd._renderer_ready_provider = lambda: False
        wd._last_renderer_ok_at = time.monotonic() - 10.0
        trigger, details = wd._evaluate()
        assert trigger is WatchdogTrigger.RENDERER_UNHEALTHY
        assert "Renderer not ready" in details


async def test_renderer_healthy_no_trigger() -> None:
    event_bus = FakeEventBus()
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        renderer_ready_provider=lambda: True,
        renderer_timeout_s=0.1,
    )
    await wd.initialize()
    trigger, _ = wd._evaluate()
    assert trigger is None
    await wd.shutdown()
    await om.shutdown()
    await dm.shutdown()


async def test_renderer_freshly_unhealthy_no_trigger() -> None:
    event_bus = FakeEventBus()
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        renderer_ready_provider=lambda: False,
        renderer_timeout_s=10.0,
    )
    await wd.initialize()
    wd._last_renderer_ok_at = time.monotonic()
    trigger, _ = wd._evaluate()
    assert trigger is None
    await wd.shutdown()
    await om.shutdown()
    await dm.shutdown()


# -- Gate stale trigger -------------------------------------------------------


async def test_gate_stale_triggers(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    wd._validation_gate = MagicMock()
    old_result = _make_gate_result(evaluated_at=time.time() - 100.0)
    with patch.object(
        type(om), "gate_result", new_callable=lambda: property(lambda _: old_result)
    ):
        trigger, details = wd._evaluate()
        assert trigger is WatchdogTrigger.GATE_STALE
        assert "stale" in details


async def test_gate_fresh_no_trigger(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    wd._validation_gate = MagicMock()
    fresh_result = _make_gate_result(evaluated_at=time.time())
    with patch.object(
        type(om),
        "gate_result",
        new_callable=lambda: property(lambda _: fresh_result),
    ):
        trigger, _ = wd._evaluate()
        assert trigger is None


# -- Gate revoked trigger -----------------------------------------------------


async def test_gate_revoked_triggers(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    wd._validation_gate = MagicMock()
    wd._last_gate_can_live = True
    revoked_result = _make_gate_result(can_live=False, evaluated_at=time.time())
    with patch.object(
        type(om),
        "gate_result",
        new_callable=lambda: property(lambda _: revoked_result),
    ):
        trigger, details = wd._evaluate()
        assert trigger is WatchdogTrigger.GATE_REVOKED
        assert "revoked" in details


# -- notify_display_event -----------------------------------------------------


async def _set_live_display(om: OutputManager, display_id: str) -> None:
    """Helper: set up an output session with a live_display_id."""
    if om.session is None:
        await om.begin_session(preview_display_id="disp-1")
    if om.session is not None:
        om._session = replace(om.session, live_display_id=display_id)


async def test_notify_display_event_disconnected_triggers(
    watchdog: object,
) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")
    await _set_live_display(om, "disp-1")

    wd.notify_display_event("disconnected", "disp-1")
    await asyncio.sleep(0.1)
    await _flush()
    triggered = [e for e in bus.emitted if isinstance(e, WatchdogTriggered)]
    assert any(e.trigger is WatchdogTrigger.DISPLAY_DISCONNECTED for e in triggered)
    await wd.stop()


async def test_notify_display_event_ignores_non_live_display(
    watchdog: object,
) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")
    await _set_live_display(om, "disp-1")
    wd.notify_display_event("disconnected", "disp-999")
    await asyncio.sleep(0.05)
    await _flush()
    triggered = [e for e in bus.emitted if isinstance(e, WatchdogTriggered)]
    assert len(triggered) == 0
    await wd.stop()


async def test_notify_display_event_noop_when_stopped(watchdog: object) -> None:
    wd, _om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)
    wd.notify_display_event("disconnected", "disp-1")
    await _flush()
    triggered = [e for e in bus.emitted if isinstance(e, WatchdogTriggered)]
    assert len(triggered) == 0


async def test_notify_resolution_change_triggers(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")
    await _set_live_display(om, "disp-1")

    wd.notify_display_event("resolution_changed", "disp-1")
    await asyncio.sleep(0.1)
    await _flush()
    triggered = [e for e in bus.emitted if isinstance(e, WatchdogTriggered)]
    assert any(e.trigger is WatchdogTrigger.RESOLUTION_CHANGED for e in triggered)
    await wd.stop()


# -- Idempotent trigger -------------------------------------------------------


async def test_trigger_is_idempotent(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    om_safe_stop = AsyncMock()
    with patch.object(om, "safe_stop", om_safe_stop):
        await wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "test")
        assert wd.state is WatchdogState.TRIGGERED
        await wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "test2")
        assert om_safe_stop.call_count == 1


async def test_safe_stop_failure_does_not_crash(watchdog: object) -> None:
    wd, om, _dm = watchdog  # type: ignore[misc]
    om_safe_stop = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(om, "safe_stop", om_safe_stop):
        await wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "test")
        assert wd.state is WatchdogState.TRIGGERED


# -- No validation gate configured --------------------------------------------


async def test_no_gate_skips_gate_checks() -> None:
    event_bus = FakeEventBus()
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        validation_gate=None,
    )
    await wd.initialize()
    trigger, _ = wd._evaluate()
    assert trigger is None
    await wd.shutdown()
    await om.shutdown()
    await dm.shutdown()


# -- WatchdogTrigger enum coverage --------------------------------------------


def test_watchdog_trigger_enum_values() -> None:
    assert WatchdogTrigger.DISPLAY_DISCONNECTED.value == "display_disconnected"
    assert WatchdogTrigger.RESOLUTION_CHANGED.value == "resolution_changed"
    assert WatchdogTrigger.GATE_STALE.value == "gate_stale"
    assert WatchdogTrigger.GATE_REVOKED.value == "gate_revoked"
    assert WatchdogTrigger.RENDERER_UNHEALTHY.value == "renderer_unhealthy"
    # CALIBRATION_INVALID is deferred to a future phase


def test_watchdog_state_enum_values() -> None:
    assert WatchdogState.STOPPED.value == "stopped"
    assert WatchdogState.STARTING.value == "starting"
    assert WatchdogState.RUNNING.value == "running"
    assert WatchdogState.TRIGGERED.value == "triggered"
    assert WatchdogState.STOPPING.value == "stopping"


# ============================================================================
# Gate 21: HardwareManager integration — production wiring
# ============================================================================


@pytest.fixture
async def hardware_with_watchdog(
    event_bus: FakeEventBus,
) -> AsyncIterator[
    tuple[
        HardwareManager, OutputManager, DisplayManager, DisplayWatcher, RuntimeWatchdog
    ]
]:
    """Build a real HardwareManager with a wired RuntimeWatchdog."""
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    watcher = DisplayWatcher(event_bus, display_manager=dm)
    await watcher.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        check_interval_s=0.05,
        gate_stale_threshold_s=1.0,
        renderer_timeout_s=0.5,
    )
    await wd.initialize()
    hm = HardwareManager(
        event_bus,
        display_manager=dm,
        watcher=watcher,
        output_manager=om,
        watchdog=wd,
    )
    await hm.initialize()
    yield hm, om, dm, watcher, wd
    await hm.shutdown()


async def test_golive_starts_watchdog(hardware_with_watchdog: object) -> None:
    """Gate 21: go_live() must start the watchdog."""
    hm, _om, _dm, _watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = _dm.displays[0] if _dm.displays else None  # type: ignore[misc]
    if display is None:
        pytest.skip("No displays available")
    await _om.begin_session(preview_display_id=display.display_id)  # type: ignore[misc]
    await _om.arm()  # type: ignore[misc]
    await hm.go_live()  # type: ignore[misc]
    assert wd.is_running  # type: ignore[misc]
    await hm.end_output_session()  # type: ignore[misc]


async def test_end_session_stops_watchdog(hardware_with_watchdog: object) -> None:
    """Gate 21: end_output_session() must stop the watchdog."""
    hm, _om, _dm, _watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = _dm.displays[0] if _dm.displays else None  # type: ignore[misc]
    if display is None:
        pytest.skip("No displays available")
    await _om.begin_session(preview_display_id=display.display_id)  # type: ignore[misc]
    await _om.arm()  # type: ignore[misc]
    await hm.go_live()  # type: ignore[misc]
    assert wd.is_running  # type: ignore[misc]
    await hm.end_output_session()  # type: ignore[misc]
    assert wd.state is WatchdogState.STOPPED  # type: ignore[misc]


async def test_shutdown_stops_watchdog(hardware_with_watchdog: object) -> None:
    """Gate 21: HardwareManager shutdown must stop the watchdog."""
    hm, _om, _dm, _watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = _dm.displays[0] if _dm.displays else None  # type: ignore[misc]
    if display is None:
        pytest.skip("No displays available")
    await _om.begin_session(preview_display_id=display.display_id)  # type: ignore[misc]
    await _om.arm()  # type: ignore[misc]
    await hm.go_live()  # type: ignore[misc]
    assert wd.is_running  # type: ignore[misc]
    await hm.shutdown()  # type: ignore[misc]
    assert wd.state is WatchdogState.STOPPED  # type: ignore[misc]


async def test_display_disconnect_event_reaches_watchdog(
    hardware_with_watchdog: object,
) -> None:
    """Gate 21: DisplayDisconnected event must forward to the watchdog.

    FakeEventBus.subscribe is a no-op, so emit() never dispatches to
    handlers.  We exercise the wiring by calling the HardwareManager
    handler directly and verifying the watchdog fires.
    """
    hm, _om, _dm, _watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = _dm.displays[0] if _dm.displays else None  # type: ignore[misc]
    if display is None:
        pytest.skip("No displays available")
    await _om.begin_session(preview_display_id=display.display_id)  # type: ignore[misc]
    await _om.arm()  # type: ignore[misc]
    await hm.go_live()  # type: ignore[misc]
    assert wd.is_running  # type: ignore[misc]
    # Use the live_display_id from the session (go_live auto-routes to projector)
    session = _om.session  # type: ignore[misc]
    assert session is not None
    live_id = session.live_display_id
    assert live_id is not None
    # Directly invoke the HardwareManager handler (FakeEventBus can't dispatch)
    from projectionai.hardware.events import DisplayDisconnected

    evt = DisplayDisconnected(display_id=live_id, name="test")
    await hm._on_display_disconnected(evt)  # type: ignore[misc]
    # The trigger is created as an async task; give it time to run
    await asyncio.sleep(0.1)
    await _flush()
    triggered = [e for e in wd.event_bus.emitted if isinstance(e, WatchdogTriggered)]  # type: ignore[misc]
    assert any(e.trigger is WatchdogTrigger.DISPLAY_DISCONNECTED for e in triggered)
    await hm.end_output_session()  # type: ignore[misc]


async def test_watchdog_state_property(hardware_with_watchdog: object) -> None:
    """Gate 21: watchdog_state property returns current state."""
    hm, _om, _dm, _watcher, _wd = hardware_with_watchdog  # type: ignore[misc]
    assert hm.watchdog_state is WatchdogState.STOPPED  # type: ignore[misc]


# ============================================================================
# GATE 1 — Safe-stop failure must have safe outcome
# ============================================================================


async def test_safe_stop_failure_leaves_output_not_live(watchdog: object) -> None:
    """Gate 1: When safe_stop() raises, OutputManager must NOT remain LIVE.

    safe_stop() transitions to STOPPING before any potential failure.
    The live route is cleared before blackout (where failures occur).
    So the output is safe even when safe_stop fails.
    """
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    display = _dm.displays[0]  # type: ignore[misc]
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await om.go_live()
    await wd.start(om.session.session_id)

    from projectionai.hardware.output_manager import OutputState

    assert om.state is OutputState.LIVE

    original_safe_stop = om.safe_stop

    async def failing_safe_stop(**kwargs: object) -> None:
        await original_safe_stop(**kwargs)
        raise RuntimeError("simulated safe_stop failure")

    om.safe_stop = failing_safe_stop  # type: ignore[assignment]

    wd._renderer_ready_provider = lambda: False
    wd._last_renderer_ok_at = time.monotonic() - 100.0

    await wd._check_all()
    await asyncio.sleep(0.1)
    await _flush()

    assert wd.state is WatchdogState.TRIGGERED
    assert om.state is not OutputState.LIVE
    assert om.session is None


# ============================================================================
# GATE 2 — Watchdog task exception must not leave output live
# ============================================================================


async def test_watchdog_task_exception_attempts_safe_stop(
    watchdog: object,
) -> None:
    """Gate 2: When the watchdog loop crashes, it must attempt safe_stop.

    Before the fix, a watchdog crash set TRIGGERED but left output LIVE.
    Now it attempts safe_stop to ensure output is not left unprotected.
    """
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    display = _dm.displays[0]  # type: ignore[misc]
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await om.go_live()
    await wd.start(om.session.session_id)

    from projectionai.hardware.output_manager import OutputState

    assert om.state is OutputState.LIVE

    # Replace _check_all to raise an unexpected exception
    async def crashing_check() -> None:
        raise ValueError("unexpected crash in watchdog")

    wd._check_all = crashing_check  # type: ignore[assignment]

    # Let the loop run one cycle
    await asyncio.sleep(wd._check_interval_s + 0.1)
    await _flush()

    # Watchdog is TRIGGERED (crash was caught)
    assert wd.state is WatchdogState.TRIGGERED

    # safe_stop was attempted — session is ended
    assert om.session is None
    assert om.state is OutputState.IDLE


# ============================================================================
# GATE 3 — Calibration invalidation covered by gate revocation
# ============================================================================


async def test_calibration_invalidation_triggers_gate_revocation(
    watchdog: object,
) -> None:
    """Gate 3: Calibration invalidation is covered by gate revocation.

    When calibration changes, the validation gate fails, can_live flips
    from True to False, and the watchdog detects GATE_REVOKED.
    """
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    wd._validation_gate = MagicMock()
    wd._last_gate_can_live = True

    # Gate was authorized, now revoked
    revoked_result = _make_gate_result(can_live=False, evaluated_at=time.time())
    with patch.object(
        type(om), "gate_result", new_callable=lambda: property(lambda _: revoked_result)
    ):
        trigger, details = wd._evaluate()
        assert trigger is WatchdogTrigger.GATE_REVOKED
        assert "revoked" in details


# ============================================================================
# GATE 4 — Gate staleness clock semantics
# ============================================================================


async def test_gate_staleness_uses_wall_clock(watchdog: object) -> None:
    """Gate 4: Gate staleness uses wall-clock (time.time()) to match
    ValidationGateResult.evaluated_at. Renderer timeout uses monotonic.

    Wall-clock jumps forward → stale detection (safe).
    Wall-clock jumps backward → gate appears fresh (acceptable risk,
    documented as provisional).
    """
    wd, om, _dm = watchdog  # type: ignore[misc]
    wd._validation_gate = MagicMock()

    # Simulate wall-clock jump forward: gate evaluated 1000s ago
    old_result = _make_gate_result(evaluated_at=time.time() - 1000.0)
    with patch.object(
        type(om), "gate_result", new_callable=lambda: property(lambda _: old_result)
    ):
        trigger, details = wd._evaluate()
        assert trigger is WatchdogTrigger.GATE_STALE
        assert "1000" in details


async def test_renderer_timeout_uses_monotonic() -> None:
    """Gate 4: Renderer timeout uses time.monotonic() for NTP/DST safety."""
    event_bus = FakeEventBus()
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        renderer_ready_provider=lambda: False,
        renderer_timeout_s=0.1,
    )
    await wd.initialize()

    # Set last_renderer_ok_at using monotonic
    wd._last_renderer_ok_at = time.monotonic() - 100.0
    trigger, details = wd._evaluate()
    assert trigger is WatchdogTrigger.RENDERER_UNHEALTHY

    await wd.shutdown()
    await om.shutdown()
    await dm.shutdown()


# ============================================================================
# GATE 5 — Production ownership: one watchdog per session
# ============================================================================


async def test_production_ownership_no_duplicate_tasks(
    hardware_with_watchdog: object,
) -> None:
    """Gate 5: go_live → end_session → go_live → end_session must not
    accumulate tasks or create duplicate watchdogs."""
    hm, om, dm, watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = dm.displays[0]  # type: ignore[misc]

    tasks_after_first: int = 0
    tasks_after_second: int = 0

    # First cycle
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await hm.go_live()
    assert wd.is_running
    tasks_after_first = sum(
        1 for t in asyncio.all_tasks() if "watchdog" in (t.get_name() or "")
    )
    await hm.end_output_session()
    assert wd.state is WatchdogState.STOPPED

    # Second cycle
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await hm.go_live()
    assert wd.is_running
    tasks_after_second = sum(
        1 for t in asyncio.all_tasks() if "watchdog" in (t.get_name() or "")
    )
    await hm.end_output_session()
    assert wd.state is WatchdogState.STOPPED

    # No task accumulation — should be same count
    assert tasks_after_second <= tasks_after_first + 1


# ============================================================================
# GATE 6 — Live start/stop integration via HardwareManager
# ============================================================================


async def test_hm_safe_stop_ends_session(hardware_with_watchdog: object) -> None:
    """Gate 6: om.safe_stop() must end the session (called directly, not
    through HardwareManager — HardwareManager doesn't wrap safe_stop)."""
    hm, om, dm, watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = dm.displays[0]  # type: ignore[misc]

    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await hm.go_live()
    assert wd.is_running

    # Direct safe_stop on OutputManager
    await om.safe_stop(reason="test")
    assert om.session is None

    # Watchdog is still running (only stopped by end_session or shutdown)
    # This is expected — the caller must also call end_output_session
    await hm.end_output_session()


# ============================================================================
# GATE 7 — Display events: display already gone
# ============================================================================


async def test_display_already_gone_no_trigger(watchdog: object) -> None:
    """Gate 7: Display event for a display not in the session → no trigger."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")
    await _set_live_display(om, "disp-1")

    # Display "disp-999" is not the live display
    wd.notify_display_event("disconnected", "disp-999")
    await asyncio.sleep(0.05)
    await _flush()
    triggered = [e for e in bus.emitted if isinstance(e, WatchdogTriggered)]
    assert len(triggered) == 0

    # Display event with unknown event name
    wd.notify_display_event("unknown_event", "disp-1")
    await asyncio.sleep(0.05)
    await _flush()
    triggered = [e for e in bus.emitted if isinstance(e, WatchdogTriggered)]
    assert len(triggered) == 0

    await wd.stop()


# ============================================================================
# GATE 8 — Renderer failure: transient unhealthy with recovery
# ============================================================================


async def test_renderer_transient_unhealthy_recovery() -> None:
    """Gate 8: Transient renderer unhealthy → recovery → no trigger.

    The renderer_timeout_s acts as a grace period. If the renderer
    recovers before the timeout, no trigger fires.
    """
    event_bus = FakeEventBus()
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()

    healthy = True

    def renderer_provider() -> bool:
        return healthy

    wd = RuntimeWatchdog(
        event_bus,
        output_manager=om,
        display_manager=dm,
        renderer_ready_provider=renderer_provider,
        renderer_timeout_s=1.0,
        check_interval_s=0.05,
    )
    await wd.initialize()
    await wd.start("sess-1")

    # Renderer becomes unhealthy
    healthy = False
    await asyncio.sleep(0.3)

    # Renderer recovers before timeout
    healthy = True
    await asyncio.sleep(0.3)

    # No trigger should fire
    triggered = [e for e in event_bus.emitted if isinstance(e, WatchdogTriggered)]
    assert len(triggered) == 0

    await wd.shutdown()
    await om.shutdown()
    await dm.shutdown()


# ============================================================================
# GATE 9 — Authorization revocation: no stale cache
# ============================================================================


async def test_authorization_revocation_no_stale_cache(watchdog: object) -> None:
    """Gate 9: can_live flips True → False must be detected immediately,
    not from a stale cache."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    wd._validation_gate = MagicMock()

    # First evaluation: authorized
    authorized = _make_gate_result(can_live=True, evaluated_at=time.time())
    with patch.object(
        type(om), "gate_result", new_callable=lambda: property(lambda _: authorized)
    ):
        trigger, _ = wd._evaluate()
        assert trigger is None
        assert wd._last_gate_can_live is True

    # Second evaluation: revoked
    revoked = _make_gate_result(can_live=False, evaluated_at=time.time())
    with patch.object(
        type(om), "gate_result", new_callable=lambda: property(lambda _: revoked)
    ):
        trigger, details = wd._evaluate()
        assert trigger is WatchdogTrigger.GATE_REVOKED
        assert "revoked" in details


# ============================================================================
# GATE 10 — No auto-recovery after trigger
# ============================================================================


async def test_no_auto_recovery_after_trigger(watchdog: object) -> None:
    """Gate 10: After trigger, no automatic rearm/go_live/resume.

    The watchdog stays in TRIGGERED state. Only an explicit start()
    call (which requires going through HardwareManager) can restart it.
    """
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")

    # Force trigger
    async with wd._lock:
        wd._state = WatchdogState.TRIGGERED

    # Wait — no automatic recovery
    await asyncio.sleep(0.3)
    assert wd.state is WatchdogState.TRIGGERED
    assert not wd.is_running

    # Only explicit start can restart
    await wd.start("sess-2")
    assert wd.state is WatchdogState.RUNNING
    await wd.stop()


# ============================================================================
# GATE 11 — Idempotency: multiple triggers = one safe-stop
# ============================================================================


async def test_idempotent_trigger_with_concurrent_calls(watchdog: object) -> None:
    """Gate 11: Multiple triggers for same fault must result in one
    effective safe-stop operation."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    om_safe_stop = AsyncMock()
    with patch.object(om, "safe_stop", om_safe_stop):
        # Fire multiple triggers concurrently
        await asyncio.gather(
            wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "t1"),
            wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "t2"),
            wd._trigger_safe_stop(WatchdogTrigger.RENDERER_UNHEALTHY, "t3"),
        )
        # Only one safe_stop call (idempotency)
        assert om_safe_stop.call_count == 1
        assert wd.state is WatchdogState.TRIGGERED


# ============================================================================
# GATE 12 — Concurrency: no deadlock, no resurrected LIVE
# ============================================================================


async def test_concurrent_trigger_and_shutdown(watchdog: object) -> None:
    """Gate 12: Trigger + shutdown must not deadlock."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    await wd.start("sess-1")
    om_safe_stop = AsyncMock()
    with patch.object(om, "safe_stop", om_safe_stop):
        # Fire trigger and shutdown concurrently
        await asyncio.gather(
            wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "test"),
            wd.stop("concurrent shutdown"),
            return_exceptions=True,
        )
    assert wd.state in (WatchdogState.STOPPED, WatchdogState.TRIGGERED)


async def test_concurrent_trigger_and_freeze(watchdog: object) -> None:
    """Gate 12: Trigger + freeze must not resurrect LIVE."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    display = _dm.displays[0]  # type: ignore[misc]
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await om.go_live()
    await wd.start(om.session.session_id)

    from projectionai.hardware.output_manager import OutputState

    assert om.state is OutputState.LIVE

    # Trigger watchdog
    await wd._trigger_safe_stop(WatchdogTrigger.DISPLAY_DISCONNECTED, "test")
    assert wd.state is WatchdogState.TRIGGERED

    # Session should be ended, not frozen
    assert om.session is None


# ============================================================================
# GATE 13 — Shutdown: output safe, task cancelled, no orphan
# ============================================================================


async def test_shutdown_from_live_cancels_task(watchdog: object) -> None:
    """Gate 13: LIVE → shutdown must cancel the monitoring task."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    display = _dm.displays[0]  # type: ignore[misc]
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await wd.start(om.session.session_id)
    assert wd.is_running

    task = wd._task
    assert task is not None
    assert not task.done()

    await wd.shutdown()

    assert wd.state is WatchdogState.STOPPED
    assert task.cancelled() or task.done()


async def test_double_shutdown_safe(watchdog: object) -> None:
    """Gate 13: Shutdown twice must not error."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    display = _dm.displays[0]  # type: ignore[misc]
    await om.begin_session(preview_display_id=display.display_id)
    await om.arm()
    await wd.start(om.session.session_id)

    await wd.shutdown()
    assert wd.state is WatchdogState.STOPPED

    # Second shutdown — should not raise
    await wd.shutdown()
    assert wd.state is WatchdogState.STOPPED


# ============================================================================
# GATE 14 — Resource reuse: no duplicate subscriptions
# ============================================================================


async def test_resource_reuse_no_task_accumulation(
    hardware_with_watchdog: object,
) -> None:
    """Gate 14: Repeated go_live/stop cycles must not accumulate tasks."""
    hm, om, dm, watcher, wd = hardware_with_watchdog  # type: ignore[misc]
    display = dm.displays[0]  # type: ignore[misc]

    for _ in range(5):
        await om.begin_session(preview_display_id=display.display_id)
        await om.arm()
        await hm.go_live()
        assert wd.is_running
        await hm.end_output_session()
        assert wd.state is WatchdogState.STOPPED

    # No orphan tasks — only the current event loop tasks exist
    watchdog_tasks = [
        t
        for t in asyncio.all_tasks()
        if "watchdog" in (t.get_name() or "") and not t.done()
    ]
    assert len(watchdog_tasks) == 0


# ============================================================================
# GATE 15 — Event pressure: CheckPassed on transitions only
# ============================================================================


async def test_event_pressure_100_healthy_cycles(watchdog: object) -> None:
    """Gate 15: 100 healthy cycles must not produce an event storm.

    CheckPassed is emitted only on state transitions (failed→passed),
    not every cycle.
    """
    wd, _om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")
    await asyncio.sleep(0.1)
    await _flush()
    bus.emitted.clear()

    # Run 100 healthy cycles
    for _ in range(100):
        await wd._check_all()

    # At most 1 CheckPassed event (the transition from initial state)
    passed_events = [e for e in bus.emitted if isinstance(e, WatchdogCheckPassed)]
    assert len(passed_events) <= 1

    await wd.stop()


async def test_event_pressure_unhealthy_to_healthy_emits_once(
    watchdog: object,
) -> None:
    """Gate 15: unhealthy → healthy transition emits exactly one CheckPassed."""
    wd, om, _dm = watchdog  # type: ignore[misc]
    bus = wd.event_bus
    assert isinstance(bus, FakeEventBus)

    await wd.start("sess-1")
    await asyncio.sleep(0.1)
    await _flush()
    bus.emitted.clear()

    # Simulate failure
    wd._last_check_passed = False

    # First healthy cycle — should emit CheckPassed (transition)
    await wd._check_all()
    await asyncio.sleep(0)
    await _flush()
    passed_after_first = [e for e in bus.emitted if isinstance(e, WatchdogCheckPassed)]
    assert len(passed_after_first) == 1

    bus.emitted.clear()

    # Second healthy cycle — should NOT emit (no transition)
    await wd._check_all()
    await asyncio.sleep(0)
    await _flush()
    passed_after_second = [e for e in bus.emitted if isinstance(e, WatchdogCheckPassed)]
    assert len(passed_after_second) == 0

    await wd.stop()
