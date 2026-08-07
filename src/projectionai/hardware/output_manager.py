"""OutputManager — output sessions with safe live switching.

Owns the "output session" lifecycle: preview routing, arming, live
switching, blackout, and teardown. Every live switch is validated
through :class:`DisplayValidator` first — a switch that fails
validation is rejected (``OutputSwitchError`` carrying the report) and
the previous state is left untouched (safe switching).

Sessions are versioned records (``OutputSession``) kept in a history so
future multi-projector coordination can replay or audit them; today the
manager drives a single active session.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import override

from projectionai.core.events import EventBus
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_validator import (
    DisplayValidator,
    ValidateInputs,
    ValidationReport,
)
from projectionai.hardware.errors import (
    OutputSessionError,
    OutputSwitchError,
)
from projectionai.hardware.events import (
    OutputArmed,
    OutputBlackout,
    OutputLiveStarted,
    OutputPreviewChanged,
    OutputSessionEnded,
    OutputSessionStarted,
)
from projectionai.hardware.models import OutputWindow
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class OutputState(StrEnum):
    """Lifecycle state of an output session."""

    IDLE = "idle"
    PREVIEW = "preview"
    ARMED = "armed"
    LIVE = "live"
    BLACKOUT = "blackout"


@dataclass(frozen=True)
class OutputSession:
    """An immutable snapshot of one output session's state."""

    session_id: str
    state: OutputState = OutputState.IDLE
    preview_display_id: str | None = None
    live_display_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class OutputManager(Manager):
    """Drives preview/live output through validated sessions."""

    def __init__(
        self,
        event_bus: EventBus,
        display_manager: DisplayManager,
        validator: DisplayValidator | None = None,
        renderer_ready_provider: Callable[[], bool] | None = None,
        window_available_provider: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._display_manager = display_manager
        self._validator = validator or DisplayValidator()
        self._session: OutputSession | None = None
        self._history: list[OutputSession] = []
        self._renderer_ready_provider = renderer_ready_provider
        self._window_available_provider = window_available_provider

    # -- Lifecycle ---------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        """No-op — sessions are created on demand."""

    @override
    async def _on_shutdown(self) -> None:
        """Close the active session, if any."""
        if self._session is not None:
            await self.end_session()
        self._history.clear()

    # -- Session state -----------------------------------------------------

    @property
    def session(self) -> OutputSession | None:
        """The active session, or ``None``."""
        return self._session

    @property
    def state(self) -> OutputState:
        """State of the active session (``IDLE`` when none)."""
        return self._session.state if self._session else OutputState.IDLE

    @property
    def is_live(self) -> bool:
        """True when the active session is live."""
        return self.state is OutputState.LIVE

    @property
    def history(self) -> tuple[OutputSession, ...]:
        """Snapshots of every session transition (active included), oldest first."""
        return tuple(self._history)

    @property
    def display_manager(self) -> DisplayManager:
        """Return the underlying display manager."""
        return self._display_manager

    # -- Session lifecycle ---------------------------------------------------

    async def begin_session(
        self, preview_display_id: str | None = None
    ) -> OutputSession:
        """Start a new output session.

        The session starts in ``PREVIEW`` state when a preview display
        is given (and connected), else ``IDLE``.
        """
        self._require_initialized()
        if self._session is not None:
            raise OutputSessionError(
                "An output session is already active — end it first."
            )
        if preview_display_id is not None:
            self._display_manager.get(preview_display_id)  # raises if unknown
        session = OutputSession(
            session_id=uuid.uuid4().hex[:12],
            state=OutputState.PREVIEW if preview_display_id else OutputState.IDLE,
            preview_display_id=preview_display_id,
            live_display_id=None,
        )
        self._record(session)
        self._display_manager.set_preview_output(preview_display_id)
        self._emit_nowait(OutputSessionStarted(session.session_id, preview_display_id))
        _logger.info("Output session started: %s", session.session_id)
        return session

    async def end_session(self) -> None:
        """End the active session (safe from any state)."""
        self._require_initialized()
        session = self._session
        if session is None:
            return
        self._record(session)  # final snapshot of the session before clearing
        self._session = None
        self._display_manager.set_live_output(None)
        self._display_manager.set_preview_output(None)
        self._emit_nowait(OutputSessionEnded(session.session_id))
        _logger.info("Output session ended: %s", session.session_id)

    # -- Routing -------------------------------------------------------------

    async def set_preview(self, display_id: str | None) -> None:
        """Change the preview target of the active session."""
        self._require_initialized()
        session = self._require_session()
        if display_id is not None:
            self._display_manager.get(display_id)  # raises if unknown
        self._display_manager.set_preview_output(display_id)
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=session.state,
                preview_display_id=display_id,
                live_display_id=session.live_display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        self._emit_nowait(OutputPreviewChanged(session.session_id, display_id))

    async def arm(self) -> ValidationReport:
        """Validate the current routing and mark the session ``ARMED``.

        Safe: does not change live output. Returns the report so the UI
        can surface errors without aborting the intent.
        """
        self._require_initialized()
        session = self._require_session()
        report = self._validate_current(session, require_projector=True)
        if report.is_ok:
            self._record(
                OutputSession(
                    session_id=session.session_id,
                    state=OutputState.ARMED,
                    preview_display_id=session.preview_display_id,
                    live_display_id=session.live_display_id,
                    created_at=session.created_at,
                    updated_at=datetime.now(UTC),
                )
            )
            self._emit_nowait(OutputArmed(session.session_id, session.live_display_id))
        return report

    async def go_live(self) -> ValidationReport:
        """Switch the session live — only when validation passes.

        The live target is resolved first (auto-routing to the first
        projector when none was chosen) and the resolved target is what
        validation runs against; output is only switched afterwards.

        Raises:
            OutputSwitchError: When validation reports errors (the
                switch is aborted; state is unchanged).
        """
        self._require_initialized()
        session = self._require_session()
        live_id = session.live_display_id
        if live_id is None:
            # Auto-route to the first projector when none was chosen.
            projectors = self._display_manager.projectors
            if not projectors:
                raise OutputSwitchError(
                    "Live switch rejected: no projector available", ValidationReport()
                )
            live_id = projectors[0].display_id
            session = replace(session, live_display_id=live_id)
        report = self._validate_current(session, require_projector=True)
        if not report.is_ok:
            raise OutputSwitchError(f"Live switch rejected: {report.summary}", report)
        self._display_manager.set_live_output(live_id)
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=OutputState.LIVE,
                preview_display_id=session.preview_display_id,
                live_display_id=live_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        self._emit_nowait(OutputLiveStarted(session.session_id, live_id))
        _logger.info("Output live on %s", live_id)
        return report

    async def blackout(self) -> None:
        """Cut live output (state ``BLACKOUT``, live route kept)."""
        self._require_initialized()
        session = self._require_session()
        self._display_manager.set_live_output(None)
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=OutputState.BLACKOUT,
                preview_display_id=session.preview_display_id,
                live_display_id=session.live_display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        self._emit_nowait(OutputBlackout(session.session_id))

    # -- Safe switch helper ---------------------------------------------------

    async def switch_live_to(
        self, display_id: str, window: OutputWindow | None = None
    ) -> ValidationReport:
        """Validate, route, and move the output window to *display_id*.

        Combines :meth:`set_live_target` + :meth:`go_live`. The window
        is moved onto the target display only after validation passes.
        A rejected switch rolls back the target transition, leaving the
        prior session state and history untouched.
        """
        original = self._session
        try:
            await self.set_live_target(display_id)
            report = await self.go_live()
        except OutputSwitchError:
            if self._history and self._history[-1] is not original:
                self._history.pop()
            self._session = original
            raise
        if window is not None:
            self._display_manager.set_fullscreen(display_id, window)
        return report

    async def set_live_target(self, display_id: str) -> None:
        """Set the session's live target (no switch yet)."""
        self._require_initialized()
        session = self._require_session()
        self._display_manager.get(display_id)  # raises if unknown
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=session.state,
                preview_display_id=session.preview_display_id,
                live_display_id=display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )

    # -- Internals ------------------------------------------------------------

    def _require_session(self) -> OutputSession:
        if self._session is None:
            raise OutputSessionError("No active output session — begin one first.")
        return self._session

    def _record(self, session: OutputSession) -> None:
        """Make *session* current and append it to the transition history.

        Consecutive snapshots of the same state are collapsed: a session
        ended without any transition keeps a single history entry.
        """
        self._session = session
        if not self._history or self._history[-1] is not session:
            self._history.append(session)

    def _renderer_ready(self) -> bool:
        if self._renderer_ready_provider is not None:
            return self._renderer_ready_provider()
        return True

    def _window_available(self) -> bool:
        if self._window_available_provider is not None:
            return self._window_available_provider()
        return True

    def _validate_current(
        self, session: OutputSession, require_projector: bool = False
    ) -> ValidationReport:
        return self._validator.validate(
            ValidateInputs(
                displays=self._display_manager.displays,
                live_display_id=session.live_display_id,
                preview_display_id=session.preview_display_id,
                renderer_ready=self._renderer_ready(),
                window_available=self._window_available(),
                require_projector=require_projector,
            )
        )
