"""DisplaysPanel — display topology, validation, and output session (dock).

Four sections:

- DISPLAYS: every detected display (kind, resolution, connection, primary).
- PROJECTORS: projector-classified displays with live-state coloring.
- VALIDATION: last validation report (errors / warnings / recommendations).
- OUTPUT: session controls — begin, preview target, arm, go live,
  blackout, end, identify.

Async manager calls are scheduled through ``run_async``; the panel
re-renders on every view-model notification and on the main window's
poll timer.
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from projectionai.hardware.display_validator import ValidationReport
from projectionai.hardware.errors import OutputSwitchError
from projectionai.hardware.models import DisplayInfo, DisplayKind
from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.panels.common import make_action_button, make_section_header
from projectionai.ui.theme import (
    LIVE_RED,
    OK_GREEN,
    STATE_COLORS,
    TEXT_DIM,
    WARN_YELLOW,
)
from projectionai.ui.widgets.panel_base import run_async

_USER_ROLE = int(Qt.ItemDataRole.UserRole)

_KIND_LABELS = {
    DisplayKind.MONITOR: "monitor",
    DisplayKind.PROJECTOR: "projector",
    DisplayKind.VIRTUAL: "virtual",
    DisplayKind.UNKNOWN: "unknown",
}


class DisplaysPanel(ViewModelPanel):
    """Display topology + validation + output session dock panel."""

    panel_id = "displays"

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("displaysPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Displays section ------------------------------------------------
        root.addWidget(make_section_header("DISPLAYS"))
        self.display_list = QListWidget()
        self.display_list.setObjectName("displayList")
        self.display_list.itemClicked.connect(self._display_clicked)
        root.addWidget(self.display_list, stretch=3)

        # -- Projectors section ------------------------------------------------
        root.addWidget(make_section_header("PROJECTORS"))
        self.projector_list = QListWidget()
        self.projector_list.setObjectName("projectorList")
        self.projector_list.itemClicked.connect(self._display_clicked)
        root.addWidget(self.projector_list, stretch=2)

        # -- Validation section ------------------------------------------------
        root.addWidget(make_section_header("VALIDATION"))
        self.validation_label = QLabel("No report yet")
        self.validation_label.setObjectName("validationLabel")
        self.validation_label.setWordWrap(True)
        root.addWidget(self.validation_label)

        # -- Output session ------------------------------------------------------
        root.addWidget(make_section_header("OUTPUT"))
        self.session_label = QLabel("● IDLE")
        self.session_label.setObjectName("liveStateLabel")
        self.session_label.setStyleSheet(f"color: {STATE_COLORS['idle']};")
        root.addWidget(self.session_label)

        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(4, 4, 4, 4)
        preview_row.setSpacing(4)
        preview_label = QLabel("Preview")
        preview_label.setObjectName("propLabel")
        self.preview_combo = QComboBox()
        self.preview_combo.setObjectName("previewTargetCombo")
        self.preview_combo.activated.connect(self._preview_activated)
        preview_row.addWidget(preview_label)
        preview_row.addWidget(self.preview_combo, stretch=1)
        root.addLayout(preview_row)

        actions_row1 = QHBoxLayout()
        actions_row1.setContentsMargins(4, 0, 4, 0)
        actions_row1.setSpacing(4)
        actions_row1.addWidget(make_action_button("Begin", self._begin_session))
        actions_row1.addWidget(make_action_button("Arm", self._arm_session))
        actions_row1.addWidget(make_action_button("Go Live", self._go_live))
        actions_row1.addStretch(1)
        root.addLayout(actions_row1)

        actions_row2 = QHBoxLayout()
        actions_row2.setContentsMargins(4, 4, 4, 4)
        actions_row2.setSpacing(4)
        actions_row2.addWidget(make_action_button("Blackout", self._blackout))
        actions_row2.addWidget(make_action_button("End", self._end_session))
        actions_row2.addWidget(make_action_button("Identify", self._identify))
        actions_row2.addStretch(1)
        root.addLayout(actions_row2)

    # -- Refresh -------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the display lists, validation summary, and session state."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            vm = self._viewmodel
            if vm is None:
                self.clear()
                return
            self._refresh_displays()
            self._refresh_projectors()
            self._refresh_validation()
            self._refresh_session()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Empty every list and reset the labels."""
        self.display_list.clear()
        self.projector_list.clear()
        self.validation_label.setText("No report yet")
        self.session_label.setText("● IDLE")
        self.session_label.setStyleSheet(f"color: {STATE_COLORS['idle']};")
        self.preview_combo.clear()

    def _refresh_displays(self) -> None:
        vm = self._viewmodel
        self.display_list.clear()
        if vm is None:
            return
        for display in vm.displays():
            self.display_list.addItem(self._display_item(display))

    def _refresh_projectors(self) -> None:
        vm = self._viewmodel
        self.projector_list.clear()
        if vm is None:
            return
        live_id = vm.live_display_id
        for projector in vm.projectors():
            self.projector_list.addItem(
                self._projector_item(projector, projector.display_id == live_id)
            )

    def _refresh_validation(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        report = vm.validate()
        self._render_report(report)

    def _refresh_session(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        state = vm.output_state.value
        self.session_label.setText(f"● {state.upper()}")
        self.session_label.setStyleSheet(f"color: {STATE_COLORS.get(state, TEXT_DIM)};")

        self.preview_combo.blockSignals(True)
        self.preview_combo.clear()
        self.preview_combo.addItem("(none)", None)
        for display in vm.displays():
            label = self._display_label(display)
            self.preview_combo.addItem(label, display.display_id)
        index = self.preview_combo.findData(vm.preview_display_id)
        if index >= 0:
            self.preview_combo.setCurrentIndex(index)
        self.preview_combo.blockSignals(False)

    # -- Item builders --------------------------------------------------------

    @staticmethod
    def _display_label(display: DisplayInfo) -> str:
        mode = display.mode_label
        kind = _KIND_LABELS.get(display.kind, "unknown")
        primary = " · primary" if display.is_primary else ""
        return f"{display.name}  ·  {mode}  ·  {kind}{primary}"

    @classmethod
    def _display_item(cls, display: DisplayInfo) -> QListWidgetItem:
        item = QListWidgetItem(cls._display_label(display))
        item.setData(_USER_ROLE, display.display_id)
        item.setForeground(QColor(TEXT_DIM))
        return item

    @classmethod
    def _projector_item(cls, display: DisplayInfo, is_live: bool) -> QListWidgetItem:
        state = "LIVE" if is_live else display.connection.value
        item = QListWidgetItem(f"{display.name}  ·  {display.mode_label}  ·  {state}")
        item.setData(_USER_ROLE, display.display_id)
        item.setForeground(QColor(LIVE_RED if is_live else TEXT_DIM))
        return item

    # -- Validation rendering ----------------------------------------------------

    def _render_report(self, report: ValidationReport) -> None:
        if report.is_ok:
            self.validation_label.setText("✓ Ready — no issues")
            self.validation_label.setStyleSheet(f"color: {OK_GREEN};")
            return
        parts: list[str] = []
        if report.errors:
            parts.append(f"{len(report.errors)} error")
        if report.warnings:
            parts.append(f"{len(report.warnings)} warning")
        if report.recommendations:
            parts.append(f"{len(report.recommendations)} recommendation")
        first_issue = (
            report.errors[0]
            if report.errors
            else report.warnings[0]
            if report.warnings
            else report.recommendations[0]
        )
        color = LIVE_RED if report.errors else WARN_YELLOW
        self.validation_label.setText(f"⚠ {', '.join(parts)} — {first_issue.message}")
        self.validation_label.setStyleSheet(f"color: {color};")

    # -- Interactions -----------------------------------------------------------

    def _selected_display_id(self) -> str | None:
        item = self.display_list.currentItem() or self.projector_list.currentItem()
        if item is None:
            return None
        return cast(str | None, item.data(_USER_ROLE))

    def _display_clicked(self, item: QListWidgetItem) -> None:
        self.display_list.setCurrentItem(item)
        self.projector_list.setCurrentItem(item)

    def _preview_activated(self, index: int) -> None:
        """Apply a user-chosen preview target to the active session."""
        vm = self._viewmodel
        if vm is None or vm.session is None:
            return
        display_id = cast(str | None, self.preview_combo.itemData(index))
        run_async(vm.set_preview(display_id))

    def _begin_session(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        preview = self.preview_combo.currentData()
        run_async(vm.begin_session(cast(str | None, preview)))

    def _arm_session(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(vm.arm())

    def _go_live(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(self._go_live_safe(vm))

    async def _go_live_safe(self, vm: Any) -> None:
        try:
            await vm.go_live()
        except OutputSwitchError as exc:
            report = exc.report
            if report is not None:
                self._render_report(report)
            self.validation_label.setText(f"✗ Live rejected — {exc}")

    def _blackout(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(vm.blackout())

    def _end_session(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(vm.end_session())

    def _identify(self) -> None:
        vm = self._viewmodel
        display_id = self._selected_display_id()
        if vm is None or display_id is None:
            return
        run_async(vm.identify(display_id))
