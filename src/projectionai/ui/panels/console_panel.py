"""ConsolePanel — read-only application log console (bottom dock).

Attaches a :class:`logging.Handler` to the root logger while the panel
is alive and mirrors records into a read-only ``QPlainTextEdit``.
``emit`` can be called from any thread, so the handler forwards lines
through a queued signal owned by the panel (which lives on the GUI
thread); the signal keeps the panel safe from cross-thread widget
access. The handler is detached on :meth:`shutdown`.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
)

from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header

_LOGGER = logging.getLogger(__name__)

_MAX_LINES = 1000
_FORMAT = "[%(asctime)s] %(levelname)s  %(message)s"
_DATEFMT = "%H:%M:%S"


class _LogBridge(QObject):
    """Cross-thread delivery channel for console lines."""

    line = Signal(str)


class _ConsoleHandler(logging.Handler):
    """Format log records and forward them to a bridge signal."""

    def __init__(self, bridge: _LogBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        self.addFilter(_IgnoreOwnModule())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            return
        self._bridge.line.emit(message)


class _IgnoreOwnModule(logging.Filter):
    """Drop records logged from this panel's own module.

    The console mirrors root-logger output; without this filter a
    message logged from ``console_panel`` itself (e.g. a future
    "console cleared" note) would echo back into the console.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        own = __name__
        return not (record.name == own or record.name.startswith(f"{own}."))


class ConsolePanel(ViewModelPanel):
    """Read-only console that mirrors root-logger output."""

    panel_id = "console"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("consolePanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(
            make_section_header(
                "CONSOLE",
                self.clear,
                action_text="Clear",
                action_tooltip="Clear console output",
            )
        )

        self.output = QPlainTextEdit()
        self.output.setObjectName("consoleOutput")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.output.setFont(font)
        root.addWidget(self.output, stretch=1)

        hints = QHBoxLayout()
        hints.setContentsMargins(4, 4, 4, 4)
        hints.addWidget(make_action_button("Clear", self.clear))
        hints.addStretch(1)
        root.addLayout(hints)

        self._bridge = _LogBridge()
        self._bridge.line.connect(self._append_line)
        self._handler = _ConsoleHandler(self._bridge)
        self._handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self._handler)

    # -- View model ---------------------------------------------------------

    def refresh(self) -> None:
        """Nothing to rebuild from a view model."""

    def clear(self) -> None:
        """Clear the console output."""
        self.output.clear()

    # -- Lifecycle ----------------------------------------------------------

    def shutdown(self) -> None:
        """Detach the log handler before dropping content."""
        logging.getLogger().removeHandler(self._handler)
        self._handler.close()
        super().shutdown()

    # -- Internals ------------------------------------------------------------

    def _append_line(self, text: str) -> None:
        self.output.appendPlainText(text)
        self._trim_to_max_lines()

    def _trim_to_max_lines(self) -> None:
        doc = self.output.document()
        while doc.blockCount() > _MAX_LINES:
            cursor = QTextCursor(doc.firstBlock())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())
