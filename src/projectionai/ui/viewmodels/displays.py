"""DisplaysViewModel — display topology, validation, and output control.

Qt-free. Wraps the :class:`HardwareManager` facade: topology snapshots
(``displays()``, ``projectors()``, ``primary``), the last validation
report, output-session state, and async session actions (begin/end,
preview, live, fullscreen, test pattern, blackout, freeze, identify,
refresh). Widgets call the coroutines through ``run_async`` and
re-render on ``revision``.

The view model also owns the *output surface* contract: the application
shell attaches the renderer's output window (a Qt widget) through
:meth:`attach_output_window`; the view model drives it through the
Qt-free :class:`OutputSurface` protocol so this layer never imports Qt.
Every output action goes through safety gates (display connected /
fullscreen-capable / output window present / no conflicting live
session) before touching hardware.
"""

from __future__ import annotations

from typing import Protocol

from projectionai.core.events import Event
from projectionai.hardware.display_validator import ValidationReport
from projectionai.hardware.errors import OutputSessionError
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
from projectionai.hardware.models import DisplayInfo, HardwareStatus, OutputWindow
from projectionai.hardware.output_manager import OutputSession, OutputState
from projectionai.hardware.patterns import PatternKind
from projectionai.ui.viewmodels.observable import Observable


class OutputSurface(OutputWindow, Protocol):
    """Qt-free surface the view model drives for pattern/blackout/freeze.

    Inherits the hardware layer's :class:`OutputWindow` protocol (so the
    surface can be moved/fullscreened by the display manager) and adds
    content control + hide. :class:`~infrastructure.renderer.output_window.GLOutputWindow`
    (and test doubles) satisfy this protocol structurally; keeping it
    here keeps the view-model layer free of Qt imports.
    """

    def set_pattern(self, pattern: PatternKind) -> None: ...
    def set_blackout(self) -> None: ...
    def set_freeze(self) -> None: ...
    def hide(self) -> None: ...


class DisplaysViewModel(Observable):
    """Observable display/validation/output facade over the hardware manager."""

    def __init__(self, hardware: HardwareManager) -> None:
        super().__init__()
        self._hardware = hardware
        self._last_report: ValidationReport | None = None
        self._window: OutputSurface | None = None
        self._message: str | None = None
        self._last_pattern: PatternKind | None = None
        bus = hardware.event_bus
        bus.subscribe(DisplayDisconnected, self._on_display_disconnected)
        bus.subscribe(DisplayConnected, self._on_output_event)
        bus.subscribe(DisplayLiveOutputChanged, self._on_output_event)
        bus.subscribe(DisplayPreviewOutputChanged, self._on_output_event)
        bus.subscribe(OutputSessionEnded, self._on_output_event)
        bus.subscribe(OutputLiveStarted, self._on_output_event)
        bus.subscribe(OutputBlackout, self._on_output_event)
        bus.subscribe(OutputFrozen, self._on_output_event)
        bus.subscribe(OutputUnfrozen, self._on_output_event)

    # -- Topology ---------------------------------------------------------------

    def displays(self) -> tuple[DisplayInfo, ...]:
        """Every detected display, in index order."""
        return self._hardware.displays

    def projectors(self) -> tuple[DisplayInfo, ...]:
        """Displays classified as projectors."""
        return self._hardware.projectors

    def primary(self) -> DisplayInfo | None:
        """The primary display, if any."""
        return self._hardware.primary

    def get_display(self, display_id: str) -> DisplayInfo:
        """Look up a display by id (raises DisplayNotFoundError)."""
        return self._hardware.get_display(display_id)

    @property
    def display_count(self) -> int:
        """Number of detected displays."""
        return self._hardware.display_count

    @property
    def projector_count(self) -> int:
        """Number of projector-classified displays."""
        return self._hardware.projector_count

    # -- Validation -------------------------------------------------------------

    def validate(self) -> ValidationReport:
        """Validate the current topology; caches the last report."""
        self._last_report = self._hardware.validate()
        return self._last_report

    @property
    def last_report(self) -> ValidationReport | None:
        """The most recently computed validation report."""
        return self._last_report

    @property
    def is_healthy(self) -> bool:
        """True when the last validation had no errors."""
        report = self._last_report
        return report is not None and report.is_ok

    @property
    def snapshot(self) -> HardwareStatus:
        """Aggregated hardware status (counts + issues)."""
        return self._hardware.snapshot()

    # -- Output session ----------------------------------------------------------

    @property
    def session(self) -> OutputSession | None:
        """The active output session, if any."""
        return self._hardware.output_session

    @property
    def output_state(self) -> OutputState:
        """Current output-session state."""
        return self._hardware.output_state

    @property
    def is_live(self) -> bool:
        """True when the session is live."""
        return self._hardware.is_live

    @property
    def live_display_id(self) -> str | None:
        """Display currently receiving live output."""
        return self._hardware.live_display_id

    @property
    def preview_display_id(self) -> str | None:
        """Display currently receiving preview output."""
        return self._hardware.preview_display_id

    @property
    def last_pattern(self) -> PatternKind | None:
        """The last test pattern shown on the output surface (if any)."""
        return self._last_pattern

    # -- Output surface + user feedback -------------------------------------------

    def attach_output_window(self, window: OutputSurface | None) -> None:
        """Attach the output surface owned by the shell (or detach with ``None``)."""
        self._window = window
        self._notify()

    @property
    def message(self) -> str | None:
        """Last user-facing status/error message, if any."""
        return self._message

    def set_message(self, text: str | None) -> None:
        """Publish a user-facing status/error message."""
        self._message = text
        self._notify()

    def clear_message(self) -> None:
        """Clear the current user-facing message."""
        self.set_message(None)

    # -- Actions (async; call through run_async) ----------------------------------

    async def begin_session(self, preview_display_id: str | None = None) -> None:
        """Start a new output session."""
        await self._start_session(preview_display_id)
        self._notify()

    async def end_session(self) -> None:
        """End the active output session."""
        await self._hardware.end_output_session()
        self._notify()

    async def set_preview(self, display_id: str | None) -> None:
        """Change the preview target of the active session."""
        await self._hardware.set_output_preview(display_id)
        self._notify()

    async def arm(self) -> ValidationReport:
        """Validate and arm the session."""
        report = await self._hardware.arm_output()
        self._last_report = report
        self._notify()
        return report

    async def go_live(self) -> ValidationReport:
        """Switch the session live (raises OutputSwitchError on failure)."""
        report = await self._hardware.go_live()
        self._last_report = report
        self._notify()
        return report

    async def identify(self, display_id: str) -> None:
        """Flash/identify *display_id* on the physical hardware."""
        await self._hardware.identify_display(display_id)
        self._notify()

    async def refresh_displays(self) -> int:
        """Re-scan the display topology now; returns the display count."""
        displays = await self._hardware.refresh_displays()
        self._notify()
        return len(displays)

    async def select_preview(self, display_id: str) -> None:
        """Make *display_id* the preview target (starts a session if needed)."""
        self._hardware.get_display(display_id)  # raises when unknown
        if self._hardware.output_session is None:
            await self._start_session(display_id)
        else:
            await self._hardware.set_output_preview(display_id)
        self._notify()

    async def select_live(self, display_id: str) -> ValidationReport:
        """Route live output to *display_id* and fullscreen the output window.

        Starts a session when none exists. Safety gates run before the
        switch: the display must be connected and the output window must
        be attached. A rejected switch raises
        :class:`OutputSwitchError` with the validation report.
        """
        self._hardware.get_display(display_id)  # raises when unknown
        window = self._require_window()
        if self._hardware.output_session is None:
            await self._start_session()
        report = await self._hardware.switch_live_output(display_id, window)
        self._last_report = report
        self._notify()
        return report

    async def enter_fullscreen(self, display_id: str) -> None:
        """Fullscreen the output window on *display_id*.

        The display must be connected and fullscreen-capable; the
        output window must be attached; and no live session may be
        routed to a different display (avoid desyncing the physical
        output from the session route).
        """
        self._require_fullscreen(display_id)
        window = self._require_window()
        self._check_live_conflict(display_id)
        if self._hardware.output_session is None:
            await self._start_session(display_id)
        self._hardware.move_window_to(display_id, window, fullscreen=True)
        self._notify()

    async def test_pattern(self, display_id: str, pattern: PatternKind) -> None:
        """Show *pattern* fullscreen on *display_id* via the output window."""
        self._require_fullscreen(display_id)
        window = self._require_window()
        self._check_live_conflict(display_id)
        if self._hardware.output_session is None:
            await self._start_session(display_id)
        self._hardware.move_window_to(display_id, window, fullscreen=True)
        window.set_pattern(pattern)
        self._last_pattern = pattern
        self._notify()

    async def blackout(self) -> None:
        """Cut live output and black the output window."""
        await self._hardware.emergency_blackout()
        if self._window is not None:
            self._window.set_blackout()
        self._notify()

    async def exit_output(self) -> None:
        """End the session and restore/hide the output window."""
        await self._hardware.end_output_session()
        self._last_pattern = None
        if self._window is not None:
            self._window.showNormal()
            self._window.hide()
        self._notify()

    async def freeze(self) -> None:
        """Freeze the live output (holds the last rendered frame)."""
        await self._hardware.freeze_output()
        if self._window is not None:
            self._window.set_freeze()
        self._notify()

    async def unfreeze(self) -> None:
        """Resume the frozen output (restores the pre-freeze state)."""
        await self._hardware.unfreeze_output()
        if self._window is not None:
            if self.output_state is OutputState.BLACKOUT:
                self._window.set_blackout()
            elif self._last_pattern is not None:
                self._window.set_pattern(self._last_pattern)
            else:
                self._window.set_blackout()
        self._notify()

    async def toggle_freeze(self) -> None:
        """Freeze when running, unfreeze when frozen."""
        if self.output_state is OutputState.FREEZE:
            await self.unfreeze()
        else:
            await self.freeze()

    # -- Event handling ------------------------------------------------------------

    async def _on_display_disconnected(self, event: Event) -> None:
        if not isinstance(event, DisplayDisconnected):
            return
        session = self._hardware.output_session
        if session is not None and event.display_id in {
            session.live_display_id,
            session.preview_display_id,
        }:
            self.set_message(f"Display {event.name!r} disconnected — output affected.")
            return
        self._notify()

    async def _on_output_event(self, _event: Event) -> None:
        """Re-render after any output-route/session state change."""
        self._notify()

    # -- Internals ------------------------------------------------------------

    def _require_window(self) -> OutputSurface:
        if self._window is None:
            raise OutputSessionError("Output window unavailable — output is disabled.")
        return self._window

    async def _start_session(self, preview_display_id: str | None = None) -> None:
        """Begin a new output session; session-scoped state must not carry over."""
        await self._hardware.begin_output_session(preview_display_id)
        self._last_pattern = None

    def _require_fullscreen(self, display_id: str) -> DisplayInfo:
        display = self._hardware.get_display(display_id)  # raises when unknown
        if not display.capabilities.supports_fullscreen:
            raise OutputSessionError(
                f"{display.name!r} does not support fullscreen output."
            )
        return display

    def _check_live_conflict(self, display_id: str) -> None:
        session = self._hardware.output_session
        if (
            session is not None
            and session.state is OutputState.LIVE
            and session.live_display_id != display_id
        ):
            raise OutputSessionError(
                "Live output is on another display — exit output or switch live first."
            )
