"""HistoryPanel — branching undo/redo history (left dock).

Blender-style branching list: the undo stack is rendered top-of-stack
first, then a separator, then the redo stack (next-to-redo first).
Undo/redo operations are async on the manager, so they run through
``run_async`` and the panel re-renders on the resulting notification.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from projectionai.domain.command import Command
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import ACCENT, TEXT_DIM, TEXT_FAINT
from projectionai.ui.widgets.panel_base import run_async


class HistoryPanel(ViewModelPanel):
    """History dock panel: branching undo/redo stack."""

    panel_id = "history"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header ---------------------------------------------------------------
        root.addWidget(
            make_section_header(
                "HISTORY",
                self._clear,
                action_text="Clear",
                action_tooltip="Clear the entire undo/redo history",
            )
        )

        # -- History list ----------------------------------------------------------
        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        root.addWidget(self.history_list, stretch=1)

        # -- Action row -------------------------------------------------------------
        actions = QHBoxLayout()
        actions.setContentsMargins(4, 4, 4, 4)
        actions.setSpacing(4)
        self.undo_btn = make_action_button("Undo", self._undo)
        self.redo_btn = make_action_button("Redo", self._redo)
        actions.addWidget(self.undo_btn)
        actions.addWidget(self.redo_btn)
        actions.addStretch(1)
        actions.addWidget(make_action_button("Clear", self._clear))
        root.addLayout(actions)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the branching list from the view model."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            vm = self._viewmodel
            self.history_list.clear()
            if vm is None:
                self.undo_btn.setEnabled(False)
                self.redo_btn.setEnabled(False)
                return
            self.undo_btn.setEnabled(vm.can_undo)
            self.redo_btn.setEnabled(vm.can_redo)

            for command in vm.undo_entries():
                self.history_list.addItem(self._command_item(command, undo=True))
            if vm.redo_depth:
                separator = QListWidgetItem("── redo ──")
                separator.setForeground(QColor(TEXT_FAINT))
                self.history_list.addItem(separator)
                for command in vm.redo_entries():
                    self.history_list.addItem(self._command_item(command, undo=False))
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty the history list."""
        self.history_list.clear()

    # -- Item builder ------------------------------------------------------------

    @staticmethod
    def _command_item(command: Command, undo: bool) -> QListWidgetItem:
        label = f"{command.name}  ·  {command.timestamp.strftime('%H:%M:%S')}"
        if undo:
            label = "↺ " + label
        item = QListWidgetItem(label)
        item.setForeground(QColor(ACCENT if undo else TEXT_DIM))
        return item

    # -- Interactions ---------------------------------------------------------------

    def _undo(self) -> None:
        if self._viewmodel is not None:
            run_async(self._viewmodel.undo())

    def _redo(self) -> None:
        if self._viewmodel is not None:
            run_async(self._viewmodel.redo())

    def _clear(self) -> None:
        if self._viewmodel is None:
            return
        result = QMessageBox.question(
            self,
            "Clear History",
            "Clear the entire undo/redo history?",
        )
        if result == QMessageBox.StandardButton.Yes:
            self._viewmodel.clear()
