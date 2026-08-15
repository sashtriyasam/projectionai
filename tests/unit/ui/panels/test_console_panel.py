"""Tests for ConsolePanel: log mirroring, clear, shutdown, line cap.

The panel attaches a handler to the root logger on construction; the
bridge signal is direct-connected (same thread), so a logged record is
mirrored synchronously. Every test shuts the panel down so handlers do
not leak across tests. Rendering happens offscreen
(``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from projectionai.ui.panels.console_panel import _MAX_LINES, ConsolePanel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    """Return the process-wide QApplication (created once)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _debug_root_logger() -> Generator[None]:
    """Let DEBUG records reach handlers (root defaults to WARNING)."""
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    yield
    root.setLevel(previous)


class TestLogMirroring:
    def test_log_record_appears(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        try:
            logging.getLogger("test.console").info("hello console")
            assert "hello console" in panel.output.toPlainText()
        finally:
            panel.shutdown()

    def test_warning_has_level_name(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        try:
            logging.getLogger("test.console").warning("watch out")
            assert "WARNING" in panel.output.toPlainText()
        finally:
            panel.shutdown()

    def test_clear_empties_output(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        try:
            logging.getLogger("test.console").info("transient")
            panel.clear()
            assert panel.output.toPlainText() == ""
        finally:
            panel.shutdown()

    def test_own_module_records_are_filtered(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        try:
            logging.getLogger("projectionai.ui.panels.console_panel").warning(
                "self echo"
            )
            logging.getLogger("projectionai.ui.panels.console_panel.sub").warning(
                "child echo"
            )
            assert "self echo" not in panel.output.toPlainText()
            assert "child echo" not in panel.output.toPlainText()
        finally:
            panel.shutdown()

    def test_sibling_prefixed_module_is_not_filtered(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        try:
            logging.getLogger("projectionai.ui.panels.console_panel_metrics").info(
                "sibling metrics"
            )
            assert "sibling metrics" in panel.output.toPlainText()
        finally:
            panel.shutdown()


class TestLifecycle:
    def test_shutdown_detaches_handler(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        root = logging.getLogger()
        assert panel._handler in root.handlers
        panel.shutdown()
        assert panel._handler not in root.handlers
        assert panel._handler._closed  # close() was invoked

    def test_line_cap(self, qapp: QApplication) -> None:
        panel = ConsolePanel()
        try:
            for i in range(_MAX_LINES + 50):
                panel._append_line(f"line {i}")
            assert panel.output.document().blockCount() <= _MAX_LINES
        finally:
            panel.shutdown()
