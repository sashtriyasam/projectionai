"""HardwareManager — facade over the hardware subsystem.

Aggregates display topology, validation status, output-session state,
and an emergency blackout into one manager the Application wires up.
"""

from __future__ import annotations

import contextlib
from typing import override

from projectionai.core.events import EventBus
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_validator import (
    DisplayValidator,
    ValidateInputs,
    ValidationReport,
)
from projectionai.hardware.display_watcher import DisplayWatcher
from projectionai.hardware.models import (
    DisplayInfo,
    DisplayKind,
    HardwareStatus,
    OutputWindow,
)
from projectionai.hardware.output_manager import (
    OutputManager,
    OutputSession,
    OutputState,
)
from projectionai.managers import Manager


async def _shutdown_quietly(manager: Manager) -> None:
    """Best-effort rollback of an initialized sub-manager.

    Suppresses cleanup errors so the original initialization failure
    always propagates.
    """
    with contextlib.suppress(Exception):
        await manager.shutdown()


class HardwareManager(Manager):
    """Composite manager for the hardware layer."""

    def __init__(
        self,
        event_bus: EventBus,
        display_manager: DisplayManager,
        watcher: DisplayWatcher,
        output_manager: OutputManager,
        validator: DisplayValidator | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._display_manager = display_manager
        self._watcher = watcher
        self._output_manager = output_manager
        self._validator = validator or DisplayValidator()

    @override
    async def _on_initialize(self) -> None:
        async with contextlib.AsyncExitStack() as stack:
            for manager in (
                self._display_manager,
                self._watcher,
                self._output_manager,
            ):
                await manager.initialize()
                stack.push_async_callback(_shutdown_quietly, manager)
            stack.pop_all()

    @override
    async def _on_shutdown(self) -> None:
        await self._output_manager.shutdown()
        await self._watcher.shutdown()
        await self._display_manager.shutdown()

    # -- Topology -----------------------------------------------------------

    @property
    def displays(self) -> tuple[DisplayInfo, ...]:
        """Snapshot of every detected display."""
        return self._display_manager.displays

    @property
    def projectors(self) -> tuple[DisplayInfo, ...]:
        """Snapshot of every projector-classified display."""
        return self._display_manager.projectors

    @property
    def primary(self) -> DisplayInfo | None:
        """The primary display, if any."""
        return self._display_manager.primary

    @property
    def display_count(self) -> int:
        return len(self._display_manager.displays)

    @property
    def projector_count(self) -> int:
        return len(self._display_manager.projectors)

    # -- Validation -----------------------------------------------------------

    def validate(self) -> ValidationReport:
        """Validate the current topology."""
        return self._validator.validate(
            ValidateInputs(
                displays=self._display_manager.displays,
                live_display_id=(
                    self._output_manager.session.live_display_id
                    if self._output_manager.session
                    else None
                ),
                preview_display_id=(
                    self._output_manager.session.preview_display_id
                    if self._output_manager.session
                    else None
                ),
            )
        )

    # -- Output ----------------------------------------------------------------

    @property
    def output_state(self) -> OutputState:
        """Current output-session state."""
        return self._output_manager.state

    @property
    def is_live(self) -> bool:
        return self._output_manager.is_live

    @property
    def live_display_id(self) -> str | None:
        """Display currently receiving live output."""
        if self._output_manager.session:
            return self._output_manager.session.live_display_id
        return None

    @property
    def preview_display_id(self) -> str | None:
        """Display currently receiving preview output."""
        if self._output_manager.session:
            return self._output_manager.session.preview_display_id
        return None

    @property
    def output_session(self) -> OutputSession | None:
        """The active output session, if any."""
        return self._output_manager.session

    async def begin_output_session(self, preview_display_id: str | None = None) -> None:
        """Start a new output session."""
        await self._output_manager.begin_session(preview_display_id)

    async def end_output_session(self) -> None:
        """End the active output session."""
        await self._output_manager.end_session()

    async def set_output_preview(self, display_id: str | None) -> None:
        """Change the preview target of the active session."""
        await self._output_manager.set_preview(display_id)

    async def arm_output(self) -> ValidationReport:
        """Validate and arm the session; returns the ValidationReport."""
        return await self._output_manager.arm()

    async def go_live(self) -> ValidationReport:
        """Switch the session live; returns the ValidationReport."""
        return await self._output_manager.go_live()

    async def identify_display(self, display_id: str) -> None:
        """Flash the identified display on the physical hardware."""
        await self._display_manager.identify(display_id)

    def get_display(self, display_id: str) -> DisplayInfo:
        """Look up a display by id; raises DisplayNotFoundError."""
        return self._display_manager.get(display_id)

    async def emergency_blackout(self) -> None:
        """Cut live output immediately from any state."""
        if self._output_manager.session is None:
            return
        await self._output_manager.blackout()

    def move_window_to(
        self, display_id: str, window: OutputWindow, fullscreen: bool = True
    ) -> None:
        """Move an output window onto a display, fullscreen when requested."""
        if fullscreen:
            self._display_manager.set_fullscreen(display_id, window)
        else:
            self._display_manager.move_window_to(display_id, window)

    # -- Status ---------------------------------------------------------------

    def snapshot(self) -> HardwareStatus:
        """Aggregate hardware status for the status bar / UI."""
        report = self.validate()
        displays = self._display_manager.displays
        return HardwareStatus(
            display_count=self._display_manager.display_count,
            projector_count=sum(1 for d in displays if d.kind is DisplayKind.PROJECTOR),
            monitor_count=sum(1 for d in displays if d.kind is DisplayKind.MONITOR),
            virtual_count=sum(1 for d in displays if d.kind is DisplayKind.VIRTUAL),
            unknown_count=sum(1 for d in displays if d.kind is DisplayKind.UNKNOWN),
            issue_count=len(report.errors),
            warning_count=len(report.warnings),
        )
