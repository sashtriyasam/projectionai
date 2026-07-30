"""Command manager — undo/redo command history.

Wraps the domain ``CommandHistory`` and integrates with the event bus.
Supports command execution, undo, redo, grouping, and transactions.
"""

from __future__ import annotations

import logging
from typing import override

from projectionai.core.events import (
    CommandExecuted,
    CommandHistoryCleared,
    CommandRedone,
    CommandUndone,
    EventBus,
)
from projectionai.domain.command import Command, CommandHistory
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class CommandManager(Manager):
    """Manages the undo/redo command history for the application.

    Delegates to ``CommandHistory`` for the actual stack logic and
    emits events for every state change.
    """

    def __init__(self, event_bus: EventBus, max_depth: int = 256) -> None:
        super().__init__(event_bus)
        self._history: CommandHistory = CommandHistory(max_depth=max_depth)

    # -- Properties ---------------------------------------------------------

    @property
    def history(self) -> CommandHistory:
        """Return the underlying command history."""
        return self._history

    @property
    def can_undo(self) -> bool:
        """Return ``True`` if there is a command to undo."""
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        """Return ``True`` if there is a command to redo."""
        return self._history.can_redo

    @property
    def undo_depth(self) -> int:
        """Return the number of available undo steps."""
        return self._history.undo_depth

    @property
    def redo_depth(self) -> int:
        """Return the number of available redo steps."""
        return self._history.redo_depth

    @property
    def undo_text(self) -> str:
        """Return description of the next command to undo, if any."""
        return self._history.undo_text

    @property
    def redo_text(self) -> str:
        """Return description of the next command to redo, if any."""
        return self._history.redo_text

    # -- Transaction support -------------------------------------------------

    @property
    def in_transaction(self) -> bool:
        """Return ``True`` if a transaction is active."""
        return self._history.in_transaction

    def begin_transaction(self, name: str = "Transaction") -> None:
        """Begin a command transaction (grouped undo/redo)."""
        self._require_initialized()
        self._history.begin_transaction(name)

    def end_transaction(self) -> None:
        """Finalize the current transaction."""
        self._require_initialized()
        self._history.end_transaction()

    async def cancel_transaction(self) -> None:
        """Cancel the current transaction, undoing any executed commands."""
        self._require_initialized()
        commands = await self._history.cancel_transaction()
        if not commands:
            return
        for cmd in commands:
            _logger.debug("Transaction undone: %s", cmd.name)
            await self._event_bus.emit(
                CommandUndone(command_id=cmd.id, command_name=cmd.name)
            )

    # -- Operations ---------------------------------------------------------

    async def execute(self, command: Command) -> None:
        """Execute a command and push it onto the undo stack.

        Delegates to ``CommandHistory.execute()`` which handles
        transaction grouping and merge logic.

        Args:
            command: The command to execute.
        """
        self._require_initialized()
        _logger.debug("Executing command: %s", command.name)
        pushed = await self._history.execute(command)
        if pushed:
            await self._event_bus.emit(
                CommandExecuted(
                    command_id=command.id,
                    command_name=command.name,
                )
            )

    async def undo(self) -> None:
        """Undo the most recent command.

        Does nothing if the undo stack is empty.
        """
        self._require_initialized()
        if not self._history.can_undo:
            return
        command = await self._history.undo()
        if command is not None:
            _logger.debug("Undone: %s", command.name)
            await self._event_bus.emit(
                CommandUndone(
                    command_id=command.id,
                    command_name=command.name,
                )
            )

    async def redo(self) -> None:
        """Redo the most recently undone command.

        Does nothing if the redo stack is empty.
        """
        self._require_initialized()
        if not self._history.can_redo:
            return
        command = await self._history.redo()
        if command is not None:
            _logger.debug("Redone: %s", command.name)
            await self._event_bus.emit(
                CommandRedone(
                    command_id=command.id,
                    command_name=command.name,
                )
            )

    def clear(self) -> None:
        """Clear the entire command history."""
        self._require_initialized()
        self._history.clear()
        self._emit_nowait(CommandHistoryCleared())

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        _logger.debug(
            "CommandManager initialized (max_depth=%d)", self._history.max_depth
        )

    @override
    async def _on_shutdown(self) -> None:
        self._history.clear()
