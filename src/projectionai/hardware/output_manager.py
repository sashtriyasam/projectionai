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

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from projectionai.calibration.validator import ValidationReport as CalReport

import time

from projectionai.calibration.validation_gate import (
    ValidationGate,
    ValidationGateResult,
)
from projectionai.core.events import EventBus
from projectionai.hardware.display_manager import DisplayManager
from projectionai.hardware.display_validator import (
    DisplayValidator,
    ValidateInputs,
    ValidationReport,
)
from projectionai.hardware.errors import (
    CalibrationInvalidError,
    DisplayLostError,
    DisplayNotFoundError,
    LiveNotAuthorizedError,
    OutputSessionError,
    OutputSwitchError,
)
from projectionai.hardware.events import (
    OutputArmed,
    OutputBlackout,
    OutputDisarmed,
    OutputFrozen,
    OutputLiveStarted,
    OutputPreviewChanged,
    OutputSessionEnded,
    OutputSessionStarted,
    OutputStopped,
    OutputUnfrozen,
)
from projectionai.hardware.models import DisplayMode, OutputWindow
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)

# Stale gate threshold: 300 seconds (5 minutes)
_GATE_STALE_SECONDS = 300.0


class OutputState(StrEnum):
    """Lifecycle state of an output session."""

    IDLE = "idle"
    PREVIEW = "preview"
    ARMING = "arming"
    ARMED = "armed"
    LIVE = "live"
    STOPPING = "stopping"
    BLACKOUT = "blackout"
    FREEZE = "freeze"
    FAILED = "failed"


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
        validation_gate: ValidationGate | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._display_manager = display_manager
        self._validator = validator or DisplayValidator()
        self._validation_gate = validation_gate
        self._session: OutputSession | None = None
        self._history: list[OutputSession] = []
        self._pre_freeze_state: OutputState | None = None
        self._renderer_ready_provider = renderer_ready_provider
        self._window_available_provider = window_available_provider
        self._calibration_report: CalReport | None = None
        self._hardware_pending: tuple[str, ...] = ()
        self._source_mode: str = "SYNTHETIC"
        self._last_gate_result: ValidationGateResult | None = None
        # Concurrency guards
        self._arming_lock = asyncio.Lock()
        self._live_lock = asyncio.Lock()
        self._stopping_lock = asyncio.Lock()

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

    # -- Gate context --------------------------------------------------------

    def set_calibration_context(
        self,
        *,
        calibration_report: CalReport | None = None,
        hardware_pending: tuple[str, ...] = (),
        source_mode: str = "SYNTHETIC",
    ) -> None:
        """Set the calibration context for the unified validation gate.

        Call this before :meth:`arm` or :meth:`go_live` so the gate can
        evaluate calibration quality, hardware pending, and source mode
        in addition to display routing.

        Args:
            calibration_report: Output of ``CalibrationValidator.validate()``.
                ``None`` means no calibration exists (gate FAILS V-01).
            hardware_pending: Tuple of pending hardware gate strings from
                ``ProductionWorkflow.hardware_pending``.
            source_mode: One of ``SYNTHETIC``, ``REPLAY``, ``LIVE``.
        """
        self._calibration_report = calibration_report
        self._hardware_pending = tuple(hardware_pending)
        sm = source_mode.upper() if source_mode else "SYNTHETIC"
        self._source_mode = sm if sm in ("SYNTHETIC", "REPLAY", "LIVE") else "SYNTHETIC"

    @property
    def gate_result(self) -> ValidationGateResult | None:
        """The most recent unified gate evaluation, or ``None`` if not yet run."""
        return self._last_gate_result

    @property
    def can_arm(self) -> bool:
        """True when the gate authorizes arming (or gate is not configured)."""
        if self._validation_gate is None:
            return True  # backward compat: no gate = legacy behavior
        return self._last_gate_result is not None and self._last_gate_result.can_arm

    @property
    def can_live(self) -> bool:
        """True when the gate authorizes going live (or gate is not configured)."""
        if self._validation_gate is None:
            return True
        return self._last_gate_result is not None and self._last_gate_result.can_live

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
        self._pre_freeze_state = None
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

    # -- Unified gate --------------------------------------------------------

    def _run_gate(
        self,
        *,
        display_report: ValidationReport | None = None,
        require_projector: bool = True,
    ) -> ValidationGateResult:
        assert self._validation_gate is not None
        if display_report is None:
            display_report = self._validate_current(
                self._require_session(), require_projector=require_projector
            )
        result = self._validation_gate.check(
            calibration_report=self._calibration_report,
            display_report=display_report,
            hardware_pending=self._hardware_pending,
            source_mode=self._source_mode,
        )
        self._last_gate_result = result
        return result

    async def arm(self, require_projector: bool = True) -> ValidationReport:
        """Validate the current routing and mark the session ``ARMED``.

        When a :class:`ValidationGate` is configured, the unified gate
        is evaluated in addition to the display validator.  The session
        only transitions to ARMED when **both** the display report is OK
        **and** the gate authorises arming.

        Safe: does not change live output. Returns the display report so
        the UI can surface errors without aborting the intent.
        Gate authorization failures do NOT raise — the report is returned
        for the UI to surface. This differs from go_live() which raises
        LiveNotAuthorizedError on gate failure.
        """
        async with self._arming_lock:
            self._require_initialized()
            session = self._require_session()

            # Only allow arming from PREVIEW or IDLE
            if session.state not in (OutputState.PREVIEW, OutputState.IDLE):
                raise OutputSessionError(
                    f"Cannot arm from {session.state.value!r} — "
                    "must be in PREVIEW or IDLE state."
                )

            # Transition to ARMING
            self._record(
                OutputSession(
                    session_id=session.session_id,
                    state=OutputState.ARMING,
                    preview_display_id=session.preview_display_id,
                    live_display_id=session.live_display_id,
                    created_at=session.created_at,
                    updated_at=datetime.now(UTC),
                )
            )

            try:
                report = self._validate_current(
                    session, require_projector=require_projector
                )

                gate_ok = True
                gate_result = None
                if self._validation_gate is not None:
                    gate_result = self._run_gate(
                        display_report=report,
                        require_projector=require_projector,
                    )
                    gate_ok = gate_result.can_arm

                if report.is_ok and gate_ok:
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
                    self._emit_nowait(
                        OutputArmed(session.session_id, session.live_display_id)
                    )
                    _logger.info("Output armed: %s", session.session_id)
                else:
                    # Rollback to previous state on failure (does not raise — caller checks report)
                    rollback_state = (
                        session.state
                        if session.state in (OutputState.PREVIEW, OutputState.IDLE)
                        else OutputState.PREVIEW
                    )
                    self._record(
                        OutputSession(
                            session_id=session.session_id,
                            state=rollback_state,
                            preview_display_id=session.preview_display_id,
                            live_display_id=session.live_display_id,
                            created_at=session.created_at,
                            updated_at=datetime.now(UTC),
                        )
                    )
            except Exception as exc:
                # Unexpected error during arm — transition to FAILED
                _logger.exception("Unexpected error during arm: %s", exc)
                self._record(
                    OutputSession(
                        session_id=session.session_id,
                        state=OutputState.FAILED,
                        preview_display_id=session.preview_display_id,
                        live_display_id=session.live_display_id,
                        created_at=session.created_at,
                        updated_at=datetime.now(UTC),
                    )
                )
                raise
            return report

    async def go_live(self, require_projector: bool = True) -> ValidationReport:
        """Switch the session live — only when validation passes.

        When a :class:`ValidationGate` is configured, the unified gate
        is evaluated in addition to the display validator.  The session
        only transitions to LIVE when **both** the display report is OK
        **and** the gate authorises going live.

        The live target is resolved first (auto-routing to the first
        projector when none was chosen) and the resolved target is what
        validation runs against; output is only switched afterwards.

        Raises:
            OutputSwitchError: When validation reports errors (the
                switch is aborted; state is unchanged).
            LiveNotAuthorizedError: When the validation gate rejects going live.

        Note: Unlike arm() which returns a report on gate failure, go_live()
        raises LiveNotAuthorizedError on gate failure. This asymmetry is
        intentional: arm() is a "safe" operation returning a report for UI
        display, while go_live() is a "critical" operation that must fail
        loudly on authorization failure.
        """
        async with self._live_lock:
            self._require_initialized()
            session = self._require_session()

            # Only allow going live from ARMED state
            if session.state is not OutputState.ARMED:
                raise OutputSessionError(
                    f"Cannot go live from {session.state.value!r} — "
                    "must be in ARMED state."
                )

            live_id = session.live_display_id
            if not require_projector:
                if live_id is None:
                    raise OutputSwitchError(
                        "Live switch rejected: no live target set. Call set_live_target() first.",
                        ValidationReport(),
                    )
            else:
                if live_id is None:
                    projectors = self._display_manager.projectors
                    if not projectors:
                        raise OutputSwitchError(
                            "Live switch rejected: no projector available",
                            ValidationReport(),
                        )
                    live_id = projectors[0].display_id
                    session = replace(session, live_display_id=live_id)

            try:
                # Validate display routing first
                report = self._validate_current(
                    session, require_projector=require_projector
                )
                if not report.is_ok:
                    raise OutputSwitchError(
                        f"Live switch rejected: {report.summary}", report
                    )

                # Re-evaluate authorization gate immediately before going live
                if self._validation_gate is not None:
                    gate_result = self._run_gate(
                        display_report=report,
                        require_projector=require_projector,
                    )
                    if not gate_result.can_live:
                        failed_gates = [
                            r.gate_id.value for r in gate_result.failed_gates
                        ]
                        raise LiveNotAuthorizedError(
                            f"Live switch rejected by validation gate: {failed_gates}",
                            gate_result,
                        )

                # Activate live output
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
            except (OutputSwitchError, LiveNotAuthorizedError):
                # Expected validation failures — re-raise without state change
                raise
            except Exception as exc:
                # Unexpected error during go_live — blackout and transition to FAILED
                _logger.exception("Unexpected error during go_live: %s", exc)
                with contextlib.suppress(Exception):
                    self._display_manager.set_live_output(None)
                self._record(
                    OutputSession(
                        session_id=session.session_id,
                        state=OutputState.FAILED,
                        preview_display_id=session.preview_display_id,
                        live_display_id=session.live_display_id,
                        created_at=session.created_at,
                        updated_at=datetime.now(UTC),
                    )
                )
                raise
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

    async def freeze(self) -> None:
        """Hold the current frame (state ``FREEZE``).

        Only valid while live or blacked out; the live route (when set)
        is kept so unfreezing resumes instantly. The output window is
        responsible for holding the last rendered frame.

        Raises:
            OutputSessionError: When the session is not live/blacked out
                (the state is left unchanged).
        """
        self._require_initialized()
        session = self._require_session()
        if session.state not in (OutputState.LIVE, OutputState.BLACKOUT):
            raise OutputSessionError(
                f"Cannot freeze from {session.state.value!r} — "
                "only live or blackout output can be frozen."
            )
        self._pre_freeze_state = session.state
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=OutputState.FREEZE,
                preview_display_id=session.preview_display_id,
                live_display_id=session.live_display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        self._emit_nowait(OutputFrozen(session.session_id, session.state))
        _logger.info("Output frozen: %s", session.session_id)

    async def unfreeze(self) -> None:
        """Resume from ``FREEZE`` to the state it was frozen from.

        When the frozen state was ``LIVE`` but the live display has
        since disconnected, falls back to ``BLACKOUT`` instead of
        reporting a live route that no longer exists.

        Raises:
            OutputSessionError: When the session is not frozen (the
                state is left unchanged).
        """
        self._require_initialized()
        session = self._require_session()
        if session.state is not OutputState.FREEZE:
            raise OutputSessionError(
                f"Cannot unfreeze from {session.state.value!r} — "
                "the session is not frozen."
            )
        restored = self._pre_freeze_state or OutputState.LIVE
        self._pre_freeze_state = None
        if restored is OutputState.LIVE:
            live_id = session.live_display_id
            if live_id is None or not self._display_manager.has(live_id):
                # The display that was live is gone: reporting LIVE would
                # lie (the display manager has already cleared the live
                # route). Fall back to BLACKOUT so the session state
                # matches the physical output.
                restored = OutputState.BLACKOUT
                self._display_manager.set_live_output(None)
            else:
                # Re-apply the route so the recorded live display and the
                # display manager's live output stay aligned (no-op when
                # the route never drifted).
                self._display_manager.set_live_output(live_id)
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=restored,
                preview_display_id=session.preview_display_id,
                live_display_id=session.live_display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        self._emit_nowait(OutputUnfrozen(session.session_id, restored))
        _logger.info("Output unfrozen: %s", session.session_id)

    async def disarm(self, reason: str = "Operator requested disarm") -> None:
        """Return from ARMED to PREVIEW state.

        Does not affect live output (only valid from ARMED/ARMING).
        """
        self._require_initialized()
        session = self._require_session()
        if session.state not in (OutputState.ARMED, OutputState.ARMING):
            raise OutputSessionError(
                f"Cannot disarm from {session.state.value!r} — "
                "must be in ARMED or ARMING state."
            )
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=OutputState.PREVIEW,
                preview_display_id=session.preview_display_id,
                live_display_id=session.live_display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        self._emit_nowait(OutputDisarmed(session.session_id, reason))
        _logger.info("Output disarmed: %s (reason: %s)", session.session_id, reason)

    async def safe_stop(self, reason: str = "Operator requested safe stop") -> None:
        """Idempotent safe stop from any state.

        - If LIVE: blackout, clear live route, end session
        - If ARMED/ARMING: disarm, end session
        - If PREVIEW/IDLE/FREEZE/BLACKOUT: end session
        - If STOPPING: no-op (already stopping)
        """
        async with self._stopping_lock:
            self._require_initialized()
            session = self._session
            if session is None:
                return  # already idle

            # Transition to STOPPING
            self._record(
                OutputSession(
                    session_id=session.session_id,
                    state=OutputState.STOPPING,
                    preview_display_id=session.preview_display_id,
                    live_display_id=session.live_display_id,
                    created_at=session.created_at,
                    updated_at=datetime.now(UTC),
                )
            )

            # Cut live output first if active
            if session.state in (OutputState.LIVE, OutputState.FREEZE):
                self._display_manager.set_live_output(None)
            # Blackout output window
            if session.state == OutputState.LIVE:
                try:
                    await self.blackout()
                except Exception as exc:
                    _logger.warning("Blackout during safe_stop failed: %s", exc)

            # Clear routes
            self._display_manager.set_live_output(None)
            self._display_manager.set_preview_output(None)

            self._emit_nowait(OutputSessionEnded(session.session_id))
            self._session = None
            self._pre_freeze_state = None

            self._emit_nowait(OutputStopped(session.session_id, reason))
            _logger.info(
                "Safe stop completed: %s (reason: %s)", session.session_id, reason
            )

    async def handle_display_loss(self, display_id: str) -> None:
        """Handle unexpected display disconnection.

        If the live display is lost while LIVE/FREEZE: safe stop + raise.
        If preview display lost: clear preview route.
        """
        self._require_initialized()
        session = self._session
        if session is None:
            return

        if session.live_display_id == display_id:
            # Live display lost - emergency safe stop
            await self.safe_stop(f"Live display lost: {display_id}")
            raise DisplayLostError(display_id)

        if session.preview_display_id == display_id:
            # Preview display lost - clear preview route
            self._record(
                OutputSession(
                    session_id=session.session_id,
                    state=session.state,
                    preview_display_id=None,
                    live_display_id=session.live_display_id,
                    created_at=session.created_at,
                    updated_at=datetime.now(UTC),
                )
            )
            self._display_manager.set_preview_output(None)
            self._emit_nowait(OutputPreviewChanged(session.session_id, None))
            _logger.warning("Preview display lost: %s", display_id)

    async def handle_resolution_change(
        self, display_id: str, old_mode: DisplayMode, new_mode: DisplayMode
    ) -> None:
        """Handle resolution/refresh rate change on active display.

        If live display resolution changes: invalidate live authorization.
        """
        self._require_initialized()
        session = self._session
        if session is None:
            return

        if session.live_display_id == display_id and session.state == OutputState.LIVE:
            # Live display resolution changed - must re-validate
            await self.safe_stop(
                f"Live display resolution changed: {old_mode.label} -> {new_mode.label}"
            )
            raise CalibrationInvalidError(
                f"Live display {display_id} resolution changed: {old_mode.label} -> {new_mode.label}",
                calibration_id=None,
            )

    def check_gate_stale(self) -> bool:
        """Check if the last gate evaluation is stale (> 300s)."""
        if self._last_gate_result is None:
            return True
        age = time.time() - self._last_gate_result.evaluated_at
        return age > _GATE_STALE_SECONDS

    async def rearm_after_failure(self) -> None:
        """Clear failed state and re-evaluate gate for re-arm attempt.

        Caller must ensure failure cause is resolved before calling.
        """
        self._require_initialized()
        session = self._require_session()
        if session.state not in (
            OutputState.FAILED,
            OutputState.PREVIEW,
            OutputState.IDLE,
        ):
            raise OutputSessionError(
                f"Cannot re-arm from {session.state.value!r} — "
                "must be in FAILED, PREVIEW, or IDLE."
            )
        self._record(
            OutputSession(
                session_id=session.session_id,
                state=OutputState.PREVIEW,
                preview_display_id=session.preview_display_id,
                live_display_id=session.live_display_id,
                created_at=session.created_at,
                updated_at=datetime.now(UTC),
            )
        )
        # Clear gate result to force re-evaluation
        self._last_gate_result = None
        _logger.info("Re-arm ready: %s", session.session_id)

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
            display = self._display_manager.get(display_id)
        except DisplayNotFoundError:
            self._session = original
            raise
        if not display.capabilities.supports_fullscreen:
            # The facade must not bypass the fullscreen capability gate:
            # a live switch moves the output window fullscreen on the
            # display, so a display that cannot go fullscreen is not a
            # valid live target here.
            raise OutputSessionError(
                f"{display.name!r} does not support fullscreen output."
            )
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
        """Set the session's live target (no switch yet).

        Rejected while the session is frozen: the live target of a
        frozen session must not change (unfreeze first), otherwise the
        recorded target could diverge from the actual live route.

        Raises:
            OutputSessionError: When the session is frozen.
        """
        self._require_initialized()
        session = self._require_session()
        if session.state is OutputState.FREEZE:
            raise OutputSessionError(
                "Cannot change the live target while the output is frozen."
            )
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
        self, session: OutputSession, require_projector: bool = True
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
