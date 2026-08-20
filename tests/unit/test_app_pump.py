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
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from projectionai.app import _drive_qt_loop, _run_qt
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


def test_pump_destroys_deferred_delete_objects(qapp: QApplication) -> None:
    """Objects scheduled with deleteLater() must be destroyed by the pump.

    A manual ``processEvents()`` pump does not deliver ``DeferredDelete``
    events (they are only processed when control returns to an ``exec()``
    loop), so the pump must flush them explicitly with
    ``sendPostedEvents(None, QEvent.Type.DeferredDelete)``. Without that,
    dialogs/menus/panels scheduled via ``deleteLater()`` leak until
    process exit.
    """
    destroyed: list[bool] = []
    victim = QObject()
    victim.destroyed.connect(lambda *_: destroyed.append(True))
    victim.deleteLater()

    window = QMainWindow()
    window.show()
    QTimer.singleShot(200, window.close)

    asyncio.run(_drive_qt_loop(qapp, window))

    assert destroyed == [True]


class _FakeWindow:
    """MainWindow stand-in recording that show() was called."""

    def __init__(self, _app: object) -> None:
        self.shown = False

    def show(self) -> None:
        self.shown = True


class _FakeApp:
    """Application stand-in recording shutdown() calls."""

    def __init__(self) -> None:
        self.shutdown_calls = 0
        self.shutdown_error: Exception | None = None

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error


async def test_run_qt_shuts_down_when_drive_loop_fails(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing Qt loop must still release application resources."""
    app = _FakeApp()
    monkeypatch.setattr("projectionai.ui.main_window.MainWindow", _FakeWindow)

    async def _boom(_qapp: QApplication, _window: object) -> None:
        raise RuntimeError("loop boom")

    monkeypatch.setattr("projectionai.app._drive_qt_loop", _boom)

    with pytest.raises(RuntimeError, match="loop boom"):
        await _run_qt(app, qapp)

    assert app.shutdown_calls == 1


async def test_run_qt_cancellation_still_shuts_down(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation of the Qt loop must not skip application shutdown."""
    app = _FakeApp()
    monkeypatch.setattr("projectionai.ui.main_window.MainWindow", _FakeWindow)

    async def _cancel(_qapp: QApplication, _window: object) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("projectionai.app._drive_qt_loop", _cancel)

    with pytest.raises(asyncio.CancelledError):
        await _run_qt(app, qapp)

    assert app.shutdown_calls == 1


async def test_run_qt_shutdown_failure_returns_1(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shutdown failure alone must surface as exit code 1."""
    app = _FakeApp()
    app.shutdown_error = RuntimeError("shutdown boom")
    monkeypatch.setattr("projectionai.ui.main_window.MainWindow", _FakeWindow)

    async def _noop(_qapp: QApplication, _window: object) -> None:
        return None

    monkeypatch.setattr("projectionai.app._drive_qt_loop", _noop)

    code = await _run_qt(app, qapp)

    assert code == 1


async def test_run_qt_drive_error_wins_over_shutdown_failure(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The original Qt-loop error must not be masked by a shutdown failure."""
    app = _FakeApp()
    app.shutdown_error = RuntimeError("shutdown boom")
    monkeypatch.setattr("projectionai.ui.main_window.MainWindow", _FakeWindow)

    async def _boom(_qapp: QApplication, _window: object) -> None:
        raise RuntimeError("loop boom")

    monkeypatch.setattr("projectionai.app._drive_qt_loop", _boom)

    with pytest.raises(RuntimeError, match="loop boom"):
        await _run_qt(app, qapp)

    assert app.shutdown_calls == 1


async def test_run_qt_clean_exit_returns_0(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean pump exit shuts the application down and returns 0."""
    app = _FakeApp()
    monkeypatch.setattr("projectionai.ui.main_window.MainWindow", _FakeWindow)

    async def _noop(_qapp: QApplication, _window: object) -> None:
        return None

    monkeypatch.setattr("projectionai.app._drive_qt_loop", _noop)

    code = await _run_qt(app, qapp)

    assert code == 0
    assert app.shutdown_calls == 1
