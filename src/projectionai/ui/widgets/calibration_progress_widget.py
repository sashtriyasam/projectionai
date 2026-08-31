"""CalibrationProgressWidget — production calibration progress display.

Shows the complete pipeline (9 stages), overall/stage progress bars,
elapsed time, ETA, hardware-pending gates, cancel/retry controls,
warnings, and errors.  Polls the viewmodel on a QTimer so the Qt
event loop is never blocked during calibration.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.theme import (
    ACCENT,
    BORDER,
    LIVE_RED,
    OK_GREEN,
    PANEL_BG,
    TEXT,
    TEXT_DIM,
    WARN_YELLOW,
    WINDOW_BG,
)
from projectionai.ui.viewmodels.calibration_progress import (
    CalibrationProgressViewModel,
)

# ---------------------------------------------------------------------------
# Stage definitions — deterministic order matches ProductionWorkflow
# ---------------------------------------------------------------------------
_STAGES: tuple[str, ...] = (
    "PREPARING",
    "CAPTURING",
    "DECODING",
    "RECONSTRUCTING",
    "SOLVING",
    "VALIDATING",
    "PREVIEW",
    "SAVING",
)

# Mapping from ProductionWorkflow stage ids (in _WORKFLOW_STAGE_ORDER) to
# widget display names.  Must be exactly 1:1 with the 8 execution stages
# defined in ProductionWorkflow._WORKFLOW_STAGE_ORDER.
_WORKFLOW_TO_WIDGET_STAGE: dict[str, str] = {
    "prepare": "PREPARING",
    "capture": "CAPTURING",
    "decode": "DECODING",
    "reconstruct": "RECONSTRUCTING",
    "solve": "SOLVING",
    "validate": "VALIDATING",
    "warp": "PREVIEW",
    "persist": "SAVING",
}

# Status → colour token (matches theme.py)
_STATUS_COLORS: dict[str, str] = {
    "PENDING": TEXT_DIM,
    "RUNNING": ACCENT,
    "COMPLETE": OK_GREEN,
    "FAILED": LIVE_RED,
    "CANCELLED": TEXT_DIM,
    "SKIPPED": TEXT_DIM,
}

_POLL_INTERVAL_MS: int = 100


def _fmt_elapsed(seconds: float) -> str:
    """Format seconds as ``MM:SS``."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _make_separator() -> QFrame:
    """Thin horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet(f"color: {BORDER};")
    return line


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------
class CalibrationProgressWidget(QWidget):
    """Calibration progress panel — polls viewmodel via QTimer."""

    def __init__(
        self,
        viewmodel: CalibrationProgressViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = viewmodel
        self._last_revision: int = -1

        self.setObjectName("calibrationProgressWidget")
        self.setStyleSheet(
            f"background: {PANEL_BG}; color: {TEXT};"
            f"QWidget#calibrationProgressWidget {{ background: {PANEL_BG}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # -- Title ----------------------------------------------------------
        title = QLabel("Calibration Progress")
        title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {TEXT};")
        root.addWidget(title)

        # -- State label ----------------------------------------------------
        self._state_label = QLabel("Idle")
        self._state_label.setObjectName("stateLabel")
        root.addWidget(self._state_label)

        self._source_label = QLabel("")
        self._source_label.setStyleSheet(
            f"font-weight: bold; font-size: 11px; color: {ACCENT};"
        )
        root.addWidget(self._source_label)

        root.addWidget(_make_separator())

        # -- Stage pipeline -------------------------------------------------
        stages_header = QLabel("Pipeline")
        stages_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(stages_header)

        self._stage_labels: dict[str, QLabel] = {}
        for stage in _STAGES:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(stage)
            lbl.setFixedWidth(140)
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            status_lbl = QLabel("PENDING")
            status_lbl.setObjectName(f"stage_{stage}")
            status_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            self._stage_labels[stage] = status_lbl
            row.addWidget(lbl)
            row.addWidget(status_lbl)
            row.addStretch(1)
            root.addLayout(row)

        root.addWidget(_make_separator())

        # -- Overall progress ------------------------------------------------
        overall_row = QHBoxLayout()
        overall_row.setSpacing(8)
        overall_lbl = QLabel("Overall")
        overall_lbl.setStyleSheet(f"color: {TEXT_DIM};")
        self._overall_pct = QLabel("0%")
        self._overall_pct.setStyleSheet(f"color: {TEXT}; font-weight: bold;")
        overall_row.addWidget(overall_lbl)
        overall_row.addStretch(1)
        overall_row.addWidget(self._overall_pct)
        root.addLayout(overall_row)

        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 100)
        self._overall_bar.setValue(0)
        self._overall_bar.setTextVisible(False)
        self._overall_bar.setFixedHeight(8)
        self._overall_bar.setStyleSheet(
            f"QProgressBar {{ background: {WINDOW_BG}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}"
        )
        root.addWidget(self._overall_bar)

        # -- Stage progress -------------------------------------------------
        stage_row = QHBoxLayout()
        stage_row.setSpacing(8)
        stage_prog_lbl = QLabel("Stage")
        stage_prog_lbl.setStyleSheet(f"color: {TEXT_DIM};")
        self._stage_pct = QLabel("0%")
        self._stage_pct.setStyleSheet(f"color: {TEXT};")
        stage_row.addWidget(stage_prog_lbl)
        stage_row.addStretch(1)
        stage_row.addWidget(self._stage_pct)
        root.addLayout(stage_row)

        self._stage_bar = QProgressBar()
        self._stage_bar.setRange(0, 100)
        self._stage_bar.setValue(0)
        self._stage_bar.setTextVisible(False)
        self._stage_bar.setFixedHeight(6)
        self._stage_bar.setStyleSheet(
            f"QProgressBar {{ background: {WINDOW_BG}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )
        root.addWidget(self._stage_bar)

        # -- Time row -------------------------------------------------------
        time_row = QHBoxLayout()
        time_row.setSpacing(12)
        self._elapsed_label = QLabel("Elapsed: 00:00")
        self._elapsed_label.setStyleSheet(f"color: {TEXT_DIM};")
        self._eta_label = QLabel("ETA: calculating…")
        self._eta_label.setStyleSheet(f"color: {TEXT_DIM};")
        time_row.addWidget(self._elapsed_label)
        time_row.addWidget(self._eta_label)
        time_row.addStretch(1)
        root.addLayout(time_row)

        root.addWidget(_make_separator())

        # -- Device status --------------------------------------------------
        dev_header = QLabel("Devices")
        dev_header.setStyleSheet(f"font-weight: bold; color: {TEXT_DIM};")
        root.addWidget(dev_header)

        self._camera_label = QLabel("Camera: Not connected")
        self._camera_label.setStyleSheet(f"color: {TEXT_DIM};")
        self._projector_label = QLabel("Projector: Not connected")
        self._projector_label.setStyleSheet(f"color: {TEXT_DIM};")
        root.addWidget(self._camera_label)
        root.addWidget(self._projector_label)

        root.addWidget(_make_separator())

        # -- Hardware-pending -----------------------------------------------
        hw_header = QLabel("HARDWARE PENDING")
        hw_header.setStyleSheet(
            f"font-weight: bold; color: {WARN_YELLOW}; font-size: 11px;"
        )
        root.addWidget(hw_header)

        self._hw_frame = QFrame()
        self._hw_layout = QVBoxLayout(self._hw_frame)
        self._hw_layout.setContentsMargins(0, 0, 0, 0)
        self._hw_layout.setSpacing(2)
        self._hw_labels: list[QLabel] = []
        root.addWidget(self._hw_frame)

        root.addWidget(_make_separator())

        # -- Warnings -------------------------------------------------------
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setStyleSheet(f"color: {WARN_YELLOW};")
        self._warnings_label.hide()
        root.addWidget(self._warnings_label)

        # -- Errors ---------------------------------------------------------
        self._errors_label = QLabel("")
        self._errors_label.setWordWrap(True)
        self._errors_label.setStyleSheet(f"color: {LIVE_RED};")
        self._errors_label.hide()
        root.addWidget(self._errors_label)

        # -- Controls -------------------------------------------------------
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {LIVE_RED}; color: white; border: none;"
            f" padding: 4px 12px; border-radius: 3px; }}"
            f"QPushButton:disabled {{ background: {TEXT_DIM}; color: {WINDOW_BG}; }}"
        )
        self._retry_btn = QPushButton("Retry")
        self._retry_btn.setEnabled(False)
        self._retry_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: {WINDOW_BG}; border: none;"
            f" padding: 4px 12px; border-radius: 3px; }}"
            f"QPushButton:disabled {{ background: {TEXT_DIM}; color: {WINDOW_BG}; }}"
        )
        ctrl_row.addWidget(self._cancel_btn)
        ctrl_row.addWidget(self._retry_btn)
        ctrl_row.addStretch(1)
        root.addLayout(ctrl_row)

        root.addStretch(1)

        # -- Poll timer -----------------------------------------------------
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)

    # -- Public API --------------------------------------------------------

    def refresh(self) -> None:
        """Read the viewmodel and update all visible elements."""
        if self._vm.revision == self._last_revision:
            return
        self._last_revision = self._vm.revision

        vm = self._vm

        # State
        self._state_label.setText(vm.workflow_state)

        # Source mode
        self._source_label.setText(f"SOURCE: {vm.source_mode}")

        # Pipeline stages — map workflow stage id to widget display name
        active_id = self._vm._active_stage_id()
        active_widget_stage = (
            _WORKFLOW_TO_WIDGET_STAGE.get(active_id, "") if active_id else ""
        )

        for stage_name, lbl in self._stage_labels.items():
            # Determine this stage's display status
            if stage_name == active_widget_stage:
                stage_st = vm.stage_status
            elif vm.workflow_state in ("Cancelled", "Failed"):
                # Keep completed stages green in terminal state
                stage_st = "COMPLETE"
            else:
                stage_st = "PENDING"
            color = _STATUS_COLORS.get(stage_st, TEXT_DIM)
            prefix = (
                "●"
                if stage_st == "RUNNING"
                else (
                    "✓"
                    if stage_st == "COMPLETE"
                    else (
                        "✗"
                        if stage_st == "FAILED"
                        else ("-" if stage_st == "SKIPPED" else "o")
                    )
                )
            )
            lbl.setText(f"{prefix} {stage_st}")
            lbl.setStyleSheet(f"color: {color}; font-size: 11px;")

        # Overall progress
        pct = int(vm.overall_progress * 100)
        self._overall_bar.setValue(pct)
        self._overall_pct.setText(f"{pct}%")

        # Stage progress
        spct = int(vm.stage_progress * 100)
        self._stage_bar.setValue(spct)
        self._stage_pct.setText(f"{spct}%")

        # Time
        self._elapsed_label.setText(f"Elapsed: {_fmt_elapsed(vm.elapsed_time)}")
        eta = vm.estimated_remaining
        if eta is None:
            self._eta_label.setText("ETA: calculating…")
        else:
            self._eta_label.setText(f"ETA: {_fmt_elapsed(eta)}")

        # Devices
        self._camera_label.setText(f"Camera: {vm.camera_status}")
        self._projector_label.setText(f"Projector: {vm.projector_status}")

        # Hardware-pending gates
        self._update_hw_gates(vm.hardware_pending)

        # Warnings
        warnings = vm.warnings
        if warnings:
            self._warnings_label.setText("⚠ " + "\n".join(warnings))
            self._warnings_label.show()
        else:
            self._warnings_label.hide()

        # Errors
        errors = vm.errors
        if errors:
            cat = vm.error_category
            prefix = f"[{cat}] " if cat else ""
            self._errors_label.setText(prefix + "✗ " + "\n".join(errors))
            self._errors_label.show()
        else:
            self._errors_label.hide()

        # Controls
        self._cancel_btn.setEnabled(vm.can_cancel)
        self._retry_btn.setEnabled(vm.can_retry)

    # -- Internal ----------------------------------------------------------

    def _update_hw_gates(self, gates: tuple[str, ...]) -> None:
        """Rebuild the hardware-pending gate labels."""
        # Remove old labels
        for lbl in self._hw_labels:
            self._hw_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._hw_labels.clear()

        if not gates:
            empty = QLabel("None")
            empty.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            self._hw_layout.addWidget(empty)
            self._hw_labels.append(empty)
            return

        for gate in gates:
            lbl = QLabel(f"  ○ {gate}")
            lbl.setStyleSheet(f"color: {WARN_YELLOW}; font-size: 11px;")
            self._hw_layout.addWidget(lbl)
            self._hw_labels.append(lbl)
