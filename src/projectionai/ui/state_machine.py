"""Output state machine — the safety model of the editor shell.

Pure Python, no Qt dependency. The UI observes state changes through
registered callbacks; the state machine itself never touches widgets.

States and their meaning (per docs/UX-ARCHITECTURE.md):

- ``IDLE``     — no output configured, nothing projected.
- ``PREVIEW``  — editing state: the Preview window is live, the
                 projector is dark. Everything is safe and undoable.
- ``ARMED``    — the user pressed Arm: the next deliberate action
                 (Send) pushes Preview to the projector.
- ``LIVE``     — the projector shows the program output.
- ``BLACKOUT`` — the program keeps running but the output is black
                 (instant safety, Resolume-style ``B`` key).
- ``FREEZE``   — output is paused on the last frame (``D`` key).

Transition invariants:

- The projector only ever shows content after ``ARMED -> LIVE``.
- ``BLACKOUT`` and ``FREEZE`` are reachable from any outputting state
  and return to ``LIVE`` without re-arming.
- ``STOP`` returns to ``IDLE`` from any state.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

StateChangeHandler = Callable[[Any, Any], None]  # (old_state, new_state)


class OutputState(StrEnum):
    """Enumeration of output states (string values keep persistence safe)."""

    IDLE = "idle"
    PREVIEW = "preview"
    ARMED = "armed"
    LIVE = "live"
    BLACKOUT = "blackout"
    FREEZE = "freeze"


#: All valid transitions. A transition not listed here is rejected.
VALID_TRANSITIONS: dict[OutputState, set[OutputState]] = {
    OutputState.IDLE: {OutputState.PREVIEW, OutputState.ARMED},
    OutputState.PREVIEW: {OutputState.ARMED, OutputState.IDLE},
    OutputState.ARMED: {OutputState.LIVE, OutputState.PREVIEW, OutputState.IDLE},
    OutputState.LIVE: {OutputState.BLACKOUT, OutputState.FREEZE, OutputState.IDLE},
    OutputState.BLACKOUT: {OutputState.LIVE, OutputState.FREEZE, OutputState.IDLE},
    OutputState.FREEZE: {OutputState.LIVE, OutputState.BLACKOUT, OutputState.IDLE},
}


#: States in which the projector is actively displaying program content.
OUTPUTTING_STATES: frozenset[OutputState] = frozenset(
    {OutputState.LIVE, OutputState.BLACKOUT, OutputState.FREEZE}
)

#: States in which the projector is dark (no program content visible).
#: Includes ARMED (still safe: content not yet sent) and BLACKOUT (the
#: output is blacked). FREEZE is NOT dark — the last frame stays visible.
DARK_STATES: frozenset[OutputState] = frozenset(
    {
        OutputState.IDLE,
        OutputState.PREVIEW,
        OutputState.ARMED,
        OutputState.BLACKOUT,
    }
)


class OutputStateMachine:
    """Guarded output state machine.

    Usage::

        sm = OutputStateMachine()
        sm.subscribe(lambda old, new: print(old, "->", new))
        sm.arm()          # preview -> armed
        sm.send_to_live()  # armed -> live
        sm.blackout()      # live -> blackout
        sm.unblackout()    # blackout -> live
        sm.stop()          # live -> idle
    """

    def __init__(self, initial: OutputState = OutputState.IDLE) -> None:
        self._state: OutputState = initial
        self._handlers: list[StateChangeHandler] = []

    # -- Observers ----------------------------------------------------------

    def subscribe(self, handler: StateChangeHandler) -> None:
        """Register a callback invoked as ``(old, new)`` on every change."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: StateChangeHandler) -> None:
        """Remove a previously registered callback."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    # -- State --------------------------------------------------------------

    @property
    def state(self) -> OutputState:
        """Return the current state."""
        return self._state

    @property
    def is_outputting(self) -> bool:
        """True when the projector is actively displaying program content."""
        return self._state in OUTPUTTING_STATES

    @property
    def is_dark(self) -> bool:
        """True when the projector shows no program content.

        True for IDLE, PREVIEW, ARMED, and BLACKOUT. False for LIVE and
        FREEZE (a frozen frame is still visible).
        """
        return self._state in DARK_STATES

    @property
    def is_live(self) -> bool:
        """True when program content is visible (not blackout/freeze)."""
        return self._state == OutputState.LIVE

    # -- Core transition ----------------------------------------------------

    def can(self, target: OutputState) -> bool:
        """True when moving to ``target`` is a legal state change.

        ``False`` for the current state itself (no change) and for
        targets outside the transition table for the current state.
        """
        if target == self._state:
            return False
        allowed = VALID_TRANSITIONS.get(self._state, set())
        return target in allowed

    def transition(self, target: OutputState) -> bool:
        """Attempt a guarded transition.

        Returns ``True`` when the transition is legal and applied,
        ``False`` when the transition is invalid for the current state
        (the state is left untouched). A no-op transition to the
        current state succeeds without firing handlers.
        """
        if target == self._state:
            return True
        if not self.can(target):
            return False
        old = self._state
        self._state = target
        for handler in list(self._handlers):
            handler(old, target)
        return True

    # -- Intentions ---------------------------------------------------------

    def activate_preview(self) -> bool:
        """Enter the editing/preview state from idle."""
        return self.transition(OutputState.PREVIEW)

    def arm(self) -> bool:
        """Arm the output: the next ``send_to_live`` pushes to the projector."""
        if self._state in (OutputState.IDLE, OutputState.PREVIEW):
            return self.transition(OutputState.ARMED)
        return self._state == OutputState.ARMED

    def send_to_live(self) -> bool:
        """Push the current preview state to the projector (requires ARM)."""
        return self.transition(OutputState.LIVE)

    def disarm(self) -> bool:
        """Return to preview from armed without sending anything."""
        return self.transition(OutputState.PREVIEW)

    def blackout(self) -> bool:
        """Instantly black the output. Safe from live, freeze, or blackout."""
        return self.transition(OutputState.BLACKOUT)

    def unblackout(self) -> bool:
        """Restore the program output after a blackout."""
        return self.transition(OutputState.LIVE)

    def freeze(self) -> bool:
        """Pause output on the current frame (hold-to-freeze semantics)."""
        return self.transition(OutputState.FREEZE)

    def unfreeze(self) -> bool:
        """Resume output after a freeze."""
        return self.transition(OutputState.LIVE)

    def stop(self) -> bool:
        """Stop output entirely; return to idle."""
        return self.transition(OutputState.IDLE)

    def toggle_blackout(self) -> bool:
        """Blackout when outputting, restore when blacked out."""
        if self._state == OutputState.BLACKOUT:
            return self.transition(OutputState.LIVE)
        if self._state in OUTPUTTING_STATES:
            return self.transition(OutputState.BLACKOUT)
        return False

    # -- Description helpers ------------------------------------------------

    def describe(self) -> str:
        """Return a human-readable status line for the current state."""
        return {
            OutputState.IDLE: "Idle",
            OutputState.PREVIEW: "Preview",
            OutputState.ARMED: "Armed — press Enter to send",
            OutputState.LIVE: "LIVE",
            OutputState.BLACKOUT: "BLACKOUT",
            OutputState.FREEZE: "FREEZE",
        }[self._state]
