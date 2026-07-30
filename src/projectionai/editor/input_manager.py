"""Input manager — routes mouse, keyboard, and wheel events to editor subsystems."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

_logger = logging.getLogger(__name__)


@dataclass
class MouseState:
    """Snapshot of the current mouse state."""

    x: float = 0.0
    y: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    left: bool = False
    right: bool = False
    middle: bool = False
    ctrl: bool = False
    shift: bool = False
    alt: bool = False

    @property
    def any_button(self) -> bool:
        return self.left or self.right or self.middle

    @property
    def modifiers(self) -> list[str]:
        mods: list[str] = []
        if self.ctrl:
            mods.append("ctrl")
        if self.shift:
            mods.append("shift")
        if self.alt:
            mods.append("alt")
        return mods


@dataclass
class KeyBinding:
    """A single key binding definition."""

    key: str
    modifiers: tuple[str, ...] = ()
    description: str = ""


class InputManager:
    """Central input router for the editor viewport.

    Receives raw mouse / keyboard / wheel events from the viewport widget
    and dispatches them to registered handlers based on the active tool
    and modifier state.

    The manager supports:

    - **Mouse handlers** — called on press/release/move with the current
      :class:`MouseState`.
    - **Wheel handlers** — called with a delta value.
    - **Keyboard shortcuts** — configurable key-to-action mapping.

    Input routing is context-aware: handlers can be enabled/disabled based
    on the active tool or editor mode.
    """

    def __init__(self) -> None:
        self._mouse_state = MouseState()

        # Handler lists
        self._mouse_press_handlers: list[Callable[[MouseState], None]] = []
        self._mouse_release_handlers: list[Callable[[MouseState, str], None]] = []
        self._mouse_move_handlers: list[Callable[[MouseState], None]] = []
        self._wheel_handlers: list[Callable[[float], None]] = []

        # Keyboard shortcuts: action_name -> KeyBinding
        self._shortcuts: dict[str, KeyBinding] = {}
        # Reverse lookup: (normalized_key, frozenset{modifiers}) -> action_name
        self._key_map: dict[tuple[str, frozenset[str]], str] = {}

    # -- Mouse event dispatch -----------------------------------------------

    def on_press(self, x: float, y: float, button: str, modifiers: list[str]) -> None:
        """Handle a mouse button press event.

        Args:
            x: Viewport-space x coordinate.
            y: Viewport-space y coordinate.
            button: ``"left"``, ``"right"``, or ``"middle"``.
            modifiers: Active modifier keys (``"ctrl"``, ``"shift"``, ``"alt"``).
        """
        self._update_modifiers(modifiers)
        state = self._mouse_state
        state.x = x
        state.y = y
        state.dx = 0.0
        state.dy = 0.0

        if button == "left":
            state.left = True
        elif button == "right":
            state.right = True
        elif button == "middle":
            state.middle = True

        for handler in self._mouse_press_handlers:
            handler(state)

    def on_release(self, x: float, y: float, button: str, modifiers: list[str]) -> None:
        """Handle a mouse button release event."""
        self._update_modifiers(modifiers)
        state = self._mouse_state
        state.x = x
        state.y = y

        if button == "left":
            state.left = False
        elif button == "right":
            state.right = False
        elif button == "middle":
            state.middle = False

        for handler in self._mouse_release_handlers:
            handler(state, button)

    def on_move(self, x: float, y: float, modifiers: list[str]) -> None:
        """Handle a mouse move event."""
        prev_x, prev_y = self._mouse_state.x, self._mouse_state.y
        self._update_modifiers(modifiers)
        state = self._mouse_state
        state.dx = x - prev_x
        state.dy = y - prev_y
        state.x = x
        state.y = y

        for handler in self._mouse_move_handlers:
            handler(state)

    def on_wheel(self, delta: float, modifiers: list[str]) -> None:
        """Handle a mouse wheel event.

        Args:
            delta: Scroll delta (positive = up, negative = down).
            modifiers: Active modifier keys.
        """
        self._update_modifiers(modifiers)
        for handler in self._wheel_handlers:
            handler(delta)

    # -- Handler registration -----------------------------------------------

    def add_press_handler(self, handler: Callable[[MouseState], None]) -> None:
        """Register a mouse-press handler."""
        self._mouse_press_handlers.append(handler)

    def add_release_handler(self, handler: Callable[[MouseState, str], None]) -> None:
        """Register a mouse-release handler."""
        self._mouse_release_handlers.append(handler)

    def add_move_handler(self, handler: Callable[[MouseState], None]) -> None:
        """Register a mouse-move handler."""
        self._mouse_move_handlers.append(handler)

    def add_wheel_handler(self, handler: Callable[[float], None]) -> None:
        """Register a wheel handler."""
        self._wheel_handlers.append(handler)

    def remove_press_handler(self, handler: Callable[[MouseState], None]) -> None:
        """Remove a previously registered press handler."""
        if handler in self._mouse_press_handlers:
            self._mouse_press_handlers.remove(handler)

    def remove_release_handler(
        self, handler: Callable[[MouseState, str], None]
    ) -> None:
        """Remove a previously registered release handler."""
        if handler in self._mouse_release_handlers:
            self._mouse_release_handlers.remove(handler)

    def remove_move_handler(self, handler: Callable[[MouseState], None]) -> None:
        """Remove a previously registered move handler."""
        if handler in self._mouse_move_handlers:
            self._mouse_move_handlers.remove(handler)

    def remove_wheel_handler(self, handler: Callable[[float], None]) -> None:
        """Remove a previously registered wheel handler."""
        if handler in self._wheel_handlers:
            self._wheel_handlers.remove(handler)

    def clear_handlers(self) -> None:
        """Remove all registered handlers."""
        self._mouse_press_handlers.clear()
        self._mouse_release_handlers.clear()
        self._mouse_move_handlers.clear()
        self._wheel_handlers.clear()

    def reset_state(self) -> None:
        """Reset mouse state (useful on focus loss)."""
        self._mouse_state = MouseState()

    # -- Keyboard shortcuts -------------------------------------------------

    def register_shortcut(
        self,
        action: str,
        key: str,
        modifiers: tuple[str, ...] = (),
        description: str = "",
    ) -> None:
        """Register a keyboard shortcut.

        Args:
            action: Unique action name (e.g. ``"delete"``, ``"duplicate"``).
            key: Key identifier (e.g. ``"G"``, ``"R"``, ``"S"``, ``"Delete"``).
            modifiers: Required modifier keys.
            description: Human-readable description for UI.
        """
        mods = frozenset(m.lower() for m in modifiers)
        normalized_key = self._normalize_key(key)
        key_code = (normalized_key, mods)

        existing = self._shortcuts.get(action)
        if existing is not None:
            old_key_code = (
                self._normalize_key(existing.key),
                frozenset(m.lower() for m in existing.modifiers),
            )
            self._key_map.pop(old_key_code, None)

        previous_action = self._key_map.get(key_code)
        if previous_action is not None and previous_action != action:
            _logger.warning(
                "Shortcut collision: key %r (modifiers %s) already bound to "
                "action %r — reassigning to %r",
                key,
                modifiers,
                previous_action,
                action,
            )
            self._shortcuts.pop(previous_action, None)

        binding = KeyBinding(
            key=key, modifiers=tuple(sorted(modifiers)), description=description
        )
        self._shortcuts[action] = binding
        self._key_map[key_code] = action

    def on_key(self, key: str, modifiers: list[str]) -> str | None:
        """Process a key press and return the triggered action, if any.

        Args:
            key: The pressed key identifier.
            modifiers: Active modifiers.

        Returns:
            The action name if a shortcut matched, ``None`` otherwise.
        """
        key_code = (self._normalize_key(key), frozenset(m.lower() for m in modifiers))
        return self._key_map.get(key_code)

    # -- State access -------------------------------------------------------

    @property
    def mouse_state(self) -> MouseState:
        """Current mouse state (read-only snapshot)."""
        return MouseState(
            x=self._mouse_state.x,
            y=self._mouse_state.y,
            dx=self._mouse_state.dx,
            dy=self._mouse_state.dy,
            left=self._mouse_state.left,
            right=self._mouse_state.right,
            middle=self._mouse_state.middle,
            ctrl=self._mouse_state.ctrl,
            shift=self._mouse_state.shift,
            alt=self._mouse_state.alt,
        )

    @property
    def shortcuts(self) -> dict[str, KeyBinding]:
        """Registered shortcut bindings (read-only)."""
        return dict(self._shortcuts)

    # -- Internal -----------------------------------------------------------

    def _update_modifiers(self, modifiers: list[str]) -> None:
        mods = set(m.lower() for m in modifiers)
        self._mouse_state.ctrl = "ctrl" in mods
        self._mouse_state.shift = "shift" in mods
        self._mouse_state.alt = "alt" in mods

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Normalize a key string for comparison."""
        return key.strip().lower()
