"""OutputViewModel — binds the output state machine to UI needs.

Qt-free. Widgets subscribe to change callbacks or poll ``revision``;
the status bar and toolbar read the exposed state properties. The
state machine itself (ui.state_machine) holds all transition rules.
"""

from __future__ import annotations

from collections.abc import Callable

from projectionai.ui.state_machine import (
    OutputState,
    OutputStateMachine,
)
from projectionai.ui.theme import STATE_COLORS

ChangeHandler = Callable[[OutputState, OutputState], None]
PollHandler = Callable[[], None]


class OutputViewModel:
    """Observable wrapper over :class:`OutputStateMachine`."""

    def __init__(self, state_machine: OutputStateMachine | None = None) -> None:
        self._machine = state_machine or OutputStateMachine()
        self._handlers: list[ChangeHandler] = []
        self._history: list[tuple[OutputState, OutputState]] = []
        self._revision: int = 0
        self._closed: bool = False
        self._machine.subscribe(self._on_transition)

    # -- Observation ----------------------------------------------------------

    @property
    def revision(self) -> int:
        """Increment on every state change (cheap poll target)."""
        return self._revision

    def subscribe(self, handler: ChangeHandler) -> None:
        """Register a callback invoked as ``(old_state, new_state)``."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: ChangeHandler) -> None:
        """Remove a previously registered callback."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    # -- Lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Release the state machine subscription. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._machine.unsubscribe(self._on_transition)

    # -- State accessors ------------------------------------------------------

    @property
    def state(self) -> OutputState:
        """Return the current output state."""
        return self._machine.state

    @property
    def is_live(self) -> bool:
        """True when program content is visible."""
        return self._machine.is_live

    @property
    def is_dark(self) -> bool:
        """True when the projector shows no program content."""
        return self._machine.is_dark

    @property
    def is_outputting(self) -> bool:
        """True when the projector is actively displaying (incl. blackout)."""
        return self._machine.is_outputting

    @property
    def label(self) -> str:
        """Human-readable state label (e.g. ``"LIVE"``, ``"Armed"``)."""
        return self._machine.describe()

    @property
    def color(self) -> str:
        """Theme color token for the current state."""
        return STATE_COLORS.get(self.state.value, "#8A8F9C")

    @property
    def history(self) -> list[tuple[OutputState, OutputState]]:
        """Recent transitions as ``(old, new)`` pairs, oldest first."""
        return list(self._history)

    # -- Action guards (UI enablement) ---------------------------------------

    def can_arm(self) -> bool:
        """True when Arm is available (idle/preview)."""
        return self._machine.can(OutputState.ARMED)

    def can_send(self) -> bool:
        """True when Send-to-Live is available (armed)."""
        return self.state == OutputState.ARMED

    def can_disarm(self) -> bool:
        """True when the operator may abort an armed state."""
        return self.state == OutputState.ARMED

    def can_blackout(self) -> bool:
        """True when blackout may be engaged."""
        return self._machine.can(OutputState.BLACKOUT)

    def can_unblackout(self) -> bool:
        """True when output may be restored from blackout."""
        return self.state == OutputState.BLACKOUT

    def can_freeze(self) -> bool:
        """True when output may be frozen."""
        return self._machine.can(OutputState.FREEZE)

    def can_unfreeze(self) -> bool:
        """True when output may be resumed from freeze."""
        return self.state == OutputState.FREEZE

    def can_stop(self) -> bool:
        """True when the output can be stopped entirely."""
        return self._machine.can(OutputState.IDLE)

    # -- Actions --------------------------------------------------------------

    def activate_preview(self) -> bool:
        """Enter preview from idle; returns True when applied."""
        return self._machine.activate_preview()

    def arm(self) -> bool:
        """Arm the output; returns True when applied."""
        return self._machine.arm()

    def send_to_live(self) -> bool:
        """Push preview to the projector; returns True when applied."""
        return self._machine.send_to_live()

    def disarm(self) -> bool:
        """Abort an armed state; returns True when applied."""
        return self._machine.disarm()

    def blackout(self) -> bool:
        """Instantly black the output; returns True when applied."""
        return self._machine.blackout()

    def unblackout(self) -> bool:
        """Restore output after blackout; returns True when applied."""
        return self._machine.unblackout()

    def toggle_blackout(self) -> bool:
        """Toggle blackout; returns True when a change was applied."""
        return self._machine.toggle_blackout()

    def freeze(self) -> bool:
        """Freeze output on the current frame; returns True when applied."""
        return self._machine.freeze()

    def unfreeze(self) -> bool:
        """Resume output after freeze; returns True when applied."""
        return self._machine.unfreeze()

    def stop(self) -> bool:
        """Stop output and return to idle; returns True when applied."""
        return self._machine.stop()

    # -- Internal -------------------------------------------------------------

    def _on_transition(self, old: OutputState, new: OutputState) -> None:
        if self._closed:
            return
        self._history.append((old, new))
        if len(self._history) > 20:
            self._history = self._history[-20:]
        self._revision += 1
        for handler in list(self._handlers):
            handler(old, new)
