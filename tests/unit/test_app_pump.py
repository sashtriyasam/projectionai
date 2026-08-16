"""Regression tests for the cooperative Qt+asyncio event-loop pump.

The app previously blocked inside ``qapp.exec()``, which starved every
asyncio task scheduled from Qt callbacks via ``run_async``: the loop
never regained control, so fire-and-forget view-model work (camera
refresh, open/close, preview) silently never ran. ``app._drive_qt_loop``
pumps Qt events and yields to asyncio instead; these tests pin that
behaviour so a blocking ``exec()`` cannot be reintroduced.

Note on exit detection: ``exec()``-only quit signals (``closingDown()``,
``aboutToQuit``, ``lastWindowClosed``) are never emitted by a manual
``processEvents`` pump, so the pump watches the main window's visibility
instead — the app quits exactly when ``MainWindow.close()`` runs.

``QtWidgets``-adjacent modules are imported after the offscreen platform
plugin is installed to guarantee imports are safe on headless CI.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from projectionai.app import _drive_qt_loop
from projectionai.ui.widgets.panel_base import run_async


@pytest.fixture
def qapp() -> QApplication:
    """A shared offscreen QApplication instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_pump_runs_tasks_scheduled_from_qt_callbacks(qapp: QApplication) -> None:
    """run_async work scheduled from a Qt callback must execute while the
    cooperative pump drives both loops."""
    ran: list[bool] = []

    async def worker() -> None:
        ran.append(True)

    def schedule() -> None:
        run_async(worker())

    window = QMainWindow()
    window.show()
    # Fire from the Qt event loop, exactly like a button click.
    QTimer.singleShot(0, schedule)
    # Close the window after the pump has had time to run the task.
    QTimer.singleShot(200, window.close)

    asyncio.run(_drive_qt_loop(qapp, window))

    assert ran == [True]
    assert not window.isVisible()


def test_pump_exits_when_main_window_closes(qapp: QApplication) -> None:
    """The pump must return once the main window is closed."""
    window = QMainWindow()
    window.show()
    QTimer.singleShot(0, window.close)

    asyncio.run(_drive_qt_loop(qapp, window))

    assert not window.isVisible()
