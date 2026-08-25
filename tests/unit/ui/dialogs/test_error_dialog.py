"""Tests for fatal-error reporting: exception hooks and ErrorDialog.

The hooks install process-wide handlers, so every test restores the
original ``sys.excepthook`` / ``threading.excepthook`` / Qt message
handler afterwards — a failing test must not poison the rest of the
suite. ``_report_fatal`` is monkeypatched wherever a report would be
triggered (it shows a modal dialog and terminates the process).
Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Generator
from pathlib import Path

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QPushButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import projectionai.ui.dialogs.error_dialog as error_dialog

# qapp provided by pytest-qt (function-scoped) - custom module fixture removed to avoid leak


def _noop_qt_handler(_msg_type: object, _context: object, _message: str) -> None:
    """Discard Qt messages; used to capture the previous handler."""


class TestInstallExceptionHooks:
    def test_install_sets_all_hooks_and_is_idempotent(self, qapp: QApplication) -> None:
        previous_qt = qInstallMessageHandler(_noop_qt_handler)
        previous_sys = sys.excepthook
        previous_thread = threading.excepthook
        try:
            error_dialog.install_exception_hooks()
            assert sys.excepthook is error_dialog._handle_sys_exception
            assert threading.excepthook is error_dialog._handle_thread_exception

            error_dialog.install_exception_hooks()
            assert sys.excepthook is error_dialog._handle_sys_exception
        finally:
            qInstallMessageHandler(previous_qt)
            sys.excepthook = previous_sys
            threading.excepthook = previous_thread
            error_dialog._hooks_installed = False


class TestSysException:
    def test_main_thread_reports(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reports: list[tuple[str, str]] = []
        monkeypatch.setattr(
            error_dialog,
            "_report_fatal",
            lambda message, details: reports.append((message, details)),
        )
        error_dialog._handle_sys_exception(ValueError, ValueError("boom"), None)
        assert len(reports) == 1
        assert "boom" in reports[0][0]
        assert "ValueError" in reports[0][1]

    def test_background_thread_logs_only(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        reports: list[tuple[str, str]] = []
        monkeypatch.setattr(
            error_dialog,
            "_report_fatal",
            lambda message, details: reports.append((message, details)),
        )
        monkeypatch.setattr(error_dialog, "_should_report", lambda: False)
        error_dialog._handle_sys_exception(ValueError, ValueError("boom"), None)
        assert reports == []
        assert "Unhandled exception" in caplog.text


class TestThreadException:
    def test_logs_only(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        reports: list[tuple[str, str]] = []
        monkeypatch.setattr(
            error_dialog,
            "_report_fatal",
            lambda message, details: reports.append((message, details)),
        )
        args = threading.ExceptHookArgs((ValueError, ValueError("boom"), None, None))
        error_dialog._handle_thread_exception(args)
        assert reports == []
        assert "Unhandled exception" in caplog.text

    def test_missing_value_logs(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        reports: list[tuple[str, str]] = []
        monkeypatch.setattr(
            error_dialog,
            "_report_fatal",
            lambda message, details: reports.append((message, details)),
        )
        args = threading.ExceptHookArgs((None, None, None, None))
        error_dialog._handle_thread_exception(args)
        assert reports == []
        assert "no exception value" in caplog.text


class TestQtMessage:
    def test_fatal_reports(
        self, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reports: list[tuple[str, str]] = []
        monkeypatch.setattr(
            error_dialog,
            "_report_fatal",
            lambda message, details: reports.append((message, details)),
        )
        error_dialog._handle_qt_message(QtMsgType.QtFatalMsg, object(), "qt boom")
        assert len(reports) == 1
        assert "qt boom" in reports[0][1]

    def test_non_fatal_logs_debug(
        self,
        qapp: QApplication,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        reports: list[tuple[str, str]] = []
        monkeypatch.setattr(
            error_dialog,
            "_report_fatal",
            lambda message, details: reports.append((message, details)),
        )
        with caplog.at_level(logging.DEBUG, logger="projectionai"):
            error_dialog._handle_qt_message(QtMsgType.QtWarningMsg, object(), "qt warn")
        assert reports == []
        assert "qt warn" in caplog.text


class TestFindLogFile:
    @pytest.fixture(autouse=True)
    def _clean_root_logger(self) -> Generator[None]:
        """Isolate the root logger (pytest installs its own handlers)."""
        root = logging.getLogger()
        saved = root.handlers[:]
        root.handlers[:] = []
        yield
        root.handlers[:] = saved

    def test_returns_file_handler_path(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        handler = logging.FileHandler(tmp_path / "app.log")
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            assert error_dialog._find_log_file() == tmp_path / "app.log"
        finally:
            root.removeHandler(handler)
            handler.close()

    def test_returns_none_without_file_handler(self, qapp: QApplication) -> None:
        assert error_dialog._find_log_file() is None


class TestErrorDialog:
    def test_toggle_details(self, qapp: QApplication) -> None:
        dialog = error_dialog.ErrorDialog("bad thing", "traceback line 1")
        dialog.show()
        try:
            assert not dialog._detail_view.isVisible()
            dialog._toggle_button.click()
            assert dialog._detail_view.isVisible()
            assert dialog._toggle_button.text() == "Hide Details"
            dialog._toggle_button.click()
            assert not dialog._detail_view.isVisible()
            assert dialog._toggle_button.text() == "Show Details"
        finally:
            dialog.close()

    def test_open_log_button_only_with_log_file(
        self, qapp: QApplication, tmp_path: Path
    ) -> None:
        with_log = error_dialog.ErrorDialog("m", "d", log_file=tmp_path / "app.log")
        texts = [b.text() for b in with_log.findChildren(QPushButton)]
        assert "Open Log File" in texts

        without = error_dialog.ErrorDialog("m", "d")
        texts = [b.text() for b in without.findChildren(QPushButton)]
        assert "Open Log File" not in texts
