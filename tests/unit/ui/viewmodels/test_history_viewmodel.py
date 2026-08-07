"""Tests for HistoryViewModel stack listing and the CommandHistory
accessors it relies on.

``HistoryViewModel`` is Qt-free, so no QApplication is required; the
command manager is duck-typed with a real ``CommandHistory`` underneath.
"""

from __future__ import annotations

from typing import cast

from projectionai.domain.command import Command, CommandHistory
from projectionai.managers.command_manager import CommandManager
from projectionai.ui.viewmodels.history import HistoryViewModel


class _RecordedCommand(Command):
    """No-op command that records whether it ran."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.executed = 0
        self.undone = 0

    async def execute(self) -> None:
        self.executed += 1

    async def undo(self) -> None:
        self.undone += 1


class _FakeManager:
    """Duck-typed CommandManager: only ``.history`` is needed to list."""

    def __init__(self, history: CommandHistory) -> None:
        self.history = history


def _vm(history: CommandHistory) -> HistoryViewModel:
    return HistoryViewModel(cast(CommandManager, _FakeManager(history)))


async def test_undo_stack_returns_oldest_first_tuple() -> None:
    history = CommandHistory()
    c1, c2, c3 = _RecordedCommand("c1"), _RecordedCommand("c2"), _RecordedCommand("c3")
    await history.execute(c1)
    await history.execute(c2)
    await history.execute(c3)

    assert history.undo_stack == (c1, c2, c3)
    assert isinstance(history.undo_stack, tuple)


async def test_redo_stack_returns_oldest_first_tuple() -> None:
    history = CommandHistory()
    c1, c2, c3 = _RecordedCommand("c1"), _RecordedCommand("c2"), _RecordedCommand("c3")
    await history.execute(c1)
    await history.execute(c2)
    await history.execute(c3)
    await history.undo()
    await history.undo()

    assert history.redo_stack == (c2, c3)
    assert history.undo_stack == (c1,)


async def test_accessors_return_snapshot_not_live_view() -> None:
    history = CommandHistory()
    c1, c2 = _RecordedCommand("c1"), _RecordedCommand("c2")
    await history.execute(c1)
    await history.execute(c2)
    snapshot = history.undo_stack

    await history.execute(_RecordedCommand("c3"))

    assert snapshot == (c1, c2)
    assert len(history.undo_stack) == 3


async def test_undo_entries_most_recent_first() -> None:
    history = CommandHistory()
    await history.execute(_RecordedCommand("c1"))
    await history.execute(_RecordedCommand("c2"))
    await history.execute(_RecordedCommand("c3"))

    assert [c.name for c in _vm(history).undo_entries()] == ["c3", "c2", "c1"]


async def test_redo_entries_next_to_redo_first() -> None:
    history = CommandHistory()
    await history.execute(_RecordedCommand("c1"))
    await history.execute(_RecordedCommand("c2"))
    await history.execute(_RecordedCommand("c3"))
    await history.undo()
    await history.undo()

    vm = _vm(history)
    assert [c.name for c in vm.undo_entries()] == ["c1"]
    assert [c.name for c in vm.redo_entries()] == ["c2", "c3"]
