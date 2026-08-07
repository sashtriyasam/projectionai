"""Regression tests for HistoryPanel._clear confirmation.

Clearing the undo/redo history is destructive, so ``_clear`` must ask
for confirmation and only forward to the view model when the user
accepts. ``QMessageBox.question`` is patched so no modal dialog blocks
the offscreen test run.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.panels.history_panel import HistoryPanel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeViewModel:
    """Duck-typed stand-in for HistoryViewModel (bind_viewmodel accepts Any)."""

    def __init__(self) -> None:
        self.clear_calls = 0

    @property
    def can_undo(self) -> bool:
        return False

    @property
    def can_redo(self) -> bool:
        return False

    @property
    def redo_depth(self) -> int:
        return 0

    def subscribe(self, handler: Any) -> None:
        """No-op: this test only exercises the clear path."""

    def unsubscribe(self, handler: Any) -> None:
        """No-op."""

    def undo_entries(self) -> list[Any]:
        return []

    def redo_entries(self) -> list[Any]:
        return []

    def clear(self) -> None:
        self.clear_calls += 1


def _answer(
    button: QMessageBox.StandardButton,
) -> Callable[..., QMessageBox.StandardButton]:
    """Return a stand-in for QMessageBox.question answering *button*."""

    def question(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
        return button

    return question


class TestClearConfirmation:
    def test_clears_history_when_confirmed(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        panel = HistoryPanel()
        vm = _FakeViewModel()
        panel.bind_viewmodel(vm)
        monkeypatch.setattr(
            "projectionai.ui.panels.history_panel.QMessageBox.question",
            _answer(QMessageBox.StandardButton.Yes),
        )
        panel._clear()
        assert vm.clear_calls == 1

    def test_keeps_history_when_declined(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        panel = HistoryPanel()
        vm = _FakeViewModel()
        panel.bind_viewmodel(vm)
        monkeypatch.setattr(
            "projectionai.ui.panels.history_panel.QMessageBox.question",
            _answer(QMessageBox.StandardButton.No),
        )
        panel._clear()
        assert vm.clear_calls == 0

    def test_unbound_panel_does_not_prompt(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        panel = HistoryPanel()
        calls: list[tuple[Any, ...]] = []
        monkeypatch.setattr(
            "projectionai.ui.panels.history_panel.QMessageBox.question",
            lambda *args: calls.append(args) or QMessageBox.StandardButton.Yes,
        )
        panel._clear()
        assert calls == []
