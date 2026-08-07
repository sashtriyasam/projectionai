"""Shared panel-building helpers: section headers and action buttons.

Every dock panel is a stack of collapsible-looking sections. A section
header is a full-width ``QToolButton#sectionHeader`` (title) with an
optional trailing action button, wrapped in a plain container so the
header's QSS bottom-border renders correctly.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

_Callback = Callable[[], None]


def make_section_header(
    title: str,
    action: _Callback | None = None,
    action_text: str = "+",
    action_tooltip: str | None = None,
) -> QWidget:
    """Return a section header row: title + optional trailing action."""
    container = QWidget()
    container.setObjectName("sectionContainer")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    title_btn = QToolButton()
    title_btn.setObjectName("sectionHeader")
    title_btn.setText(title)
    title_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    layout.addWidget(title_btn, stretch=1)
    if action is not None:
        action_btn = QToolButton()
        action_btn.setObjectName("sectionActionButton")
        action_btn.setText(action_text)
        if action_tooltip is not None:
            action_btn.setToolTip(action_tooltip)
        action_btn.clicked.connect(action)
        layout.addWidget(action_btn)
    return container


def make_action_button(text: str, callback: _Callback | None = None) -> QToolButton:
    """Return a compact section action button."""
    button = QToolButton()
    button.setObjectName("sectionActionButton")
    button.setText(text)
    if callback is not None:
        button.clicked.connect(callback)
    return button
