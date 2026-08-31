"""RuntimeWatchdog — continuous runtime safety monitor for live sessions.

Monitors an active output session and triggers a safe stop when runtime
conditions invalidate safe operation. The watchdog observes and triggers
existing safety operations (OutputManager.safe_stop()); it does NOT become
another authority or second state machine.

Triggers:
    - Display disconnected while live → DISPLAY_DISCONNECTED
    - Live display resolution changed → RESOLUTION_CHANGED
    - Gate evaluation stale (>threshold) → GATE_STALE
    - Gate authorization revoked (was authorized, now rejected) → GATE_REVOKED
    - Renderer GL context lost (>timeout) → RENDERER_UNHEALTHY

Design notes:
    - Uses time.monotonic() for renderer timeout to prevent NTP/DST jumps
      from breaking safety timeouts. Gate staleness uses time.time() because
      ValidationGateResult.evaluated_at is wall-clock; both sides must match.
    - CheckPassed events are emitted only on state transitions (first pass after
      start, or after a trigger recovery), not every cycle, to avoid log pressure.
    - safe_stop failure is treated as a critical escalation: the session is
      marked TRIGGERED (preventing re-arm) and a CRITICAL log is emitted.
    - CALIBRATION_INVALID is deferred to future phases; calibration invalidation
      is handled by OutputManager directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING

from projectionai.core.events import EventBus
from projectionai.hardware.events import (
    WatchdogCheckPassed,
    WatchdogStarted,
    WatchdogStopped,
    WatchdogTrigger,
    WatchdogTriggered,
)
from projectionai.managers import Manager

if TYPE_CHECKING:
    from projectionai.calibration.validation_gate import ValidationGate
    from projectionai.hardware.display_manager import DisplayManager
    from projectionai.hardware.output_manager import OutputManager

_logger = logging.getLogger(__name__)


class WatchdogState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    TRIGGERED = "triggered"
    STOPPING = "stopping"


class RuntimeWatchdog(Manager):
    """Continuous runtime safety monitor for live output sessions.

    Observes the active session and triggers OutputManager.safe_stop()
    when safety invariants are violated. Does NOT maintain a second state
    machine or replace any existing validation authority.

    Args:
        event_bus: Shared event bus for emitting watchdog events.
        output_manager: The output session manager to monitor and stop.
        display_manager: Display topology provider (for future use).
        validation_gate: Optional gate for staleness/revocation checks.
        renderer_ready_provider: Callable returning True when the GL
            renderer context is healthy. When it returns False for longer
            than ``renderer_timeout_s``, the watchdog triggers
            RENDERER_UNHEALTHY. The provider must be a lightweight poll;
            it is called every ``check_interval_s`` seconds.
        check_interval_s: Seconds between safety checks (default 5.0).
        gate_stale_threshold_s: Seconds after which a gate evaluation
            is considered stale and triggers GATE_STALE (default 300.0).
            This value is provisional and should be documented per
            deployment environment.
        renderer_timeout_s: Seconds the renderer can be unhealthy before
            triggering RENDERER_UNHEALTHY (default 10.0). This acts as a
            grace period for transient GPU context switches.
    """

    def __init__(
        self,
        event_bus: EventBus,
        output_manager: OutputManager,
        display_manager: DisplayManager,
        validation_gate: ValidationGate | None = None,
        renderer_ready_provider: Callable[[], bool] | None = None,
        *,
        check_interval_s: float = 5.0,
        gate_stale_threshold_s: float = 300.0,
        renderer_timeout_s: float = 10.0,
    ) -> None:
        super().__init__(event_bus)
        self._output_manager = output_manager
        self._display_manager = display_manager
        self._validation_gate = validation_gate
        self._renderer_ready_provider = renderer_ready_provider
        self._check_interval_s = check_interval_s
        self._gate_stale_threshold_s = gate_stale_threshold_s
        self._renderer_timeout_s = renderer_timeout_s
        self._state: WatchdogState = WatchdogState.STOPPED
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._session_id: str = ""
        # monotonic clock for renderer timeout (immune to NTP/DST jumps)
        self._last_renderer_ok_at: float = 0.0
        # wall-clock for gate staleness (must match ValidationGateResult.evaluated_at)
        self._last_gate_can_live: bool | None = None
        # Gate 19: track last check result to emit CheckPassed only on transitions
        self._last_check_passed: bool = True

    @property
    def state(self) -> WatchdogState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state is WatchdogState.RUNNING

    async def start(self, session_id: str) -> None:
        """Start monitoring a live session. Idempotent — no-op if already running."""
        async with self._lock:
            if self._state not in (WatchdogState.STOPPED, WatchdogState.TRIGGERED):
                return
            if self._task is not None and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
                self._task = None
            self._session_id = session_id
            self._state = WatchdogState.STARTING
            self._last_renderer_ok_at = time.monotonic()
            self._last_gate_can_live = None
            self._last_check_passed = True
            self._task = asyncio.create_task(self._run_loop(), name="runtime-watchdog")
            self._emit_nowait(WatchdogStarted(session_id))
            self._state = WatchdogState.RUNNING
            _logger.info("Watchdog started for session %s", session_id)

    async def stop(self, reason: str = "Operator requested stop") -> None:
        """Stop monitoring. Idempotent — safe to call multiple times."""
        async with self._lock:
            if self._state in (WatchdogState.STOPPED, WatchdogState.STOPPING):
                return
            self._state = WatchdogState.STOPPING
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        async with self._lock:
            self._state = WatchdogState.STOPPED
            self._emit_nowait(WatchdogStopped(self._session_id, reason))
            _logger.info("Watchdog stopped: %s", reason)

    async def _run_loop(self) -> None:
        """Main monitoring loop. Exits when state leaves RUNNING.

        Gate 2/4: Catches all exceptions to prevent silent watchdog death.
        If an unexpected exception occurs, the session is marked TRIGGERED
        (preventing re-arm), a CRITICAL log is emitted, and safe_stop is
        attempted to ensure the output is not left live and unprotected.
        """
        try:
            while self._state is WatchdogState.RUNNING:
                await asyncio.sleep(self._check_interval_s)
                if self._state is not WatchdogState.RUNNING:
                    break
                await self._check_all()
        except asyncio.CancelledError:
            return
        except Exception:
            # Gate 2/4: Watchdog must not silently disappear while LIVE.
            _logger.critical(
                "Watchdog loop crashed with unexpected exception", exc_info=True
            )
            async with self._lock:
                if self._state is not WatchdogState.TRIGGERED:
                    self._state = WatchdogState.TRIGGERED
                    self._emit_nowait(
                        WatchdogTriggered(
                            self._session_id,
                            WatchdogTrigger.RENDERER_UNHEALTHY,
                            "Watchdog loop crashed",
                        )
                    )
            # Gate 2: Attempt safe stop to prevent live output continuing
            # unprotected after watchdog failure.
            try:
                await self._output_manager.safe_stop(
                    reason="Watchdog loop crashed — attempting safe stop"
                )
            except Exception:
                _logger.critical(
                    "safe_stop FAILED after watchdog crash. "
                    "Session may still be live — manual intervention required.",
                    exc_info=True,
                )

    async def _check_all(self) -> None:
        trigger, details = self._evaluate()
        if trigger is not None:
            await self._trigger_safe_stop(trigger, details)
            self._last_check_passed = False
        else:
            # Gate 19: Only emit CheckPassed on state transitions to avoid
            # log pressure. Emit when transitioning from failed→passed
            # (e.g., first pass after start, or after a trigger recovery).
            if not self._last_check_passed:
                self._emit_nowait(WatchdogCheckPassed(self._session_id))
            self._last_check_passed = True

    def _evaluate(self) -> tuple[WatchdogTrigger | None, str]:
        """Evaluate all safety conditions. Returns (trigger, details) or (None, "")."""
        # Renderer health check (uses monotonic clock for safety)
        if self._renderer_ready_provider is not None:
            if not self._renderer_ready_provider():
                age = time.monotonic() - self._last_renderer_ok_at
                if age > self._renderer_timeout_s:
                    return (
                        WatchdogTrigger.RENDERER_UNHEALTHY,
                        f"Renderer not ready for {age:.1f}s",
                    )
            else:
                self._last_renderer_ok_at = time.monotonic()

        # Gate staleness and revocation check (uses wall-clock to match
        # ValidationGateResult.evaluated_at which is set with time.time())
        if self._validation_gate is not None:
            last_result = self._output_manager.gate_result
            if last_result is not None:
                age = time.time() - last_result.evaluated_at
                if age > self._gate_stale_threshold_s:
                    return (
                        WatchdogTrigger.GATE_STALE,
                        f"Gate evaluation stale: {age:.1f}s > {self._gate_stale_threshold_s}s",
                    )
                if self._last_gate_can_live is True and not last_result.can_live:
                    return (
                        WatchdogTrigger.GATE_REVOKED,
                        "Gate authorization revoked: can_live was True, now False",
                    )
                self._last_gate_can_live = last_result.can_live

        return None, ""

    async def _trigger_safe_stop(self, trigger: WatchdogTrigger, details: str) -> None:
        """Trigger a safe stop. Idempotent — only triggers once per session.

        Gate 3: If safe_stop fails, the session is already in TRIGGERED state
        (preventing re-arm). A CRITICAL log is emitted so operators are alerted
        immediately. The watchdog does NOT re-raise — the loop will exit on
        next iteration because state is no longer RUNNING.
        """
        async with self._lock:
            if self._state is WatchdogState.TRIGGERED:
                return
            self._state = WatchdogState.TRIGGERED
        self._emit_nowait(WatchdogTriggered(self._session_id, trigger, details))
        _logger.warning("Watchdog triggered: %s — %s", trigger.value, details)
        try:
            await self._output_manager.safe_stop(
                reason=f"Watchdog: {trigger.value} — {details}"
            )
        except Exception:
            # Gate 3: safe_stop failure is a critical escalation.
            # Session is in TRIGGERED state — manual intervention required.
            _logger.critical(
                "safe_stop FAILED during watchdog trigger (%s). "
                "Session is in TRIGGERED state — manual intervention required.",
                trigger.value,
                exc_info=True,
            )

    def notify_display_event(self, event_name: str, display_id: str) -> None:
        """Forward a display topology event to the watchdog.

        Called by HardwareManager when DisplayDisconnected or
        DisplayResolutionChanged events are received. If the event
        affects the live display, a safe stop is triggered asynchronously.

        Args:
            event_name: "disconnected" or "resolution_changed".
            display_id: The display that changed.
        """
        if self._state is not WatchdogState.RUNNING:
            return
        session = self._output_manager.session
        if session is None:
            return
        live_id = session.live_display_id
        if live_id is None or live_id != display_id:
            return
        if event_name == "disconnected":
            trigger = WatchdogTrigger.DISPLAY_DISCONNECTED
            detail = f"Live display {display_id} disconnected"
        elif event_name == "resolution_changed":
            trigger = WatchdogTrigger.RESOLUTION_CHANGED
            detail = f"Live display {display_id} resolution changed"
        else:
            return
        task = asyncio.create_task(self._trigger_safe_stop(trigger, detail))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _on_initialize(self) -> None:
        pass

    async def _on_shutdown(self) -> None:
        await self.stop(reason="Manager shutdown")
