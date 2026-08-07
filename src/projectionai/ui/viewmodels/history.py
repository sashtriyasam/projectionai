"""HistoryViewModel — undo/redo history for the History panel.

Qt-free. Wraps :class:`CommandManager` and renders the undo/redo
stacks as a branching list (Blender-style): the undo stack is shown
top-of-stack first, followed by the redo stack. Undo/redo are async on
the manager, so the widgets re-render after awaiting.
"""

from __future__ import annotations

from projectionai.domain.command import Command
from projectionai.managers.command_manager import CommandManager
from projectionai.ui.viewmodels.observable import Observable


class HistoryViewModel(Observable):
    """Observable command-history facade."""

    def __init__(self, command_manager: CommandManager) -> None:
        super().__init__()
        self._commands = command_manager

    # -- State ----------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        """True when an undo step is available."""
        return self._commands.can_undo

    @property
    def can_redo(self) -> bool:
        """True when a redo step is available."""
        return self._commands.can_redo

    @property
    def undo_text(self) -> str:
        """Description of the next command to undo."""
        return self._commands.undo_text

    @property
    def redo_text(self) -> str:
        """Description of the next command to redo."""
        return self._commands.redo_text

    @property
    def undo_depth(self) -> int:
        """Number of available undo steps."""
        return self._commands.undo_depth

    @property
    def redo_depth(self) -> int:
        """Number of available redo steps."""
        return self._commands.redo_depth

    # -- Listing --------------------------------------------------------------

    def undo_entries(self) -> list[Command]:
        """Undo stack, most-recent first (top of stack first)."""
        return list(reversed(self._commands.history.undo_stack))

    def redo_entries(self) -> list[Command]:
        """Redo stack, next-to-redo first."""
        return list(self._commands.history.redo_stack)

    # -- Operations -------------------------------------------------------------

    async def undo(self) -> None:
        """Undo the most recent command."""
        await self._commands.undo()
        self._notify()

    async def redo(self) -> None:
        """Redo the most recently undone command."""
        await self._commands.redo()
        self._notify()

    def clear(self) -> None:
        """Clear the entire command history."""
        self._commands.clear()
        self._notify()

    def refresh(self) -> None:
        """Force a revision bump (call on a poll timer)."""
        self._notify()
