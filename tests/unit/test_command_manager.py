"""Tests for CommandManager."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from projectionai.core.events import (
    CommandExecuted,
    CommandHistoryCleared,
    CommandRedone,
    CommandUndone,
)
from projectionai.domain.command import Command, CommandError
from projectionai.managers.command_manager import CommandManager

pytestmark = pytest.mark.asyncio


class _SetValueCommand(Command):
    """A simple test command that mutates a dict."""

    def __init__(
        self,
        target: dict[str, Any],
        key: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        super().__init__(name=f"Set {key}")
        self._target = target
        self._key = key
        self._old = old_value
        self._new = new_value

    async def execute(self) -> None:
        self._target[self._key] = self._new

    async def undo(self) -> None:
        self._target[self._key] = self._old


class _MergeableCommand(Command):
    """A command that merges consecutive updates to the same key."""

    def __init__(self, target: dict[str, Any], key: str, value: Any) -> None:
        super().__init__(name=f"Merge {key}")
        self._target = target
        self._key = key
        self._value = value

    async def execute(self) -> None:
        self._target[self._key] = self._value

    async def undo(self) -> None:
        del self._target[self._key]

    def merge(self, other: Command) -> Command | None:
        if not isinstance(other, _MergeableCommand):
            return None
        if self._key != other._key:
            return None
        self._value = other._value
        self._target[self._key] = self._value
        return self


@pytest.fixture
async def manager(event_bus) -> CommandManager:
    m = CommandManager(event_bus)
    await m.initialize()
    return m


@pytest.fixture
def state() -> dict[str, Any]:
    return {"x": 0}


class TestCommandManagerBasics:
    """Core execute/undo/redo operations."""

    async def test_initial_state(self, manager: CommandManager) -> None:
        assert not manager.can_undo
        assert not manager.can_redo
        assert manager.undo_depth == 0
        assert manager.redo_depth == 0

    async def test_execute(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        cmd = _SetValueCommand(state, "x", 0, 42)
        await manager.execute(cmd)

        assert state["x"] == 42
        assert manager.can_undo
        assert not manager.can_redo

    async def test_execute_emits_event(
        self, manager: CommandManager, state: dict[str, Any], event_bus
    ) -> None:
        cmd = _SetValueCommand(state, "x", 0, 99)
        await manager.execute(cmd)

        event_bus.assert_event_emitted(CommandExecuted)

    async def test_undo(self, manager: CommandManager, state: dict[str, Any]) -> None:
        cmd = _SetValueCommand(state, "x", 0, 10)
        await manager.execute(cmd)

        await manager.undo()
        assert state["x"] == 0
        assert manager.can_redo
        assert not manager.can_undo

    async def test_undo_emits_event(
        self, manager: CommandManager, state: dict[str, Any], event_bus
    ) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.undo()

        event_bus.assert_event_emitted(CommandUndone)

    async def test_redo(self, manager: CommandManager, state: dict[str, Any]) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 5))
        await manager.undo()
        await manager.redo()

        assert state["x"] == 5

    async def test_redo_emits_event(
        self, manager: CommandManager, state: dict[str, Any], event_bus
    ) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 7))
        await manager.undo()
        await manager.redo()

        event_bus.assert_event_emitted(CommandRedone)

    async def test_undo_empty(self, manager: CommandManager) -> None:
        await manager.undo()  # should not raise

    async def test_redo_empty(self, manager: CommandManager) -> None:
        await manager.redo()  # should not raise


class TestCommandManagerUndoRedoStack:
    """Stack behavior: execute clears redo, depth tracking."""

    async def test_execute_clears_redo(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.undo()
        await manager.execute(_SetValueCommand(state, "x", 1, 2))

        assert not manager.can_redo

    async def test_multi_step_undo_redo(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.execute(_SetValueCommand(state, "x", 1, 2))
        await manager.execute(_SetValueCommand(state, "x", 2, 3))

        await manager.undo()
        assert state["x"] == 2
        await manager.undo()
        assert state["x"] == 1
        await manager.undo()
        assert state["x"] == 0
        assert not manager.can_undo

        await manager.redo()
        assert state["x"] == 1
        await manager.redo()
        assert state["x"] == 2
        await manager.redo()
        assert state["x"] == 3

    async def test_undo_text(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        assert manager.undo_text == ""
        assert manager.redo_text == ""

        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        assert "Set x" in manager.undo_text

        await manager.undo()
        assert "Set x" in manager.redo_text


class TestCommandManagerClear:
    """Clearing the command history."""

    async def test_clear(self, manager: CommandManager, state: dict[str, Any]) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.execute(_SetValueCommand(state, "x", 1, 2))
        manager.clear()

        assert not manager.can_undo
        assert not manager.can_redo

    async def test_clear_emits_event(
        self, manager: CommandManager, state: dict[str, Any], event_bus
    ) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        manager.clear()
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(CommandHistoryCleared)


class TestCommandManagerMerge:
    """Command merge support."""

    async def test_merge_consecutive(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        await manager.execute(_MergeableCommand(state, "x", 10))
        await manager.execute(_MergeableCommand(state, "x", 20))
        await manager.execute(_MergeableCommand(state, "x", 30))

        assert manager.undo_depth == 1  # all merged into one
        assert state["x"] == 30

        await manager.undo()
        assert "x" not in state

    async def test_merge_skipped_for_different_types(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.execute(_SetValueCommand(state, "x", 1, 2))

        assert manager.undo_depth == 2  # not merged (different type)


class TestCommandManagerStackNotifications:
    """Subscribers are notified on every undo/redo stack change."""

    async def test_merge_notifies_stack_change(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        notified: list[int] = []
        manager.subscribe(lambda: notified.append(1))

        await manager.execute(_MergeableCommand(state, "x", 10))
        await manager.execute(_MergeableCommand(state, "x", 20))  # merges

        assert len(notified) == 2  # push and merge both change the stack

    async def test_transaction_end_notifies_stack_change(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        notified: list[int] = []
        manager.subscribe(lambda: notified.append(1))

        manager.begin_transaction("Group")
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.execute(_SetValueCommand(state, "y", 0, 2))
        assert len(notified) == 0  # buffered: nothing on the stack yet

        manager.end_transaction()  # commits the group

        assert len(notified) == 1

    async def test_empty_transaction_end_does_not_notify(
        self, manager: CommandManager
    ) -> None:
        notified: list[int] = []
        manager.subscribe(lambda: notified.append(1))

        manager.begin_transaction("Empty")
        manager.end_transaction()

        assert len(notified) == 0  # nothing committed

    async def test_transaction_at_max_depth_notifies_stack_change(
        self, event_bus, state: dict[str, Any]
    ) -> None:
        m = CommandManager(event_bus, max_depth=1)
        await m.initialize()

        notified: list[int] = []
        m.subscribe(lambda: notified.append(1))

        await m.execute(_SetValueCommand(state, "x", 0, 1))  # stack full
        m.begin_transaction("Group")
        await m.execute(_SetValueCommand(state, "y", 0, 2))
        assert len(notified) == 1  # buffered: no stack change yet

        m.end_transaction()  # commits the group; the oldest entry is evicted

        # undo_depth stays at 1, but the stack content changed (and redo was
        # cleared), so subscribers must still be notified.
        assert len(notified) == 2
        assert m.undo_depth == 1


class TestCommandManagerTransactions:
    """Transaction (grouped commands) support."""

    async def test_transaction_group(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        manager.begin_transaction("Group")
        await manager.execute(_SetValueCommand(state, "x", 0, 1))
        await manager.execute(_SetValueCommand(state, "y", 0, 2))
        manager.end_transaction()

        assert state["x"] == 1
        assert state["y"] == 2
        assert manager.undo_depth == 1  # grouped as one

        await manager.undo()
        assert state.get("x") == 0
        assert state.get("y") == 0

    async def test_cancel_transaction(
        self, manager: CommandManager, state: dict[str, Any]
    ) -> None:
        manager.begin_transaction("Cancel")
        await manager.execute(_SetValueCommand(state, "x", 0, 100))
        await manager.cancel_transaction()

        # Commands undone and nothing pushed to undo stack
        assert state["x"] == 0
        assert manager.undo_depth == 0

    async def test_empty_transaction(self, manager: CommandManager) -> None:
        manager.begin_transaction("Empty")
        manager.end_transaction()
        assert manager.undo_depth == 0  # empty group not pushed

    async def test_double_begin_raises(self, manager: CommandManager) -> None:
        manager.begin_transaction("A")
        with pytest.raises(CommandError, match="Already in a transaction"):
            manager.begin_transaction("B")

    async def test_end_without_begin_raises(self, manager: CommandManager) -> None:
        with pytest.raises(CommandError, match="Not in a transaction"):
            manager.end_transaction()
