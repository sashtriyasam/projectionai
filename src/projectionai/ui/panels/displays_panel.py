"""DisplaysPanel — display topology, validation, and projector output (dock).

Four sections:

- DISPLAYS: every detected display with rich info (name, manufacturer/
  model, mode, kind, connection, primary, live/preview role; supported
  modes in the tooltip).
- PROJECTORS: projector-classified displays with live-state coloring.
- VALIDATION: last validation report + the latest action/event message.
- OUTPUT: session state and the projector controls — Select as Preview,
  Select as Live, Identify, Test Pattern, Fullscreen, Blackout, Freeze
  (toggle), Exit Output, Refresh.

Async manager calls are scheduled through ``run_async``; the panel
re-renders on every view-model notification, on hardware events, and on
the main window's poll timer. Action failures surface as a user-facing
message on the view model (rendered in the VALIDATION section).
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

from projectionai.core.errors import ProjectionAIError
from projectionai.hardware.display_validator import ValidationReport
from projectionai.hardware.errors import OutputSwitchError
from projectionai.hardware.models import DisplayConnection, DisplayInfo, DisplayKind
from projectionai.hardware.output_manager import OutputState
from projectionai.hardware.patterns import PATTERNS, PatternKind
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

_CONNECTION_LABELS = {
    DisplayConnection.HDMI: "HDMI",
    DisplayConnection.DISPLAY_PORT: "DisplayPort",
    DisplayConnection.VGA: "VGA",
    DisplayConnection.DVI: "DVI",
    DisplayConnection.USB_C: "USB-C",
    DisplayConnection.THUNDERBOLT: "Thunderbolt",
    DisplayConnection.WIRELESS: "wireless",
    DisplayConnection.VIRTUAL: "virtual",
    DisplayConnection.UNKNOWN: "unknown",
}


class DisplaysPanel(ViewModelPanel):
    """Display topology + validation + projector output dock panel."""

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
        self.message_label = QLabel("")
        self.message_label.setObjectName("actionMessageLabel")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {WARN_YELLOW};")
        root.addWidget(self.message_label)

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

        pattern_row = QHBoxLayout()
        pattern_row.setContentsMargins(4, 0, 4, 0)
        pattern_row.setSpacing(4)
        pattern_label = QLabel("Pattern")
        pattern_label.setObjectName("propLabel")
        self.pattern_combo = QComboBox()
        self.pattern_combo.setObjectName("patternCombo")
        for spec in PATTERNS:
            if spec.kind is PatternKind.BLACK:
                continue  # blackout covers solid black
            self.pattern_combo.addItem(spec.name, spec.kind)
        pattern_row.addWidget(pattern_label)
        pattern_row.addWidget(self.pattern_combo, stretch=1)
        pattern_row.addWidget(make_action_button("Test Pattern", self._test_pattern))
        root.addLayout(pattern_row)

        actions_row1 = QHBoxLayout()
        actions_row1.setContentsMargins(4, 4, 4, 0)
        actions_row1.setSpacing(4)
        actions_row1.addWidget(
            make_action_button("Select as Preview", self._select_preview)
        )
        actions_row1.addWidget(make_action_button("Select as Live", self._select_live))
        actions_row1.addWidget(make_action_button("Identify", self._identify))
        actions_row1.addStretch(1)
        root.addLayout(actions_row1)

        actions_row2 = QHBoxLayout()
        actions_row2.setContentsMargins(4, 4, 4, 0)
        actions_row2.setSpacing(4)
        actions_row2.addWidget(make_action_button("Fullscreen", self._fullscreen))
        actions_row2.addWidget(make_action_button("Blackout", self._blackout))
        self.freeze_button = make_action_button("Freeze", self._freeze_toggle)
        self.freeze_button.setCheckable(True)
        self.freeze_button.setObjectName("freezeButton")
        actions_row2.addWidget(self.freeze_button)
        actions_row2.addStretch(1)
        root.addLayout(actions_row2)

        actions_row3 = QHBoxLayout()
        actions_row3.setContentsMargins(4, 4, 4, 4)
        actions_row3.setSpacing(4)
        actions_row3.addWidget(make_action_button("Exit Output", self._exit_output))
        actions_row3.addWidget(make_action_button("Refresh", self._refresh))
        actions_row3.addStretch(1)
        root.addLayout(actions_row3)

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
        self.message_label.setText("")
        self.session_label.setText("● IDLE")
        self.session_label.setStyleSheet(f"color: {STATE_COLORS['idle']};")
        self.preview_combo.clear()
        self.freeze_button.setChecked(False)

    def _refresh_displays(self) -> None:
        vm = self._viewmodel
        self.display_list.clear()
        if vm is None:
            return
        live_id = vm.live_display_id
        preview_id = vm.preview_display_id
        for display in vm.displays():
            self.display_list.addItem(self._display_item(display, live_id, preview_id))

    def _refresh_projectors(self) -> None:
        vm = self._viewmodel
        self.projector_list.clear()
        if vm is None:
            return
        live_id = vm.live_display_id
        preview_id = vm.preview_display_id
        for projector in vm.projectors():
            self.projector_list.addItem(
                self._projector_item(projector, live_id, preview_id)
            )

    def _refresh_validation(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        report = vm.validate()
        self._render_report(report)
        self.message_label.setText(vm.message or "")

    def _refresh_session(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        state = vm.output_state.value
        self.session_label.setText(f"● {state.upper()}")
        self.session_label.setStyleSheet(f"color: {STATE_COLORS.get(state, TEXT_DIM)};")
        self.freeze_button.setChecked(vm.output_state is OutputState.FREEZE)

        self.preview_combo.blockSignals(True)
        self.preview_combo.clear()
        self.preview_combo.addItem("(none)", None)
        for display in vm.displays():
            label = self._display_label(display, None, None)
            self.preview_combo.addItem(label, display.display_id)
        index = self.preview_combo.findData(vm.preview_display_id)
        if index >= 0:
            self.preview_combo.setCurrentIndex(index)
        self.preview_combo.blockSignals(False)

    # -- Item builders --------------------------------------------------------

    @staticmethod
    def _display_label(
        display: DisplayInfo, live_id: str | None, preview_id: str | None
    ) -> str:
        parts = [display.name]
        device = display.manufacturer or display.model
        if device:
            parts.append(device)
        parts.append(display.mode_label)
        parts.append(_KIND_LABELS.get(display.kind, "unknown"))
        parts.append(_CONNECTION_LABELS.get(display.connection, "unknown"))
        if display.is_primary:
            parts.append("primary")
        if display.display_id == live_id:
            parts.append("LIVE")
        elif display.display_id == preview_id:
            parts.append("PREVIEW")
        return " · ".join(parts)

    @classmethod
    def _display_item(
        cls, display: DisplayInfo, live_id: str | None, preview_id: str | None
    ) -> QListWidgetItem:
        item = QListWidgetItem(cls._display_label(display, live_id, preview_id))
        item.setData(_USER_ROLE, display.display_id)
        item.setForeground(QColor(TEXT_DIM))
        item.setToolTip(cls._display_tooltip(display))
        return item

    @classmethod
    def _projector_item(
        cls, display: DisplayInfo, live_id: str | None, preview_id: str | None
    ) -> QListWidgetItem:
        if display.display_id == live_id:
            state = "LIVE"
            colour = LIVE_RED
        elif display.display_id == preview_id:
            state = "PREVIEW"
            colour = WARN_YELLOW
        else:
            state = display.connection.value
            colour = TEXT_DIM
        item = QListWidgetItem(f"{display.name}  ·  {display.mode_label}  ·  {state}")
        item.setData(_USER_ROLE, display.display_id)
        item.setForeground(QColor(colour))
        item.setToolTip(cls._display_tooltip(display))
        return item

    @staticmethod
    def _display_tooltip(display: DisplayInfo) -> str:
        modes = display.supported_modes or (display.current_mode,)
        mode_lines = "\n".join(mode.label for mode in modes)
        return f"{display.display_id}\nSupported modes:\n{mode_lines}"

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

    def _select_preview(self) -> None:
        vm = self._viewmodel
        display_id = self._selected_display_id()
        if vm is None or display_id is None:
            return
        run_async(self._safe(vm.select_preview(display_id)))

    def _select_live(self) -> None:
        vm = self._viewmodel
        display_id = self._selected_display_id()
        if vm is None or display_id is None:
            return
        run_async(self._safe(vm.select_live(display_id)))

    def _test_pattern(self) -> None:
        vm = self._viewmodel
        display_id = self._selected_display_id()
        if vm is None or display_id is None:
            return
        kind = cast(PatternKind | None, self.pattern_combo.currentData())
        if kind is None:
            return
        run_async(self._safe(vm.test_pattern(display_id, kind)))

    def _fullscreen(self) -> None:
        vm = self._viewmodel
        display_id = self._selected_display_id()
        if vm is None or display_id is None:
            return
        run_async(self._safe(vm.enter_fullscreen(display_id)))

    def _blackout(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(self._safe(vm.blackout()))

    def _freeze_toggle(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(self._safe(vm.toggle_freeze()))

    def _exit_output(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(self._safe(vm.exit_output()))

    def _refresh(self) -> None:
        vm = self._viewmodel
        if vm is None:
            return
        run_async(vm.refresh_displays())

    def _identify(self) -> None:
        vm = self._viewmodel
        display_id = self._selected_display_id()
        if vm is None or display_id is None:
            return
        run_async(vm.identify(display_id))

    async def _safe(self, coro: Any) -> None:
        """Run an action, surfacing failures as a view-model message."""
        vm = self._viewmodel
        try:
            await coro
            if vm is not None and hasattr(vm, "clear_message"):
                vm.clear_message()
        except OutputSwitchError as exc:
            if exc.report is not None:
                self._render_report(exc.report)
            if vm is not None and hasattr(vm, "set_message"):
                vm.set_message(f"✗ {exc}")
        except ProjectionAIError as exc:
            if vm is not None and hasattr(vm, "set_message"):
                vm.set_message(f"✗ {exc}")
