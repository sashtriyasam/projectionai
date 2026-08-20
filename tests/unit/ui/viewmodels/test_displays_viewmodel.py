"""Unit tests for DisplaysViewModel output actions and safety gates.

The hardware layer is faked with a minimal in-memory manager; the
output window is a plain object implementing ``OutputSurface``. The
fake event bus records subscriptions so tests can invoke the VM's
event handlers directly (the real bus is async-driven).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from projectionai.hardware.display_validator import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from projectionai.hardware.errors import (
    DisplayNotFoundError,
    OutputSessionError,
    OutputSwitchError,
)
from projectionai.hardware.events import (
    DisplayConnected,
    DisplayDisconnected,
    DisplayLiveOutputChanged,
    DisplayPreviewOutputChanged,
    OutputBlackout,
    OutputFrozen,
    OutputLiveStarted,
    OutputSessionEnded,
    OutputUnfrozen,
)
from projectionai.hardware.hardware_manager import HardwareManager
from projectionai.hardware.models import (
    DisplayCapabilities,
    DisplayInfo,
    DisplayKind,
    HardwareStatus,
)
from projectionai.hardware.output_manager import OutputState
from projectionai.hardware.patterns import PatternKind
from projectionai.ui.viewmodels.displays import DisplaysViewModel


class _FakeEventBus:
    """Records subscriptions; publish awaits async handlers like the real bus."""

    def __init__(self) -> None:
        self._handlers: dict[type[Any], list[Any]] = {}

    def subscribe(self, event_type: type[Any], handler: Any) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: type[Any], handler: Any) -> None:
        handlers = self._handlers.get(event_type)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            result = handler(event)
            if asyncio.iscoroutine(result):
                asyncio.run(result)


class _FakeSession:
    """Minimal stand-in for hardware OutputSession."""

    def __init__(
        self,
        state: OutputState = OutputState.PREVIEW,
        preview_display_id: str | None = None,
        live_display_id: str | None = None,
    ) -> None:
        self.session_id = "s1"
        self.state = state
        self.preview_display_id = preview_display_id
        self.live_display_id = live_display_id


class _FakeWindow:
    """Records all OutputSurface protocol calls."""

    def __init__(self) -> None:
        self.patterns: list[PatternKind] = []
        self.blackouts = 0
        self.freezes = 0
        self.show_normal = 0
        self.hidden = 0
        self.fullscreen = 0
        self.geometry: list[tuple[int, int, int, int]] = []

    def set_pattern(self, pattern: PatternKind) -> None:
        self.patterns.append(pattern)

    def set_blackout(self) -> None:
        self.blackouts += 1

    def set_freeze(self) -> None:
        self.freezes += 1

    def setGeometry(self, x: int, y: int, w: int, h: int) -> None:  # noqa: N802
        self.geometry.append((x, y, w, h))

    def showFullScreen(self) -> None:  # noqa: N802
        self.fullscreen += 1

    def showNormal(self) -> None:  # noqa: N802
        self.show_normal += 1

    def hide(self) -> None:
        self.hidden += 1


class _FakeHardware:
    """Duck-typed HardwareManager facade used by the view model."""

    def __init__(self, displays: tuple[DisplayInfo, ...] = ()) -> None:
        self.event_bus = _FakeEventBus()
        self._displays = displays
        self.session: _FakeSession | None = None
        self.report = ValidationReport()
        self.switch_calls: list[tuple[str, Any]] = []
        self.move_calls: list[tuple[str, Any, bool]] = []
        self.blackout_calls = 0
        self.freeze_calls = 0
        self.unfreeze_calls = 0
        self.unfreeze_restores: OutputState = OutputState.LIVE
        self.refresh_calls = 0
        self.identify_calls: list[str] = []
        self.begin_calls: list[str | None] = []
        self.preview_calls: list[str | None] = []
        self.switch_error: BaseException | None = None

    # -- Topology ------------------------------------------------------------

    @property
    def displays(self) -> tuple[DisplayInfo, ...]:
        return self._displays

    @property
    def projectors(self) -> tuple[DisplayInfo, ...]:
        return tuple(d for d in self._displays if d.kind is DisplayKind.PROJECTOR)

    @property
    def primary(self) -> DisplayInfo | None:
        return next((d for d in self._displays if d.is_primary), None)

    @property
    def display_count(self) -> int:
        return len(self._displays)

    @property
    def projector_count(self) -> int:
        return len(self.projectors)

    def get_display(self, display_id: str) -> DisplayInfo:
        for display in self._displays:
            if display.display_id == display_id:
                return display
        raise DisplayNotFoundError(f"Unknown display {display_id!r}")

    def validate(self) -> ValidationReport:
        return self.report

    def snapshot(self) -> HardwareStatus:
        return HardwareStatus(display_count=len(self._displays))

    # -- Session ---------------------------------------------------------------

    @property
    def output_session(self) -> _FakeSession | None:
        return self.session

    @property
    def output_state(self) -> OutputState:
        return self.session.state if self.session is not None else OutputState.IDLE

    @property
    def is_live(self) -> bool:
        return self.output_state is OutputState.LIVE

    @property
    def live_display_id(self) -> str | None:
        return self.session.live_display_id if self.session is not None else None

    @property
    def preview_display_id(self) -> str | None:
        return self.session.preview_display_id if self.session is not None else None

    async def begin_output_session(self, preview_display_id: str | None = None) -> None:
        self.begin_calls.append(preview_display_id)
        self.session = _FakeSession(
            OutputState.PREVIEW, preview_display_id=preview_display_id
        )

    async def end_output_session(self) -> None:
        self.session = None

    async def set_output_preview(self, display_id: str | None) -> None:
        self.preview_calls.append(display_id)
        if self.session is not None:
            self.session.preview_display_id = display_id

    async def arm_output(self) -> ValidationReport:
        return self.report

    async def go_live(self) -> ValidationReport:
        if self.session is not None:
            self.session.state = OutputState.LIVE
        return self.report

    async def identify_display(self, display_id: str) -> None:
        self.identify_calls.append(display_id)

    async def refresh_displays(self) -> tuple[DisplayInfo, ...]:
        self.refresh_calls += 1
        return self._displays

    # -- Output ----------------------------------------------------------------

    async def switch_live_output(
        self, display_id: str, window: Any
    ) -> ValidationReport:
        self.switch_calls.append((display_id, window))
        if self.switch_error is not None:
            raise self.switch_error
        if not self.report.is_ok:
            raise OutputSwitchError("Switch rejected", self.report)
        if self.session is not None:
            self.session.state = OutputState.LIVE
            self.session.live_display_id = display_id
        return self.report

    def move_window_to(
        self, display_id: str, window: Any, fullscreen: bool = True
    ) -> None:
        self.move_calls.append((display_id, window, fullscreen))

    async def emergency_blackout(self) -> None:
        self.blackout_calls += 1
        if self.session is not None:
            # Mirror the real manager: blackout cuts the session state.
            self.session.state = OutputState.BLACKOUT

    async def freeze_output(self) -> None:
        if self.session is None:
            raise OutputSessionError("No active output session")
        self.freeze_calls += 1
        self.session.state = OutputState.FREEZE

    async def unfreeze_output(self) -> None:
        if self.session is None:
            raise OutputSessionError("No active output session")
        self.unfreeze_calls += 1
        self.session.state = self.unfreeze_restores


def _make_vm(hardware: _FakeHardware) -> DisplaysViewModel:
    """Build the view model over a fake manager (repo cast convention)."""
    return DisplaysViewModel(cast(HardwareManager, hardware))


def _display(
    display_id: str,
    index: int,
    *,
    kind: DisplayKind = DisplayKind.MONITOR,
    is_primary: bool = False,
    supports_fullscreen: bool = True,
) -> DisplayInfo:
    return DisplayInfo(
        display_id=display_id,
        index=index,
        name=f"Display {display_id}",
        kind=kind,
        is_primary=is_primary,
        capabilities=DisplayCapabilities(supports_fullscreen=supports_fullscreen),
    )


def _projector(display_id: str, index: int) -> DisplayInfo:
    return _display(display_id, index, kind=DisplayKind.PROJECTOR)


def _rejecting_report() -> ValidationReport:
    return ValidationReport(
        issues=(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="no_renderer",
                message="Renderer not ready",
            ),
        )
    )


class TestSelectLive:
    async def test_select_live_starts_session_and_switches(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.select_live("p1")

        assert hardware.begin_calls == [None]
        assert hardware.switch_calls == [("p1", window)]
        assert hardware.session is not None
        assert hardware.session.state is OutputState.LIVE
        assert hardware.session.live_display_id == "p1"

    async def test_select_live_keeps_existing_session(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.PREVIEW)
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.select_live("p1")

        assert hardware.begin_calls == []
        assert hardware.switch_calls == [("p1", window)]

    async def test_select_live_unknown_display_raises(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(DisplayNotFoundError):
            await vm.select_live("nope")

        assert hardware.begin_calls == []
        assert hardware.session is None

    async def test_select_live_requires_output_window(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)

        with pytest.raises(OutputSessionError, match="Output window unavailable"):
            await vm.select_live("p1")

        assert hardware.session is None

    async def test_select_live_propagates_switch_rejection(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.report = _rejecting_report()
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSwitchError):
            await vm.select_live("p1")

    async def test_select_live_rejects_unsupported_display(self, qapp: Any) -> None:
        hardware = _FakeHardware((_display("m1", 0, supports_fullscreen=False),))
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSessionError, match="does not support fullscreen"):
            await vm.select_live("m1")

        assert hardware.begin_calls == []
        assert hardware.switch_calls == []
        assert hardware.session is None

    async def test_select_live_cleans_up_session_when_switch_rejected(
        self, qapp: Any
    ) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.report = _rejecting_report()
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        with pytest.raises(OutputSwitchError):
            await vm.select_live("p1")

        # The session started for the switch must not be left behind.
        assert hardware.session is None
        assert hardware.switch_calls == [("p1", window)]

    async def test_select_live_keeps_existing_session_when_switch_rejected(
        self, qapp: Any
    ) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.PREVIEW)
        hardware.report = _rejecting_report()
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSwitchError):
            await vm.select_live("p1")

        # A pre-existing session survives the failed switch.
        assert hardware.session is not None

    async def test_select_live_rolls_back_session_on_any_switch_failure(
        self, qapp: Any
    ) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.switch_error = RuntimeError("hardware blew up")
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(RuntimeError, match="hardware blew up"):
            await vm.select_live("p1")

        # The session started for the switch must not be left behind.
        assert hardware.session is None

    async def test_select_live_rolls_back_session_on_cancellation(
        self, qapp: Any
    ) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.switch_error = asyncio.CancelledError()
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(asyncio.CancelledError):
            await vm.select_live("p1")

        # Cancellation must not leave the created session behind.
        assert hardware.session is None


class TestEnterFullscreen:
    async def test_enter_fullscreen_moves_window(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.enter_fullscreen("p1")

        assert hardware.move_calls == [("p1", window, True)]
        assert hardware.begin_calls == ["p1"]

    async def test_enter_fullscreen_rejects_unsupported_display(
        self, qapp: Any
    ) -> None:
        hardware = _FakeHardware((_display("m1", 0, supports_fullscreen=False),))
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSessionError, match="does not support fullscreen"):
            await vm.enter_fullscreen("m1")

        assert hardware.move_calls == []

    async def test_enter_fullscreen_rejects_live_conflict(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0), _projector("p2", 1)))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSessionError, match="another display"):
            await vm.enter_fullscreen("p2")

        assert hardware.move_calls == []

    async def test_enter_fullscreen_rejects_frozen_live_conflict(
        self, qapp: Any
    ) -> None:
        """A frozen session still owns the live route — it conflicts."""
        hardware = _FakeHardware((_projector("p1", 0), _projector("p2", 1)))
        hardware.session = _FakeSession(OutputState.FREEZE, live_display_id="p1")
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSessionError, match="another display"):
            await vm.enter_fullscreen("p2")

        assert hardware.move_calls == []


class TestTestPattern:
    async def test_test_pattern_renders_through_window(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.test_pattern("p1", PatternKind.COLOUR_BARS)

        assert hardware.move_calls == [("p1", window, True)]
        assert window.patterns == [PatternKind.COLOUR_BARS]
        assert vm.last_pattern is PatternKind.COLOUR_BARS

    async def test_test_pattern_rejects_unsupported_display(self, qapp: Any) -> None:
        hardware = _FakeHardware((_display("m1", 0, supports_fullscreen=False),))
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSessionError, match="does not support fullscreen"):
            await vm.test_pattern("m1", PatternKind.COLOUR_BARS)

        assert hardware.move_calls == []
        assert hardware.begin_calls == []

    async def test_test_pattern_rejects_frozen_live_conflict(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0), _projector("p2", 1)))
        hardware.session = _FakeSession(OutputState.FREEZE, live_display_id="p1")
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        with pytest.raises(OutputSessionError, match="another display"):
            await vm.test_pattern("p2", PatternKind.COLOUR_BARS)

        assert hardware.move_calls == []
        assert window.patterns == []


class TestBlackout:
    async def test_blackout_cuts_hardware_and_window(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.blackout()

        assert hardware.blackout_calls == 1
        assert window.blackouts == 1


class TestExitOutput:
    async def test_exit_ends_session_and_hides_window(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.exit_output()

        assert hardware.session is None
        assert window.show_normal == 1
        assert window.hidden == 1


class TestFreeze:
    async def test_freeze_holds_frame(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.freeze()

        assert hardware.freeze_calls == 1
        assert window.freezes == 1
        assert vm.output_state is OutputState.FREEZE

    async def test_unfreeze_restores_last_pattern(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.FREEZE, live_display_id="p1")
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)
        await vm.test_pattern("p1", PatternKind.COLOUR_BARS)

        await vm.unfreeze()

        assert hardware.unfreeze_calls == 1
        # Applied once by the setup action, once by the unfreeze restore.
        assert window.patterns == [
            PatternKind.COLOUR_BARS,
            PatternKind.COLOUR_BARS,
        ]
        assert vm.last_pattern is PatternKind.COLOUR_BARS

    async def test_unfreeze_without_last_pattern_blackouts_coherently(
        self, qapp: Any
    ) -> None:
        """Live without a pattern must fall back to BLACKOUT, not lie."""
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.FREEZE, live_display_id="p1")
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        await vm.unfreeze()

        assert hardware.unfreeze_calls == 1
        assert hardware.blackout_calls == 1
        assert window.blackouts == 1
        assert vm.output_state is OutputState.BLACKOUT

    async def test_unfreeze_blackout_restore_stays_black(self, qapp: Any) -> None:
        """Unfreezing to BLACKOUT must not re-show the last pattern."""
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.FREEZE, live_display_id="p1")
        hardware.unfreeze_restores = OutputState.BLACKOUT
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)
        await vm.test_pattern("p1", PatternKind.COLOUR_BARS)

        await vm.unfreeze()

        assert hardware.unfreeze_calls == 1
        assert window.patterns == [PatternKind.COLOUR_BARS]
        assert window.blackouts == 1
        assert vm.last_pattern is PatternKind.COLOUR_BARS

    async def test_unfreeze_after_new_session_does_not_restore_stale_pattern(
        self, qapp: Any
    ) -> None:
        hardware = _FakeHardware((_projector("p1", 0), _projector("p2", 1)))
        vm = _make_vm(hardware)
        window = _FakeWindow()
        vm.attach_output_window(window)

        # Session 1: show a pattern, then end the session.
        await vm.test_pattern("p1", PatternKind.COLOUR_BARS)
        await vm.exit_output()

        # Session 2: starts without test_pattern; unfreeze must not restore it.
        await vm.select_preview("p2")
        await vm.freeze()
        await vm.unfreeze()

        assert window.patterns == [PatternKind.COLOUR_BARS]
        assert window.blackouts == 1
        assert vm._last_pattern is None
        assert vm.output_state is OutputState.BLACKOUT

    async def test_toggle_freeze_cycles(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        await vm.toggle_freeze()
        frozen = vm.output_state
        assert frozen is OutputState.FREEZE

        await vm.toggle_freeze()
        resumed = vm.output_state
        # No test pattern was set before freezing: unfreeze cannot
        # restore content, so the session falls back to BLACKOUT
        # instead of reporting LIVE with a black window.
        assert resumed is OutputState.BLACKOUT
        assert hardware.freeze_calls == 1
        assert hardware.unfreeze_calls == 1

    async def test_freeze_without_session_raises(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        with pytest.raises(OutputSessionError, match="No active output session"):
            await vm.freeze()

    async def test_freeze_without_output_window_raises(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)

        with pytest.raises(OutputSessionError, match="Output window unavailable"):
            await vm.freeze()

        # The gate must run before any hardware mutation.
        assert hardware.freeze_calls == 0

    async def test_unfreeze_without_output_window_raises(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.FREEZE, live_display_id="p1")
        vm = _make_vm(hardware)

        with pytest.raises(OutputSessionError, match="Output window unavailable"):
            await vm.unfreeze()

        # The gate must run before any hardware mutation.
        assert hardware.unfreeze_calls == 0

    async def test_detached_window_blocks_surface_actions(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)
        vm.attach_output_window(_FakeWindow())

        vm.attach_output_window(None)

        with pytest.raises(OutputSessionError, match="Output window unavailable"):
            await vm.freeze()

        # No output action may run against a detached (closed) window.
        assert hardware.freeze_calls == 0


class TestRefreshAndPreview:
    async def test_refresh_displays_returns_count(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0), _display("m1", 1)))
        vm = _make_vm(hardware)

        count = await vm.refresh_displays()

        assert count == 2
        assert hardware.refresh_calls == 1

    async def test_select_preview_starts_session_when_none(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)

        await vm.select_preview("p1")

        assert hardware.begin_calls == ["p1"]

    async def test_select_preview_repoints_existing_session(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0), _projector("p2", 1)))
        hardware.session = _FakeSession(OutputState.PREVIEW, preview_display_id="p1")
        vm = _make_vm(hardware)

        await vm.select_preview("p2")

        assert hardware.begin_calls == []
        assert hardware.preview_calls == ["p2"]

    async def test_select_preview_unknown_display_raises(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)

        with pytest.raises(DisplayNotFoundError):
            await vm.select_preview("nope")

        assert hardware.session is None


class TestEvents:
    def test_disconnect_of_live_display_sets_message(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)

        asyncio.run(
            vm._on_display_disconnected(DisplayDisconnected(display_id="p1", name="P1"))
        )

        assert vm.message is not None
        assert "disconnected" in vm.message

    def test_disconnect_of_unrelated_display_keeps_no_message(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0), _display("m1", 1)))
        hardware.session = _FakeSession(OutputState.LIVE, live_display_id="p1")
        vm = _make_vm(hardware)

        asyncio.run(
            vm._on_display_disconnected(DisplayDisconnected(display_id="m1", name="M1"))
        )

        assert vm.message is None

    def test_output_events_bump_revision(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        before = vm.revision

        asyncio.run(vm._on_output_event(DisplayLiveOutputChanged(display_id="p1")))

        assert vm.revision > before

    def test_disconnect_without_session_bumps_revision_only(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        before = vm.revision

        asyncio.run(
            vm._on_display_disconnected(DisplayDisconnected(display_id="p1", name="P1"))
        )

        assert vm.message is None
        assert vm.revision > before


class TestShutdown:
    _EVENT_TYPES = (
        DisplayDisconnected,
        DisplayConnected,
        DisplayLiveOutputChanged,
        DisplayPreviewOutputChanged,
        OutputSessionEnded,
        OutputLiveStarted,
        OutputBlackout,
        OutputFrozen,
        OutputUnfrozen,
    )

    def test_shutdown_unsubscribes_all_bus_handlers(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        bus = hardware.event_bus

        assert set(bus._handlers) == set(self._EVENT_TYPES)
        assert all(len(handlers) == 1 for handlers in bus._handlers.values())

        vm.shutdown()

        # All nine handler slots are empty (keys persist, as on the real bus).
        assert set(bus._handlers) == set(self._EVENT_TYPES)
        assert all(len(handlers) == 0 for handlers in bus._handlers.values())

    def test_shutdown_keeps_other_bus_subscribers(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)
        bus = hardware.event_bus

        def other(_event: Any) -> None:
            pass

        bus.subscribe(DisplayDisconnected, other)

        vm.shutdown()

        assert bus._handlers[DisplayDisconnected] == [other]

    def test_shutdown_is_idempotent(self, qapp: Any) -> None:
        hardware = _FakeHardware((_projector("p1", 0),))
        vm = _make_vm(hardware)

        vm.shutdown()
        vm.shutdown()  # must not raise
