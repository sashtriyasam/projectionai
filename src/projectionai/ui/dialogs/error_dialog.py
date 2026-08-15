"""Fatal-error reporting: unhandled exception hooks and the error dialog.

Provides :func:`install_exception_hooks` which installs process-wide
handlers for uncaught Python exceptions (main thread and background
threads) and fatal Qt messages. The main-thread handler logs the
exception and presents a modal :class:`ErrorDialog` with a collapsible
traceback and a shortcut to the log file, then exits the process.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import (
    QThread,
    QtMsgType,
    QUrl,
    qInstallMessageHandler,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

_logger = logging.getLogger("projectionai")

_hooks_installed = False
_HARD_EXIT = os._exit  # indirection for testability


def install_exception_hooks() -> None:
    """Install unhandled-exception handlers. Safe to call repeatedly."""
    global _hooks_installed
    if _hooks_installed:
        return
    sys.excepthook = _handle_sys_exception
    threading.excepthook = _handle_thread_exception
    qInstallMessageHandler(_handle_qt_message)
    _hooks_installed = True


def _handle_sys_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Main-thread unhandled exception: log, report, and exit."""
    _log_unhandled(exc_type, exc_value, exc_tb)
    if not _should_report():
        return
    _report_fatal(
        f"An unexpected error occurred: {exc_value}",
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
    )


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    """Background-thread unhandled exception: log only (no dialog)."""
    if args.exc_value is None:
        _logger.critical("Unhandled exception in thread (no exception value)")
        return
    _log_unhandled(args.exc_type, args.exc_value, args.exc_traceback)


def _handle_qt_message(msg_type: QtMsgType, _context: object, message: str) -> None:
    """Qt message handler: report fatal messages, log everything else."""
    if msg_type == QtMsgType.QtFatalMsg:
        _logger.critical("Qt fatal message: %s", message)
        if _should_report():
            _report_fatal("A fatal Qt error occurred.", message)
    else:
        _logger.debug("Qt message (%s): %s", msg_type.name, message)


def _log_unhandled(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    _logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))


def _should_report() -> bool:
    """True when a dialog can be shown from the current thread."""
    app = QApplication.instance()
    if app is None:
        return True
    return QThread.currentThread() is app.thread()


def _report_fatal(message: str, details: str) -> None:
    """Show the modal error dialog, then terminate the process."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    dialog = ErrorDialog(message, details, _find_log_file())
    dialog.exec()
    if QApplication.instance() is not None and QThread.currentThread() is app.thread():
        sys.exit(1)
    _HARD_EXIT(1)


def _find_log_file() -> Path | None:
    """Locate the file the root logger writes to, if any."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None


class ErrorDialog(QDialog):
    """Modal fatal-error dialog with collapsible traceback."""

    def __init__(
        self,
        message: str,
        details: str,
        log_file: Path | None = None,
        parent: QDialog | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ProjectionAI - Unexpected Error")
        self.setMinimumSize(560, 340)
        self.resize(640, 420)

        self._details = details

        layout = QVBoxLayout(self)
        heading = QLabel("ProjectionAI hit an unexpected problem.")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self._message_label = QLabel(message)
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        self._detail_view = QPlainTextEdit()
        self._detail_view.setReadOnly(True)
        self._detail_view.setPlainText(details)
        self._detail_view.setVisible(False)
        layout.addWidget(self._detail_view)

        button_row = QDialogButtonBox()
        self._toggle_button = QPushButton("Show Details")
        self._toggle_button.setCheckable(True)
        self._toggle_button.toggled.connect(self._on_toggle_details)
        button_row.addButton(
            self._toggle_button, QDialogButtonBox.ButtonRole.ActionRole
        )
        if log_file is not None:
            open_log = QPushButton("Open Log File")
            open_log.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file)))
            )
            button_row.addButton(open_log, QDialogButtonBox.ButtonRole.ActionRole)
        close_button = button_row.addButton(QDialogButtonBox.StandardButton.Close)
        close_button.clicked.connect(self.reject)
        layout.addWidget(button_row)

    def _on_toggle_details(self, checked: bool) -> None:
        self._detail_view.setVisible(checked)
        self._toggle_button.setText("Hide Details" if checked else "Show Details")
