"""PreviewWidget — Qt widget for warp preview display and controls.

Follows the same widget pattern as CalibrationResultReviewWidget:
poll-based refresh via QTimer, no OutputManager coupling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.theme import (
    ACCENT,
    LIVE_RED,
    PANEL_BG,
    TEXT,
    TEXT_DIM,
    WINDOW_BG,
)

if TYPE_CHECKING:
    from projectionai.ui.viewmodels.preview import PreviewViewModel

_LOGGER = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 200
_STATE_COLORS = {
    "idle": TEXT_DIM,
    "loading": ACCENT,
    "ready": "#30D158",
    "running": "#30D158",
    "frozen": ACCENT,
    "blackout": TEXT_DIM,
    "error": LIVE_RED,
    "closed": TEXT_DIM,
}


def _sep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {TEXT_DIM}; max-height: 1px;")
    return line


class PreviewWidget(QWidget):
    """Warp preview control panel.

    Displays state, mesh diagnostics, content selector, and action buttons.
    Polls the PreviewViewModel via revision counter at ``_POLL_INTERVAL_MS``.
    """

    preview_started = Signal()
    preview_stopped = Signal()
    preview_closed = Signal()

    def __init__(
        self,
        viewmodel: PreviewViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._last_revision: int = -1

        self.setObjectName("previewWidget")
        self.setStyleSheet(
            f"background: {PANEL_BG}; color: {TEXT};"
            f"QWidget#previewWidget {{ background: {PANEL_BG}; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background: {PANEL_BG}; border: none;")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background: {PANEL_BG};")
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # -- Title ---------------------------------------------------------
        title = QLabel("Warp Preview")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        root.addWidget(title)

        # Status banner
        self._status_label = QLabel("IDLE")
        self._status_label.setObjectName("previewStatusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status_label)

        # -- Mesh diagnostics ----------------------------------------------
        diag_header = QLabel("Mesh Diagnostics")
        diag_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(diag_header)

        self._diag_verts = QLabel("Vertices: —")
        self._diag_verts.setProperty("diagPrefix", "Vertices")
        self._diag_faces = QLabel("Faces: —")
        self._diag_faces.setProperty("diagPrefix", "Faces")
        self._diag_grid = QLabel("Grid: —")
        self._diag_grid.setProperty("diagPrefix", "Grid")
        self._diag_uv_range = QLabel("UV range: —")
        self._diag_uv_range.setProperty("diagPrefix", "UV range")
        self._diag_gen = QLabel("Method: —")
        self._diag_gen.setProperty("diagPrefix", "Method")
        self._diag_valid = QLabel("Valid: —")
        for lbl in (
            self._diag_verts,
            self._diag_faces,
            self._diag_grid,
            self._diag_uv_range,
            self._diag_gen,
            self._diag_valid,
        ):
            lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
            lbl.setWordWrap(True)
            root.addWidget(lbl)

        root.addWidget(_sep())

        # -- Content selector ----------------------------------------------
        content_header = QLabel("Content")
        content_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(content_header)

        self._content_label = QLabel("IDENTITY")
        self._content_label.setStyleSheet(
            f"font-weight: bold; font-size: 12px; color: {ACCENT};"
        )
        root.addWidget(self._content_label)

        content_row = QHBoxLayout()
        content_row.setSpacing(6)
        self._cycle_btn = QPushButton("Cycle Content")
        self._cycle_btn.clicked.connect(self._on_cycle)
        content_row.addWidget(self._cycle_btn)
        content_row.addStretch(1)
        root.addLayout(content_row)

        root.addWidget(_sep())

        # -- Error display -------------------------------------------------
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {LIVE_RED}; font-size: 11px;"
            f"background: {WINDOW_BG}; padding: 6px; border-radius: 4px;"
        )
        self._error_label.hide()
        root.addWidget(self._error_label)

        # -- Actions -------------------------------------------------------
        actions_header = QLabel("Actions")
        actions_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(actions_header)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self._start_btn = QPushButton("Start")
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        self._freeze_btn = QPushButton("Freeze")
        self._freeze_btn.clicked.connect(self._on_freeze)
        self._blackout_btn = QPushButton("Blackout")
        self._blackout_btn.clicked.connect(self._on_blackout)
        row1.addWidget(self._start_btn)
        row1.addWidget(self._stop_btn)
        row1.addWidget(self._freeze_btn)
        row1.addWidget(self._blackout_btn)
        row1.addStretch(1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset)
        self._close_btn = QPushButton("Close Preview")
        self._close_btn.setStyleSheet(
            f"QPushButton {{ border: 1px solid {LIVE_RED}; color: {LIVE_RED}; padding: 4px 12px; border-radius: 3px; }}"
        )
        self._close_btn.clicked.connect(self._on_close)
        row2.addWidget(self._reset_btn)
        row2.addWidget(self._close_btn)
        row2.addStretch(1)
        root.addLayout(row2)

        root.addStretch(1)

        # Poll timer
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # -- Slots -----------------------------------------------------------

    def _on_start(self) -> None:
        if self._vm.start():
            self.preview_started.emit()

    def _on_stop(self) -> None:
        if self._vm.stop():
            self.preview_stopped.emit()

    def _on_freeze(self) -> None:
        self._vm.freeze()

    def _on_blackout(self) -> None:
        self._vm.blackout()

    def _on_reset(self) -> None:
        self._vm.reset()

    def _on_close(self) -> None:
        self._vm.close()
        self.preview_closed.emit()

    def _on_cycle(self) -> None:
        self._vm.cycle_content()

    # -- Refresh ---------------------------------------------------------

    def refresh(self) -> None:
        if self._vm.revision == self._last_revision:
            return
        self._last_revision = self._vm.revision
        vm = self._vm

        # Status
        state_val = vm.state.value
        color = _STATE_COLORS.get(state_val, TEXT_DIM)
        self._status_label.setText(vm.label)
        self._status_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {color};"
            f"padding: 6px 8px; border-radius: 4px; background: {WINDOW_BG};"
        )

        # Content
        self._content_label.setText(vm.content.value.upper())

        # Mesh diagnostics
        diag = vm.diagnostics
        if diag is not None:
            self._diag_verts.setText(f"Vertices: {diag.vertex_count}")
            self._diag_faces.setText(f"Faces: {diag.face_count}")
            self._diag_grid.setText(f"Grid: {diag.grid_rows}x{diag.grid_cols}")
            uv_lo, uv_hi = diag.projector_uv_range
            self._diag_uv_range.setText(f"UV range: [{uv_lo:.3f}, {uv_hi:.3f}]")
            self._diag_gen.setText(f"Method: {diag.generation_method}")
            valid_str = "YES" if diag.is_valid else "NO"
            valid_color = "#30D158" if diag.is_valid else LIVE_RED
            self._diag_valid.setText(f"Valid: {valid_str}")
            self._diag_valid.setStyleSheet(
                f"color: {valid_color}; font-size: 11px; font-weight: bold;"
            )
        else:
            for lbl in (
                self._diag_verts,
                self._diag_faces,
                self._diag_grid,
                self._diag_uv_range,
                self._diag_gen,
            ):
                prefix = lbl.property("diagPrefix")
                lbl.setText(f"{prefix}: —")
            self._diag_valid.setText("Valid: —")
            self._diag_valid.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")

        # Error
        if vm.error:
            self._error_label.setText(f"Error: {vm.error}")
            self._error_label.show()
        else:
            self._error_label.hide()

        # Buttons — enabled/disabled by state
        is_error = vm.state.value == "error"
        is_ready = vm.state.value == "ready"
        is_running = vm.state.value == "running"
        is_frozen = vm.state.value == "frozen"
        is_blackout = vm.state.value == "blackout"

        self._start_btn.setEnabled(is_ready)
        self._stop_btn.setEnabled(is_running or is_frozen or is_blackout)
        self._freeze_btn.setEnabled(is_running)
        self._blackout_btn.setEnabled(is_running or is_frozen or is_ready)
        self._reset_btn.setEnabled(is_error)
        self._cycle_btn.setEnabled(vm.is_active or is_ready)

    def closeEvent(self, event: object) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)  # type: ignore[arg-type]
