"""Command palette — fuzzy action-search overlay (Ctrl+Shift+F).

Searches the shared action registry and executes the selected action.
Matching is a simple subsequence score: prefix matches rank highest,
then consecutive-character runs, then scattered matches.
"""

from __future__ import annotations

from typing import override

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


def score_action(query: str, candidate: str) -> int:
    """Rank *candidate* text against *query* (higher is better, 0 = no match).

    Case-insensitive. Prefix matches dominate; otherwise every query
    character must appear in order, with bonuses for consecutive runs.
    """
    query = query.casefold()
    candidate = candidate.casefold()
    if not query:
        return 0
    if candidate.startswith(query):
        return 1000 - len(candidate)
    score = 0
    streak = 0
    cursor = 0
    for char in query:
        index = candidate.find(char, cursor)
        if index == -1:
            return 0
        if index == cursor:
            streak += 1
            score += 10 + streak
        else:
            streak = 1
            score += 10
        cursor = index + 1
    return score


def _label(action: QAction) -> str:
    """Display text without accelerator ampersands or key-suffix tabs."""
    return action.text().replace("&", "").split("\t", 1)[0].strip()


class CommandPaletteDialog(QDialog):
    """Modal-less search overlay over a flat list of actions."""

    def __init__(self, actions: list[QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions = actions
        self.setWindowTitle("Command Palette")
        self.setModal(False)
        self.resize(520, 360)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("Type a command...")
        self._list = QListWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._edit)
        layout.addWidget(self._list)

        self._edit.textChanged.connect(self._refilter)
        self._list.itemActivated.connect(self._activate)
        self._list.itemClicked.connect(self._activate)

        self._populate("")
        self._edit.setFocus()

    # -- Internals ----------------------------------------------------------

    def _populate(self, query: str) -> None:
        self._list.clear()
        scored: list[tuple[int, QAction]] = []
        for action in self._actions:
            if not action.isEnabled():
                continue
            text = _label(action)
            rank = 1 if not query else score_action(query, text)
            if rank > 0:
                scored.append((rank, action))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        for _, action in scored[:20]:
            item = QListWidgetItem(_label(action))
            key = action.shortcut().toString()
            if key:
                item.setToolTip(f"Shortcut: {key}")
            item.setData(Qt.ItemDataRole.UserRole, action)
            self._list.addItem(item)
        self._list.setCurrentRow(0)

    def _refilter(self, query: str) -> None:
        self._populate(query)

    def _activate(self, item: QListWidgetItem) -> None:
        action = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(action, QAction):
            self.accept()
            action.trigger()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Down:
            self._list.setFocus()
            self._list.setCurrentRow(
                min(self._list.currentRow() + 1, self._list.count() - 1)
            )
            event.accept()
            return
        if event.key() == Qt.Key.Key_Up:
            self._list.setFocus()
            self._list.setCurrentRow(max(self._list.currentRow() - 1, 0))
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self._list.currentItem()
            if item is not None:
                self._activate(item)
                return
        super().keyPressEvent(event)
