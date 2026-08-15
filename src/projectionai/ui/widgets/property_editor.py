"""PropertyEditorWidget — renders a PropertySheet with typed editors.

Used by the Inspector, Project Properties, Timeline Properties and
Output Settings panels. Reads :class:`PropertySheet`
(ui.viewmodels.properties) and commits edits back through
``sheet.commit()`` / ``sheet.activate()``; emits Qt signals for panel
convenience. The widget itself never owns business logic.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from projectionai.ui.theme import BORDER, TEXT
from projectionai.ui.viewmodels.properties import (
    PropertyRow,
    PropertySection,
    PropertySheet,
)

_PASTEABLE_KINDS = frozenset({"text", "int", "float", "bool", "choice", "color"})


class _SectionHeader(QToolButton):
    """Collapsible section title with an arrow indicator."""

    def __init__(
        self, title: str, collapsed: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sectionHeader")
        self.setText(title)
        self.setCheckable(True)
        self.setChecked(not collapsed)
        self.setArrowType(
            Qt.ArrowType.DownArrow if self.isChecked() else Qt.ArrowType.RightArrow
        )
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )


class _RowWidget(QWidget):
    """Label + typed editor + keyframe diamond for a single property row."""

    edited = Signal(str, object)
    button_clicked = Signal(str)
    keyframe_clicked = Signal(str)

    def __init__(self, row: PropertyRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self._color_value = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self._label = QLabel(row.label)
        self._label.setObjectName("propLabel")
        self._label.setToolTip(row.help)
        self._label.setMinimumWidth(90)
        layout.addWidget(self._label)

        self._editor = self._build_editor(row, layout)
        layout.addWidget(self._editor, 1)

        if row.kind not in ("label", "button"):
            keyframe = QToolButton()
            keyframe.setObjectName("keyframeBtn")
            keyframe.setFixedSize(14, 14)
            keyframe.setCursor(Qt.CursorShape.PointingHandCursor)
            keyframe.setToolTip("Keyframe this property")
            keyframe.clicked.connect(
                lambda _checked=False, rid=row.id: self.keyframe_clicked.emit(rid)
            )
            layout.addWidget(keyframe)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.set_value(row.value)

    # -- Editor construction -------------------------------------------------

    def _build_editor(self, row: PropertyRow, layout: QHBoxLayout) -> QWidget:
        kind = row.kind
        if kind == "text":
            line_edit = QLineEdit()
            line_edit.setReadOnly(row.read_only)
            line_edit.textEdited.connect(
                lambda _text: self.edited.emit(row.id, line_edit.text())
            )
            return line_edit
        if kind == "int":
            spin = QSpinBox()
            spin.setRange(
                int(row.minimum) if row.minimum is not None else -(2**31),
                int(row.maximum) if row.maximum is not None else 2**31 - 1,
            )
            spin.setSingleStep(int(row.step) if row.step is not None else 1)
            spin.setEnabled(not row.read_only)
            spin.valueChanged.connect(lambda _v: self.edited.emit(row.id, spin.value()))
            return spin
        if kind == "float":
            double_spin = QDoubleSpinBox()
            double_spin.setDecimals(3)
            double_spin.setRange(
                row.minimum if row.minimum is not None else -1e9,
                row.maximum if row.maximum is not None else 1e9,
            )
            double_spin.setSingleStep(row.step if row.step is not None else 0.1)
            double_spin.setEnabled(not row.read_only)
            double_spin.valueChanged.connect(
                lambda _v: self.edited.emit(row.id, double_spin.value())
            )
            return double_spin
        if kind == "bool":
            check = QCheckBox()
            check.setEnabled(not row.read_only)
            check.toggled.connect(
                lambda _v: self.edited.emit(row.id, check.isChecked())
            )
            return check
        if kind == "choice":
            combo = QComboBox()
            for display, value in row.choices:
                combo.addItem(display, value)
            combo.setEnabled(not row.read_only)
            combo.currentIndexChanged.connect(
                lambda _i: self.edited.emit(row.id, combo.currentData())
            )
            return combo
        if kind == "color":
            color_button = QPushButton()
            color_button.setFixedWidth(64)
            color_button.setCursor(Qt.CursorShape.PointingHandCursor)
            color_button.setEnabled(not row.read_only)
            color_button.clicked.connect(lambda: self._pick_color(row.id, color_button))
            return color_button
        if kind == "button":
            action_button = QPushButton(row.label)
            action_button.setObjectName("sectionActionButton")
            action_button.clicked.connect(lambda _c: self.button_clicked.emit(row.id))
            self._label.hide()
            return action_button
        value_label = QLabel()
        value_label.setObjectName("propValueLabel")
        value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        return value_label

    # -- Value plumbing ------------------------------------------------------

    def set_value(self, value: Any) -> None:
        """Update the editor without emitting edit signals."""
        editor = self._editor
        editor.blockSignals(True)
        try:
            kind = self._row.kind
            if kind == "text":
                if isinstance(editor, QLineEdit):
                    editor.setText(str(value))
            elif kind == "int":
                if isinstance(editor, QSpinBox):
                    editor.setValue(int(value))
            elif kind == "float":
                if isinstance(editor, QDoubleSpinBox):
                    editor.setValue(float(value))
            elif kind == "bool":
                if isinstance(editor, QCheckBox):
                    editor.setChecked(bool(value))
            elif kind == "choice":
                if isinstance(editor, QComboBox):
                    index = editor.findData(value)
                    if index >= 0:
                        editor.setCurrentIndex(index)
            elif kind == "color":
                self._color_value = str(value)
                if isinstance(editor, QPushButton):
                    editor.setText(str(value))
                    editor.setStyleSheet(
                        f"QPushButton {{ background-color: {self._color_value}; "
                        f"color: {TEXT}; border: 1px solid {BORDER}; "
                        f"border-radius: 3px; }}"
                    )
            elif kind == "label" and isinstance(editor, QLabel):
                editor.setText(str(value))
        except (TypeError, ValueError):
            pass
        finally:
            editor.blockSignals(False)

    def current_value(self) -> Any:
        """Return the editor's current value."""
        kind = self._row.kind
        editor = self._editor
        if kind == "text" and isinstance(editor, QLineEdit):
            return editor.text()
        if kind in ("int", "float") and isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        if kind == "bool" and isinstance(editor, QCheckBox):
            return editor.isChecked()
        if kind == "choice" and isinstance(editor, QComboBox):
            return editor.currentData()
        if kind == "color":
            return self._color_value
        if kind == "label" and isinstance(editor, QLabel):
            return editor.text()
        return None

    # -- Color picker --------------------------------------------------------

    def _pick_color(self, row_id: str, button: QPushButton) -> None:
        initial = QColor(self._color_value) if self._color_value else QColor()
        picked = QColorDialog.getColor(
            initial, self, f"Choose color for {self._row.label}"
        )
        if picked.isValid():
            self.set_value(picked.name())
            self.edited.emit(row_id, picked.name())

    # -- Copy / paste --------------------------------------------------------

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("Copy value")
        paste_action = menu.addAction("Paste value")
        paste_action.setEnabled(
            self._row.kind in _PASTEABLE_KINDS and not self._row.read_only
        )
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is copy_action:
            self._copy_value()
        elif chosen is paste_action:
            self._paste_value()

    def _copy_value(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(self.current_value()))

    def _paste_value(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return
        value = self._parse_paste(clipboard.text())
        if value is None:
            return
        self.set_value(value)
        self.edited.emit(self._row.id, value)

    def _parse_paste(self, text: str) -> Any:
        """Parse clipboard text into a row value; ``None`` when unusable."""
        kind = self._row.kind
        stripped = text.strip()
        if kind == "bool":
            return stripped.lower() in ("true", "1", "yes", "on")
        if kind == "int":
            try:
                return int(stripped)
            except ValueError:
                return None
        if kind == "float":
            try:
                return float(stripped)
            except ValueError:
                return None
        if kind == "color":
            return stripped if QColor(stripped).isValid() else None
        if kind == "choice":
            editor = self._editor
            if isinstance(editor, QComboBox):
                index = editor.findData(stripped)
                if index < 0:
                    index = editor.findText(stripped)
                return editor.itemData(index) if index >= 0 else None
            return None
        return text


class PropertyEditorWidget(QScrollArea):
    """Scrollable editor for a :class:`PropertySheet`."""

    row_edited = Signal(str, object)
    row_button = Signal(str)
    keyframe_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sheet: PropertySheet | None = None
        self._rows: dict[str, _RowWidget] = {}
        self._sections: list[tuple[_SectionHeader, QWidget]] = []

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container.setObjectName("propContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        self.setWidget(self._container)

    # -- Sheet management ----------------------------------------------------

    @property
    def sheet(self) -> PropertySheet | None:
        """Return the bound property sheet."""
        return self._sheet

    def set_sheet(self, sheet: PropertySheet | None) -> None:
        """Bind a property sheet and rebuild the editor."""
        self._sheet = sheet
        self.rebuild()

    def rebuild(self) -> None:
        """Rebuild all sections from the bound sheet (structure changed)."""
        for header, content in self._sections:
            self._layout.removeWidget(header)
            header.deleteLater()
            self._layout.removeWidget(content)
            content.deleteLater()
        self._sections.clear()
        self._rows.clear()

        sheet = self._sheet
        if sheet is None:
            return
        for section in sheet.sections:
            self._add_section(section)

    def refresh(self) -> None:
        """Re-read every row value from the sheet without emitting edits."""
        sheet = self._sheet
        if sheet is None:
            return
        for section in sheet.sections:
            for row in section.rows:
                widget = self._rows.get(row.id)
                if widget is not None:
                    widget.set_value(row.value)

    # -- Internal ------------------------------------------------------------

    def _add_section(self, section: PropertySection) -> None:
        header = _SectionHeader(section.title, section.collapsed)
        content = QWidget(self._container)
        content.setObjectName("propSection")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        for row in section.rows:
            row_widget = _RowWidget(row)
            row_widget.edited.connect(self._on_row_edited)
            row_widget.button_clicked.connect(self._on_row_button)
            row_widget.keyframe_clicked.connect(self._on_keyframe)
            content_layout.addWidget(row_widget)
            self._rows[row.id] = row_widget
        content_layout.addStretch(1)

        header.toggled.connect(content.setVisible)
        content.setVisible(header.isChecked())

        index = 2 * len(self._sections)
        self._layout.insertWidget(index, header)
        self._layout.insertWidget(index + 1, content)
        self._sections.append((header, content))

    def _on_row_edited(self, row_id: str, value: Any) -> None:
        if self._sheet is not None:
            self._sheet.commit(row_id, value)
        self.row_edited.emit(row_id, value)

    def _on_row_button(self, row_id: str) -> None:
        if self._sheet is not None:
            self._sheet.activate(row_id)
        self.row_button.emit(row_id)

    def _on_keyframe(self, row_id: str) -> None:
        self.keyframe_clicked.emit(row_id)
