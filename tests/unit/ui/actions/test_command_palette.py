"""Regression tests for CommandPaletteDialog keyboard navigation.

Down/Up navigation must clamp on the first/last list rows instead of
driving ``setCurrentRow`` out of range, which invalidates the current
item and leaves Enter unable to activate the boundary selection.
Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.actions.command_palette import CommandPaletteDialog

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


def _key(key: Qt.Key) -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


class _SpyAction(QAction):
    """QAction that records direct ``trigger()`` invocations."""

    def __init__(self, name: str, parent: QApplication) -> None:
        super().__init__(parent)
        self.setText(f"Test {name}")
        self.calls = 0

    def trigger(self) -> None:
        self.calls += 1
        super().trigger()


def _dialog(
    qapp: QApplication,
) -> tuple[CommandPaletteDialog, list[_SpyAction]]:
    """A three-action palette with a trigger spy on each action."""
    actions = [_SpyAction(f"Action {i}", qapp) for i in range(3)]
    return CommandPaletteDialog(actions), actions


class TestKeyboardNavigation:
    def test_down_clamps_at_last_row(self, qapp: QApplication) -> None:
        dialog, _ = _dialog(qapp)
        dialog.keyPressEvent(_key(Qt.Key.Key_Down))
        dialog.keyPressEvent(_key(Qt.Key.Key_Down))
        assert dialog._list.currentRow() == 2
        dialog.keyPressEvent(_key(Qt.Key.Key_Down))
        assert dialog._list.currentRow() == 2
        assert dialog._list.currentItem() is not None
        dialog.close()

    def test_up_clamps_at_first_row(self, qapp: QApplication) -> None:
        dialog, _ = _dialog(qapp)
        dialog.keyPressEvent(_key(Qt.Key.Key_Up))
        assert dialog._list.currentRow() == 0
        assert dialog._list.currentItem() is not None
        dialog.close()

    def test_enter_activates_selected_item_at_bottom_edge(
        self, qapp: QApplication
    ) -> None:
        dialog, actions = _dialog(qapp)
        dialog.keyPressEvent(_key(Qt.Key.Key_Down))
        dialog.keyPressEvent(_key(Qt.Key.Key_Down))
        dialog.keyPressEvent(_key(Qt.Key.Key_Down))
        dialog.keyPressEvent(_key(Qt.Key.Key_Return))
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert actions[2].calls == 1
        dialog.close()

    def test_enter_activates_selected_item_at_top_edge(
        self, qapp: QApplication
    ) -> None:
        dialog, actions = _dialog(qapp)
        dialog.keyPressEvent(_key(Qt.Key.Key_Up))
        dialog.keyPressEvent(_key(Qt.Key.Key_Return))
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert actions[0].calls == 1
        dialog.close()
