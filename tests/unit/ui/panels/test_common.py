"""Tests for the shared panel-building helpers in ``common``.

``QtWidgets`` is imported at module scope, so the offscreen platform
plugin is installed before import to guarantee the import is safe on
headless CI.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from projectionai.ui.panels.common import make_section_header


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _action_buttons(header: QWidget) -> list[QToolButton]:
    return [
        child
        for child in header.findChildren(QToolButton)
        if child.objectName() == "sectionActionButton"
    ]


def test_header_without_action_has_no_action_button(qapp: QApplication) -> None:
    header = make_section_header("TITLE")
    assert not _action_buttons(header)


def test_header_default_action_stays_plus_sign(qapp: QApplication) -> None:
    header = make_section_header("TITLE", lambda: None)
    buttons = _action_buttons(header)
    assert len(buttons) == 1
    assert buttons[0].text() == "+"
    assert buttons[0].toolTip() == ""


def test_header_uses_supplied_action_text_and_tooltip(qapp: QApplication) -> None:
    header = make_section_header(
        "TITLE",
        lambda: None,
        action_text="Clear",
        action_tooltip="Clear the entire undo/redo history",
    )
    buttons = _action_buttons(header)
    assert len(buttons) == 1
    assert buttons[0].text() == "Clear"
    assert buttons[0].toolTip() == "Clear the entire undo/redo history"


def test_header_action_click_invokes_callback(qapp: QApplication) -> None:
    clicked: list[bool] = []

    def on_action() -> None:
        clicked.append(True)

    header = make_section_header("TITLE", on_action)
    buttons = _action_buttons(header)
    buttons[0].click()
    assert clicked == [True]
