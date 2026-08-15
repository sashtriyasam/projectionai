"""CalibrationSessionsPanel — calibration session list (left dock).

Lists workspace calibration sessions with status/progress, lets the
user create sessions (method selector), switch the active session, and
archive/remove/validate. Statuses map to theme colors so a glance at
the list shows the pipeline state.
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.types import CalibrationStatus
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import (
    ACCENT,
    LIVE_RED,
    OK_GREEN,
    TEXT_DIM,
    TEXT_FAINT,
    WARN_YELLOW,
)
from projectionai.ui.widgets.panel_base import run_async

_USER_ROLE = int(Qt.ItemDataRole.UserRole)

_STATUS_COLORS = {
    CalibrationStatus.IDLE: TEXT_FAINT,
    CalibrationStatus.PREPARING: TEXT_DIM,
    CalibrationStatus.ACQUIRING: ACCENT,
    CalibrationStatus.PROCESSING: ACCENT,
    CalibrationStatus.VALIDATING: WARN_YELLOW,
    CalibrationStatus.COMPLETED: OK_GREEN,
    CalibrationStatus.FAILED: LIVE_RED,
    CalibrationStatus.CANCELLED: TEXT_DIM,
}


class CalibrationSessionsPanel(ViewModelPanel):
    """Calibration Sessions dock panel."""

    panel_id = "calibration"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("calibrationPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header + new-session row ------------------------------------------
        root.addWidget(make_section_header("CALIBRATION SESSIONS", self._new_session))
        new_row = QHBoxLayout()
        new_row.setContentsMargins(4, 4, 4, 4)
        new_row.setSpacing(4)
        self.method_combo = QComboBox()
        self.method_combo.setObjectName("methodCombo")
        new_row.addWidget(self.method_combo, stretch=1)
        new_row.addWidget(make_action_button("New", self._new_session))
        root.addLayout(new_row)

        # -- Session list -------------------------------------------------------
        self.session_list = QListWidget()
        self.session_list.setObjectName("calibrationList")
        self.session_list.itemClicked.connect(self._session_clicked)
        root.addWidget(self.session_list, stretch=1)

        # -- Action row -----------------------------------------------------------
        actions = QHBoxLayout()
        actions.setContentsMargins(4, 4, 4, 4)
        actions.setSpacing(4)
        actions.addWidget(make_action_button("Set Active", self._set_active))
        actions.addWidget(make_action_button("Validate", self._validate))
        actions.addWidget(make_action_button("Archive", self._archive))
        actions.addWidget(make_action_button("Remove", self._remove))
        actions.addStretch(1)
        root.addLayout(actions)

        # -- Camera calibration run row ------------------------------------------
        run_row = QHBoxLayout()
        run_row.setContentsMargins(4, 4, 4, 4)
        run_row.setSpacing(4)
        self.run_button = make_action_button(
            "Run Camera Calibration", self._run_camera_calibration
        )
        self.run_button.setObjectName("runCalibrationButton")
        self.status_label = QLabel("")
        self.status_label.setObjectName("calibrationStatusLabel")
        self.status_label.setWordWrap(True)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.status_label, stretch=1)
        root.addLayout(run_row)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the method selector and session list."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._rebuild_methods()
            self._rebuild_list()
            self._sync_run_state()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty the session list."""
        self.session_list.clear()

    def _rebuild_methods(self) -> None:
        vm = self._viewmodel
        if vm is None:
            self.method_combo.clear()
            return
        current = self.method_combo.currentData()
        self.method_combo.blockSignals(True)
        try:
            self.method_combo.clear()
            for method in vm.methods():
                self.method_combo.addItem(
                    method.value.replace("_", " ").title(), method
                )
            if current is not None:
                idx = self.method_combo.findData(current)
                if idx >= 0:
                    self.method_combo.setCurrentIndex(idx)
        finally:
            self.method_combo.blockSignals(False)

    def _rebuild_list(self) -> None:
        vm = self._viewmodel
        selected = self._selected_session_id()
        self.session_list.clear()
        if vm is None:
            return
        active = vm.active_session()
        for session in vm.sessions():
            self.session_list.addItem(self._make_item(session, active))
        if selected is not None:
            for i in range(self.session_list.count()):
                item = self.session_list.item(i)
                if item.data(_USER_ROLE) == selected:
                    self.session_list.setCurrentItem(item)
                    break

    @classmethod
    def _make_item(
        cls,
        session: CalibrationSession,
        active: CalibrationSession | None,
    ) -> QListWidgetItem:
        status = cls._viewmodel_status_text(session)
        progress = int(session.state.progress * 100)
        text = f"{session.name}  ·  {status}  ·  {progress}%"
        if active is not None and session.id == active.id:
            text = "▶ " + text
        item = QListWidgetItem(text)
        item.setData(_USER_ROLE, session.id)
        color = _STATUS_COLORS.get(session.state.status, TEXT_FAINT)
        if active is not None and session.id == active.id:
            color = ACCENT
        item.setForeground(QColor(color))
        return item

    @staticmethod
    def _viewmodel_status_text(session: CalibrationSession) -> str:
        """Human-readable status (falls back to raw value)."""
        status = session.state.status
        return {
            CalibrationStatus.IDLE: "draft",
            CalibrationStatus.PREPARING: "preparing",
            CalibrationStatus.ACQUIRING: "acquiring",
            CalibrationStatus.PROCESSING: "processing",
            CalibrationStatus.VALIDATING: "validating",
            CalibrationStatus.COMPLETED: "deployed",
            CalibrationStatus.FAILED: "failed",
            CalibrationStatus.CANCELLED: "cancelled",
        }.get(status, str(status.value))

    # -- Interactions -----------------------------------------------------------

    def _session_clicked(self, item: QListWidgetItem) -> None:
        self.session_list.setCurrentItem(item)

    def _selected_session_id(self) -> str | None:
        item = self.session_list.currentItem()
        if item is None:
            return None
        return cast(str | None, item.data(_USER_ROLE))

    def _new_session(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        method = self.method_combo.currentData()
        if method is None:
            return
        name, ok = QInputDialog.getText(
            self,
            "New Calibration Session",
            "Session name:",
            text="Calibration Session",
        )
        if ok and name.strip():
            vm.create_session(name=name.strip(), method=method)

    def _set_active(self) -> None:
        vm = self._viewmodel
        session_id = self._selected_session_id()
        if vm is None or session_id is None:
            return
        vm.set_active_session(session_id)

    def _validate(self) -> None:
        vm = self._viewmodel
        session_id = self._selected_session_id()
        if vm is None or session_id is None:
            return
        session = vm.get_session(session_id)
        if session is None:
            return
        try:
            report = vm.validate(session)
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.warning(self, "Validation Failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Validation",
            f"Session '{session.name}': {getattr(report, 'status', 'valid')}",
        )

    def _archive(self) -> None:
        vm = self._viewmodel
        session_id = self._selected_session_id()
        if vm is None or session_id is None:
            return
        vm.archive_session(session_id)

    def _remove(self) -> None:
        vm = self._viewmodel
        session_id = self._selected_session_id()
        if vm is None or session_id is None:
            return
        result = QMessageBox.question(
            self,
            "Remove Session",
            "Remove this calibration session?",
        )
        if result == QMessageBox.StandardButton.Yes:
            vm.remove_session(session_id)

    # -- Camera calibration run -------------------------------------------------

    def _sync_run_state(self) -> None:
        """Reflect the run button + status label from the view model."""
        vm = self._viewmodel
        if vm is None:
            self.run_button.setEnabled(False)
            return
        self.run_button.setEnabled(not vm.is_calibration_running())
        status = vm.last_run_status()
        if status is not None:
            self.status_label.setText(status)

    def _run_camera_calibration(self) -> None:
        """Start a camera intrinsic calibration on the first open camera."""
        vm = self._viewmodel
        if vm is None:
            return
        camera_ids = vm.open_camera_ids()
        if not camera_ids:
            QMessageBox.information(
                self,
                "Run Camera Calibration",
                "Open a camera first (Camera panel).",
            )
            return
        self.run_button.setEnabled(False)
        run_async(vm.run_camera_calibration(camera_ids[0]))
