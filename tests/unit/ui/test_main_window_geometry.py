"""Restored window geometry must land on an available screen."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from projectionai.ui.main_window import _fit_to_screen


def test_offscreen_geometry_is_pulled_onto_screen(qtbot: QtBot) -> None:
    avail = QGuiApplication.primaryScreen().availableGeometry()
    fitted = _fit_to_screen(
        QRect(avail.right() + 5000, avail.bottom() + 5000, 400, 300)
    )
    assert avail.contains(fitted)
    assert (fitted.width(), fitted.height()) == (400, 300)


def test_oversized_geometry_is_shrunk_to_screen(qtbot: QtBot) -> None:
    avail = QGuiApplication.primaryScreen().availableGeometry()
    fitted = _fit_to_screen(
        QRect(avail.left(), avail.top(), avail.width() * 3, avail.height() * 3)
    )
    assert avail.contains(fitted)
