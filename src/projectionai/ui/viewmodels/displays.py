"""DisplaysViewModel — display topology + validation for the Displays panel.

Qt-free. Wraps the :class:`HardwareManager` facade: topology snapshots
(``displays()``, ``projectors()``, ``primary``), the last validation
report, output-session state, and async session actions (begin/end,
preview, arm, live, blackout, identify). Widgets call the coroutines
through ``run_async`` and re-render on ``revision``.
"""

from __future__ import annotations

from projectionai.hardware.display_validator import ValidationReport
from projectionai.hardware.hardware_manager import HardwareManager
from projectionai.hardware.models import DisplayInfo, HardwareStatus
from projectionai.hardware.output_manager import OutputSession, OutputState
from projectionai.ui.viewmodels.observable import Observable


class DisplaysViewModel(Observable):
    """Observable display/validation facade over the hardware manager."""

    def __init__(self, hardware: HardwareManager) -> None:
        super().__init__()
        self._hardware = hardware
        self._last_report: ValidationReport | None = None

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

    # -- Validation -----------------------------------------------------------

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

    # -- Output session --------------------------------------------------------

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

    # -- Actions (async; call through run_async) --------------------------------

    async def begin_session(self, preview_display_id: str | None = None) -> None:
        """Start a new output session."""
        await self._hardware.begin_output_session(preview_display_id)
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

    async def blackout(self) -> None:
        """Cut live output."""
        await self._hardware.emergency_blackout()
        self._notify()

    async def identify(self, display_id: str) -> None:
        """Flash/identify *display_id* on the physical hardware."""
        await self._hardware.identify_display(display_id)
        self._notify()
