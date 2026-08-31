"""Tests for the output manager — session lifecycle and safe switching."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import replace as dataclass_replace

import pytest

from projectionai.core.errors import ManagerNotInitializedError
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.errors import (
    DisplayNotFoundError,
    OutputSessionError,
    OutputSwitchError,
)
from projectionai.hardware.events import (
    OutputArmed,
    OutputBlackout,
    OutputFrozen,
    OutputLiveStarted,
    OutputPreviewChanged,
    OutputSessionEnded,
    OutputSessionStarted,
    OutputUnfrozen,
)
from projectionai.hardware.models import DisplayCapabilities
from projectionai.hardware.output_manager import OutputManager, OutputState
from projectionai.infrastructure.display.mock_provider import (
    MockDisplayProvider,
    make_display,
)
from tests.conftest import FakeEventBus


async def _flush() -> None:
    """Yield control so fire-and-forget emit tasks can run."""
    await asyncio.sleep(0)


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until *predicate* returns True or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("Timed out waiting for condition")


@pytest.fixture
async def output_manager(
    event_bus: FakeEventBus,
) -> AsyncIterator[tuple[OutputManager, DisplayManager, MockDisplayProvider]]:
    """Return an initialized OutputManager over the mock topology."""
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    yield om, dm, provider
    await om.shutdown()
    await dm.shutdown()


# -- Session lifecycle ------------------------------------------------------


async def test_begin_session_with_preview_starts_in_preview(
    output_manager: object,
) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    session = await om.begin_session(preview_display_id="disp-1")
    await _flush()
    assert session.state is OutputState.PREVIEW
    assert session.preview_display_id == "disp-1"
    assert om.state is OutputState.PREVIEW
    assert event_bus.assert_event_emitted(OutputSessionStarted) is None
    assert dm.preview_output is not None
    assert dm.preview_output.display_id == "disp-1"


async def test_begin_session_without_preview_starts_idle(
    output_manager: object,
) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    session = await om.begin_session()
    assert session.state is OutputState.IDLE
    assert session.preview_display_id is None
    assert om.state is OutputState.IDLE


async def test_begin_session_while_active_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    with pytest.raises(OutputSessionError):
        await om.begin_session()


async def test_begin_session_unknown_preview_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    with pytest.raises(DisplayNotFoundError):
        await om.begin_session(preview_display_id="ghost")


async def test_end_session_clears_routing(output_manager: object) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session(preview_display_id="disp-1")
    # Set calibration context for gate (LIVE source, no hardware pending)
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.end_session()
    await _flush()
    assert om.session is None
    assert om.state is OutputState.IDLE
    assert dm.live_output is None
    assert dm.preview_output is None
    assert event_bus.assert_event_emitted(OutputSessionEnded) is None


async def test_end_session_without_session_is_noop(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.end_session()
    assert om.session is None


# -- Preview routing -----------------------------------------------------------


async def test_set_preview_changes_target(output_manager: object) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session()
    await om.set_preview("disp-3")
    await _flush()
    assert om.session is not None
    assert om.session.preview_display_id == "disp-3"
    assert event_bus.assert_event_emitted(OutputPreviewChanged) is None
    assert dm.preview_output is not None
    assert dm.preview_output.display_id == "disp-3"


async def test_set_preview_without_session_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    with pytest.raises(OutputSessionError):
        await om.set_preview("disp-1")


# -- Arm / live ---------------------------------------------------------------


async def test_arm_validates_and_arms(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session()
    await om.set_live_target("disp-2")
    report = await om.arm()
    await _flush()
    assert report.is_ok
    assert om.state is OutputState.ARMED
    assert event_bus.assert_event_emitted(OutputArmed) is None


async def test_arm_without_live_target_still_arms(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    report = await om.arm()
    assert report.is_ok
    assert om.state is OutputState.ARMED


async def test_go_live_auto_routes_to_first_projector(
    output_manager: object,
) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session()
    # Set calibration context for gate (LIVE source, no hardware pending)
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    report = await om.go_live()
    await _flush()
    assert report.is_ok
    assert om.state is OutputState.LIVE
    assert om.is_live
    assert dm.live_output is not None
    assert dm.live_output.kind.value == "projector"
    assert event_bus.assert_event_emitted(OutputLiveStarted) is None


async def test_go_live_uses_explicit_target(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.set_live_target("disp-2")
    await om.go_live()
    assert om.session is not None
    assert om.session.live_display_id == "disp-2"


async def test_go_live_rejects_without_projector(event_bus: FakeEventBus) -> None:
    provider = MockDisplayProvider(
        [make_display("mon-1", 0, "Dell U2720Q", manufacturer="Dell")]
    )
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        from projectionai.calibration.validator import (
            ValidationReport as CalValidationReport,
        )

        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        # Arm with require_projector=False since only monitor is present
        await om.arm(require_projector=False)
        with pytest.raises(OutputSwitchError):
            await om.go_live()
        # Safe switching: state remains ARMED after failed go_live
        assert om.state is OutputState.ARMED
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_go_live_allows_monitor_when_require_projector_false(
    event_bus: FakeEventBus,
) -> None:
    """With require_projector=False, a monitor should be accepted as live target."""
    provider = MockDisplayProvider(
        [make_display("mon-1", 0, "Dell U2720Q", manufacturer="Dell")]
    )
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        from projectionai.calibration.validator import (
            ValidationReport as CalValidationReport,
        )

        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        await om.arm(require_projector=False)
        await om.set_live_target("mon-1")
        report = await om.go_live(require_projector=False)
        assert report.is_ok
        assert om.state is OutputState.LIVE
        assert om.session.live_display_id == "mon-1"
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_arm_allows_monitor_when_require_projector_false(
    event_bus: FakeEventBus,
) -> None:
    """With require_projector=False, arm should accept a monitor target."""
    provider = MockDisplayProvider(
        [make_display("mon-1", 0, "Dell U2720Q", manufacturer="Dell")]
    )
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        report = await om.arm(require_projector=False)
        assert report.is_ok
        assert om.state is OutputState.ARMED
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_arm_default_requires_projector(event_bus: FakeEventBus) -> None:
    """Default behavior (require_projector=True) should reject monitor."""
    provider = MockDisplayProvider(
        [make_display("mon-1", 0, "Dell U2720Q", manufacturer="Dell")]
    )
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        report = await om.arm()  # default require_projector=True
        assert not report.is_ok
        # On failed arm, state rolls back to original (IDLE before PREVIEW)
        assert om.state is OutputState.IDLE
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_go_live_default_requires_projector(event_bus: FakeEventBus) -> None:
    """Default behavior (require_projector=True) should reject monitor."""
    provider = MockDisplayProvider(
        [make_display("mon-1", 0, "Dell U2720Q", manufacturer="Dell")]
    )
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        from projectionai.calibration.validator import (
            ValidationReport as CalValidationReport,
        )

        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        await om.arm(require_projector=False)
        with pytest.raises(OutputSwitchError):
            await om.go_live()  # default require_projector=True
        assert om.state is OutputState.ARMED
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_go_live_rejects_when_no_output_window(
    event_bus: FakeEventBus,
) -> None:
    provider = MockDisplayProvider()
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(
        event_bus,
        display_manager=dm,
        window_available_provider=lambda: False,
    )
    await om.initialize()
    try:
        await om.begin_session()
        from projectionai.calibration.validator import (
            ValidationReport as CalValidationReport,
        )

        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        await om.arm()
        with pytest.raises(OutputSwitchError) as exc_info:
            await om.go_live()
        assert not exc_info.value.report.is_ok
        assert any(
            issue.code == "window_not_available"
            for issue in exc_info.value.report.errors
        )
        # Safe switching: state remains ARMED after failed go_live
        assert om.state is OutputState.ARMED
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_go_live_rejects_without_projector_when_monitor_only(
    event_bus: FakeEventBus,
) -> None:
    provider = MockDisplayProvider(
        [make_display("mon-1", 0, "Dell U2720Q", manufacturer="Dell")]
    )
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        from projectionai.calibration.validator import (
            ValidationReport as CalValidationReport,
        )

        cal = CalValidationReport(passed=True, quality_score=0.9)
        om.set_calibration_context(
            calibration_report=cal, hardware_pending=(), source_mode="LIVE"
        )
        await om.arm(require_projector=False)
        with pytest.raises(OutputSwitchError):
            await om.go_live()
        # Safe switching: state remains ARMED after failed go_live
        assert om.state is OutputState.ARMED
    finally:
        await om.shutdown()
        await dm.shutdown()


# -- Blackout ------------------------------------------------------------------


async def test_blackout_cuts_live_but_keeps_session(output_manager: object) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.blackout()
    await _flush()
    assert om.state is OutputState.BLACKOUT
    assert dm.live_output is None
    assert om.session is not None
    assert event_bus.assert_event_emitted(OutputBlackout) is None


# -- Freeze ----------------------------------------------------------------------


async def test_freeze_from_live_holds_route_and_emits(
    output_manager: object,
) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.freeze()
    await _flush()
    assert om.state is OutputState.FREEZE
    assert dm.live_output is not None  # route kept for instant resume
    assert om.session is not None
    assert om.session.live_display_id is not None
    frozen = next(ev for ev in event_bus.emitted if isinstance(ev, OutputFrozen))
    assert frozen.from_state is OutputState.LIVE


async def test_freeze_from_blackout(output_manager: object) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.blackout()
    await om.freeze()
    await _flush()
    assert om.state is OutputState.FREEZE
    assert dm.live_output is None
    frozen = next(ev for ev in om.event_bus.emitted if isinstance(ev, OutputFrozen))
    assert frozen.from_state is OutputState.BLACKOUT


async def test_freeze_requires_session(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    with pytest.raises(OutputSessionError):
        await om.freeze()


async def test_freeze_from_invalid_state_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()  # IDLE
    with pytest.raises(OutputSessionError, match="Cannot freeze"):
        await om.freeze()
    await om.set_live_target("disp-2")
    await om.arm()  # ARMED
    with pytest.raises(OutputSessionError, match="Cannot freeze"):
        await om.freeze()
    assert om.state is OutputState.ARMED  # unchanged


async def test_double_freeze_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.freeze()
    with pytest.raises(OutputSessionError, match="Cannot freeze"):
        await om.freeze()


async def test_unfreeze_restores_live(output_manager: object) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    event_bus = om.event_bus
    assert isinstance(event_bus, FakeEventBus)
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.freeze()
    await om.unfreeze()
    await _flush()
    assert om.state is OutputState.LIVE
    assert om.is_live
    assert dm.live_output is not None
    unfrozen = next(ev for ev in event_bus.emitted if isinstance(ev, OutputUnfrozen))
    assert unfrozen.restored_state is OutputState.LIVE


async def test_unfreeze_reapplies_route_to_recorded_live_display(
    output_manager: object,
) -> None:
    """Unfreeze reconciles the live route with the recorded target."""
    om, dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()  # auto-routes live to the projector ("disp-2")
    await om.freeze()
    # Route drifts while frozen: unfreeze must re-apply the recorded
    # target instead of trusting the current route.
    dm.set_live_output("disp-1")
    await om.unfreeze()
    await _flush()
    assert om.state is OutputState.LIVE
    assert om.session is not None
    assert om.session.live_display_id == "disp-2"
    assert dm.live_output is not None
    assert dm.live_output.display_id == "disp-2"


async def test_set_live_target_while_frozen_raises(output_manager: object) -> None:
    """A frozen session's live target must not change."""
    om, dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()  # recorded live target = "disp-2" (the projector)
    await om.freeze()
    with pytest.raises(OutputSessionError, match="frozen"):
        await om.set_live_target("disp-1")
    # State, recorded target, and route are all untouched.
    assert om.state is OutputState.FREEZE
    assert om.session is not None
    assert om.session.live_display_id == "disp-2"
    assert dm.live_output is not None
    assert dm.live_output.display_id == "disp-2"


async def test_unfreeze_from_blackout_restores_blackout(
    output_manager: object,
) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.blackout()
    await om.freeze()
    await om.unfreeze()
    await _flush()
    assert om.state is OutputState.BLACKOUT
    unfrozen = next(ev for ev in om.event_bus.emitted if isinstance(ev, OutputUnfrozen))
    assert unfrozen.restored_state is OutputState.BLACKOUT


async def test_unfreeze_without_freeze_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    with pytest.raises(OutputSessionError, match="not frozen"):
        await om.unfreeze()
    assert om.state is OutputState.LIVE  # unchanged


async def test_unfreeze_requires_session(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    with pytest.raises(OutputSessionError):
        await om.unfreeze()


async def test_end_session_while_frozen_cleans_up(output_manager: object) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.freeze()
    await om.end_session()
    await _flush()
    assert om.session is None
    assert om.state is OutputState.IDLE
    assert dm.live_output is None
    assert dm.preview_output is None
    with pytest.raises(OutputSessionError):
        await om.unfreeze()  # frozen state fully cleared


# -- Safe switching -------------------------------------------------------------


class FakeWindow:
    """Duck-typed OutputWindow that records geometry/fullscreen calls."""

    def __init__(self) -> None:
        self.geometry: tuple[int, int, int, int] | None = None
        self.fullscreen = False

    def setGeometry(self, x: int, y: int, w: int, h: int) -> None:  # noqa: N802 - Qt protocol name
        self.geometry = (x, y, w, h)

    def showFullScreen(self) -> None:  # noqa: N802 - Qt protocol name
        self.fullscreen = True

    def showNormal(self) -> None:  # noqa: N802 - Qt protocol name
        self.fullscreen = False


async def test_switch_live_to_routes_and_fullscreens_window(
    output_manager: object,
) -> None:
    om, dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    window = FakeWindow()
    report = await om.switch_live_to("disp-2", window)
    await _flush()
    assert report.is_ok
    assert om.state is OutputState.LIVE
    assert window.fullscreen
    assert window.geometry is not None
    assert dm.live_output is not None
    assert dm.live_output.display_id == "disp-2"


async def test_switch_live_to_unknown_display_raises(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    window = FakeWindow()
    with pytest.raises(DisplayNotFoundError):
        await om.switch_live_to("ghost", window)
    assert not window.fullscreen
    assert om.state is OutputState.ARMED


async def test_switch_live_to_rejects_display_without_fullscreen(
    event_bus: FakeEventBus,
) -> None:
    """The hardware facade must not bypass the fullscreen capability gate."""
    projector = make_display("pj-1", 1, "Epson EB-2250U", manufacturer="Epson")
    projector = dataclass_replace(
        projector,
        capabilities=DisplayCapabilities(supports_fullscreen=False),
    )
    provider = MockDisplayProvider([make_display("mon-1", 0, "Dell U2720Q"), projector])
    dm = DisplayManager(event_bus, provider=provider)
    await dm.initialize()
    om = OutputManager(event_bus, display_manager=dm)
    await om.initialize()
    try:
        await om.begin_session()
        with pytest.raises(OutputSessionError, match="does not support fullscreen"):
            await om.switch_live_to("pj-1")
        assert om.state is OutputState.IDLE  # nothing switched
        assert dm.live_output is None
    finally:
        await om.shutdown()
        await dm.shutdown()


async def test_unfreeze_falls_back_to_blackout_when_live_display_gone(
    output_manager: object,
) -> None:
    om, dm, provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    from projectionai.calibration.validator import (
        ValidationReport as CalValidationReport,
    )

    cal = CalValidationReport(passed=True, quality_score=0.9)
    om.set_calibration_context(
        calibration_report=cal, hardware_pending=(), source_mode="LIVE"
    )
    await om.arm()
    await om.go_live()
    await om.freeze()

    # The live display disappears while frozen; the display manager
    # refresh clears the live route.
    provider.disconnect("disp-2")
    await dm.refresh()
    assert dm.live_output is None

    await om.unfreeze()
    await _flush()

    # Unfreeze must not report LIVE for a route that no longer exists.
    assert om.state is OutputState.BLACKOUT
    assert dm.live_output is None
    unfrozen = next(ev for ev in om.event_bus.emitted if isinstance(ev, OutputUnfrozen))
    assert unfrozen.restored_state is OutputState.BLACKOUT


# -- History --------------------------------------------------------------------


async def test_history_records_sessions(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.begin_session()
    await om.end_session()
    await om.begin_session()
    await om.end_session()
    assert len(om.history) == 2
    assert all(s.session_id for s in om.history)


async def test_uninitialized_operations_raise(output_manager: object) -> None:
    om, _dm, _provider = output_manager  # type: ignore[misc]
    await om.shutdown()
    with pytest.raises(ManagerNotInitializedError):
        await om.begin_session()
