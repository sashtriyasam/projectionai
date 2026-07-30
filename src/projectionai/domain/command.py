"""Command pattern implementation for undo/redo support.

Every user action that modifies the project should be implemented as a
``Command``. Commands can be executed, undone, and redone. Groups of
commands can be batched into transactions so the user undoes/redoes them
as a single action.

Design decisions:
- ``Command`` is an ABC — concrete commands override ``execute()`` and
  ``undo()``. ``redo()`` defaults to calling ``execute()``.
- The ``CommandHistory`` owns the undo/redo stacks.
- ``CommandGroup`` wraps multiple commands into one atomic unit.
- ``merge()`` allows consecutive commands of the same type to be
  coalesced (e.g., a series of slider drags becomes one "move" action).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, override
from uuid import uuid4


class Command(ABC):
    """Abstract base for all undoable commands.

    Usage::

        class MoveNodeCommand(Command):
            def __init__(self, node_id: str, old_pos, new_pos) -> None:
                super().__init__(name="Move Node")
                self._node_id = node_id
                self._old_pos = old_pos
                self._new_pos = new_pos

            async def execute(self) -> None:
                scene.set_position(self._node_id, self._new_pos)

            async def undo(self) -> None:
                scene.set_position(self._node_id, self._old_pos)
    """

    def __init__(
        self,
        name: str = "Command",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._id: str = uuid4().hex
        self._name: str = name
        self._timestamp: datetime = datetime.now(UTC)
        self._metadata: dict[str, Any] = metadata or {}
        self._executed: bool = False

    # -- Properties ---------------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    @property
    def is_executed(self) -> bool:
        return self._executed

    # -- Abstract methods ---------------------------------------------------

    @abstractmethod
    async def execute(self) -> None:
        """Perform the command action.

        Called the first time the command runs.
        Raises ``CommandError`` on failure.
        """

    @abstractmethod
    async def undo(self) -> None:
        """Reverse the command action.

        Raises ``CommandError`` on failure.
        """

    async def redo(self) -> None:
        """Re-perform after an undo. Defaults to calling ``execute()``."""
        await self.execute()

    # -- Optional merging ---------------------------------------------------

    def merge(self, _other: Command) -> Command | None:
        """Try to merge *other* into this command.

        Returns the merged command (usually ``self``) or ``None`` if
        merge is not possible.
        """
        return None

    # -- Internal -----------------------------------------------------------

    def mark_executed(self) -> None:
        self._executed = True


# ---------------------------------------------------------------------------
# Command group — multiple commands as one unit
# ---------------------------------------------------------------------------


class CommandGroup(Command):
    """A group of commands that are undone/redone as one unit.

    Used for transactions::

        async with command_manager.transaction("Create Object"):
            command_manager.execute(AddNodeCommand(...))
            command_manager.execute(SetTransformCommand(...))
    """

    def __init__(self, name: str = "Group") -> None:
        super().__init__(name=name)
        self._commands: list[Command] = []

    @property
    def commands(self) -> list[Command]:
        return list(self._commands)

    def add(self, command: Command) -> None:
        """Add a command to this group."""
        self._commands.append(command)

    @property
    def is_empty(self) -> bool:
        return len(self._commands) == 0

    @override
    async def execute(self) -> None:
        for cmd in self._commands:
            await cmd.execute()
            cmd.mark_executed()

    @override
    async def undo(self) -> None:
        for cmd in reversed(self._commands):
            await cmd.undo()

    @override
    async def redo(self) -> None:
        for cmd in self._commands:
            await cmd.redo()
            cmd.mark_executed()


# ---------------------------------------------------------------------------
# Command error
# ---------------------------------------------------------------------------


class CommandError(RuntimeError):
    """Raised when a command operation fails."""


# ---------------------------------------------------------------------------
# Command history (undo/redo stack)
# ---------------------------------------------------------------------------


@dataclass
class CommandHistoryState:
    """Observable state of the command history."""

    undo_count: int = 0
    redo_count: int = 0
    undo_description: str = ""
    redo_description: str = ""


class CommandHistory:
    """The undo/redo stack.

    Thread-safe for the event-loop thread. Not safe for concurrent access
    from multiple threads.

    Usage::

        history = CommandHistory(max_depth=256)
        await history.execute(MyCommand())
        await history.undo()  # reverses the last command
        await history.redo()  # re-applies it
    """

    def __init__(self, max_depth: int = 256) -> None:
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._max_depth: int = max_depth
        self._active_group: CommandGroup | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def undo_text(self) -> str:
        if not self._undo_stack:
            return ""
        return self._undo_stack[-1].name

    @property
    def redo_text(self) -> str:
        if not self._redo_stack:
            return ""
        return self._redo_stack[-1].name

    @property
    def undo_depth(self) -> int:
        return len(self._undo_stack)

    @property
    def redo_depth(self) -> int:
        return len(self._redo_stack)

    def get_state(self) -> CommandHistoryState:
        """Return a snapshot of the current history state (for UI binding)."""
        return CommandHistoryState(
            undo_count=self.undo_depth,
            redo_count=self.redo_depth,
            undo_description=self.undo_text,
            redo_description=self.redo_text,
        )

    # -- Transaction support ------------------------------------------------

    @property
    def max_depth(self) -> int:
        """Return maximum history depth."""
        return self._max_depth

    @property
    def in_transaction(self) -> bool:
        """Return ``True`` if a transaction is active."""
        return self._active_group is not None

    def begin_transaction(self, name: str = "Transaction") -> None:
        """Begin grouping subsequent commands into one unit.

        Must be paired with ``end_transaction()`` or
        ``cancel_transaction()``.
        """
        if self._active_group is not None:
            raise CommandError("Already in a transaction")
        self._active_group = CommandGroup(name=name)

    def end_transaction(self) -> None:
        """Finalize the current transaction and push it onto the stack."""
        if self._active_group is None:
            raise CommandError("Not in a transaction")
        group = self._active_group
        self._active_group = None
        if not group.is_empty:
            self._push(group)

    async def cancel_transaction(self) -> list[Command]:
        """Cancel the current transaction without pushing anything.

        Commands that were executed immediately via ``execute()`` during the
        transaction are undone in reverse order before clearing the group.

        Returns:
            The list of commands that were undone.
        """
        if self._active_group is None:
            raise CommandError("Not in a transaction")
        group = self._active_group
        self._active_group = None
        undone: list[Command] = []
        for cmd in reversed(group.commands):
            await cmd.undo()
            undone.append(cmd)
        return undone

    # -- Core operations ----------------------------------------------------

    async def execute(self, command: Command) -> bool:
        """Execute a command and push it onto the undo stack.

        If a transaction is active, the command is added to the group
        instead of the main stack.

        Returns:
            ``True`` if a distinct entry was pushed to the undo stack;
            ``False`` if the command was merged into an existing entry
            or buffered in an open transaction.
        """
        if self._active_group is not None:
            # Execute first; only add to the group on success so
            # cancel_transaction never tries to undo a failed command.
            await command.execute()
            command.mark_executed()
            self._active_group.add(command)
            return False

        # Execute the command first so its side effect is always applied,
        # regardless of whether ``merge()`` handles side effects inline.
        await command.execute()
        command.mark_executed()

        # Try to merge with the last command (undo-history compaction only)
        if self._undo_stack:
            last = self._undo_stack[-1]
            merged = last.merge(command)
            if merged is not None:
                self._undo_stack[-1] = merged
                self._redo_stack.clear()
                return False

        self._push(command)
        return True

    async def undo(self) -> Command | None:
        """Undo the last command.

        Returns the undone command, or ``None`` if nothing to undo.
        """
        if not self._undo_stack:
            return None
        command = self._undo_stack.pop()
        try:
            await command.undo()
        except Exception:
            raise
        self._redo_stack.append(command)
        return command

    async def redo(self) -> Command | None:
        """Redo the last undone command.

        Returns the redone command, or ``None`` if nothing to redo.
        """
        if not self._redo_stack:
            return None
        command = self._redo_stack.pop()
        try:
            await command.redo()
        except Exception:
            raise
        self._undo_stack.append(command)
        return command

    def clear(self) -> None:
        """Clear the entire history (e.g., when a new project is opened)."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._active_group = None

    # -- Internal -----------------------------------------------------------

    def _push(self, command: Command) -> None:
        self._undo_stack.append(command)
        self._redo_stack.clear()
        if len(self._undo_stack) > self._max_depth:
            _ = self._undo_stack.pop(0)
