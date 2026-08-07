"""Property sheet model — Qt-free data behind the property editor widget.

The Inspector, Project Properties, Timeline Properties, and Output
Settings panels all render a :class:`PropertySheet`: an ordered list
of collapsible sections, each holding rows of typed properties.
Values are stored in the sheet itself (editable by the widget), so
the model is unit-testable without Qt.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

#: Value-kind discriminator for a property row.
Kind = Literal["text", "int", "float", "bool", "choice", "color", "label", "button"]

ChangeHandler = Callable[[str, Any], None]  # (row_id, new_value)


@dataclass
class PropertyRow:
    """A single editable property."""

    id: str
    label: str
    value: Any = ""
    kind: Kind = "text"
    #: Choices for ``kind == "choice"`` (label -> value pairs).
    choices: list[tuple[str, str]] = field(default_factory=list)
    #: Minimum/maximum for numeric kinds.
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    #: Help text shown in the row tooltip.
    help: str = ""
    #: Row is read-only (displayed but not editable).
    read_only: bool = False
    #: Action callback for ``kind == "button"``.
    action: Callable[[], None] | None = None


@dataclass
class PropertySection:
    """A collapsible group of rows."""

    title: str
    rows: list[PropertyRow] = field(default_factory=list)
    collapsed: bool = False


class PropertySheet:
    """Ordered sections of typed properties.

    Emits ``changed(row_id, value)`` when the widget commits an edit,
    and ``requested(row_id)`` when a button row is activated.
    """

    def __init__(self, title: str = "Properties") -> None:
        self.title: str = title
        self._sections: list[PropertySection] = []
        self._change_handlers: list[ChangeHandler] = []
        self._request_handlers: list[Callable[[str], None]] = []

    # -- Observation --------------------------------------------------------

    def on_changed(self, handler: ChangeHandler) -> None:
        """Register a handler for value edits: ``(row_id, new_value)``."""
        if handler not in self._change_handlers:
            self._change_handlers.append(handler)

    def on_requested(self, handler: Callable[[str], None]) -> None:
        """Register a handler for button activations: ``(row_id)``."""
        if handler not in self._request_handlers:
            self._request_handlers.append(handler)

    def off_changed(self, handler: ChangeHandler) -> None:
        """Remove a previously registered change handler."""
        if handler in self._change_handlers:
            self._change_handlers.remove(handler)

    def off_requested(self, handler: Callable[[str], None]) -> None:
        """Remove a previously registered request handler."""
        if handler in self._request_handlers:
            self._request_handlers.remove(handler)

    def _changed(self, row_id: str, value: Any) -> None:
        for handler in list(self._change_handlers):
            handler(row_id, value)

    def _requested(self, row_id: str) -> None:
        for handler in list(self._request_handlers):
            handler(row_id)

    # -- Structure ----------------------------------------------------------

    @property
    def sections(self) -> list[PropertySection]:
        return list(self._sections)

    def add_section(self, title: str, collapsed: bool = False) -> PropertySection:
        """Append a section and return it."""
        section = PropertySection(title=title, collapsed=collapsed)
        self._sections.append(section)
        return section

    def add_row(self, section: PropertySection, row: PropertyRow) -> PropertyRow:
        """Append a row to a section and return it."""
        section.rows.append(row)
        return row

    def clear(self) -> None:
        """Remove every section."""
        self._sections.clear()

    def row(self, row_id: str) -> PropertyRow | None:
        """Find a row by id across all sections."""
        for section in self._sections:
            for row in section.rows:
                if row.id == row_id:
                    return row
        return None

    def set_value(self, row_id: str, value: Any) -> None:
        """Programmatically update a row's value (no change notification)."""
        row = self.row(row_id)
        if row is not None:
            row.value = value

    def commit(self, row_id: str, value: Any) -> None:
        """Update a row's value and notify listeners (widget edit path)."""
        row = self.row(row_id)
        if row is None or row.read_only:
            return
        if row.kind in ("int", "float"):
            # Numeric rows accept only values matching their declared kind:
            # booleans and non-numeric values are rejected outright, non-finite
            # floats (inf/NaN) are rejected before any conversion, and "int"
            # rows additionally reject fractional values. Integers bypass the
            # finiteness check (arbitrary precision, always finite). Rejected
            # values are dropped before assignment and notification.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return
            if isinstance(value, float) and not math.isfinite(value):
                return
            if row.kind == "int" and value != int(value):
                return
            if row.minimum is not None:
                value = max(value, row.minimum)
            if row.maximum is not None:
                value = min(value, row.maximum)
        row.value = value
        self._changed(row_id, value)

    def activate(self, row_id: str) -> None:
        """Trigger a button row's action and notify listeners."""
        row = self.row(row_id)
        if row is None or row.kind != "button":
            return
        if row.action is not None:
            with contextlib.suppress(Exception):
                row.action()
        self._requested(row_id)

    # -- Convenience builders ------------------------------------------------

    def add_text(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: str = "",
        *,
        read_only: bool = False,
        help: str = "",
    ) -> PropertyRow:
        """Add a text row."""
        return self.add_row(
            section,
            PropertyRow(
                id=row_id,
                label=label,
                value=value,
                kind="text",
                read_only=read_only,
                help=help,
            ),
        )

    def add_int(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: int = 0,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
        step: int = 1,
        help: str = "",
    ) -> PropertyRow:
        """Add an integer row."""
        return self.add_row(
            section,
            PropertyRow(
                id=row_id,
                label=label,
                value=value,
                kind="int",
                minimum=minimum,
                maximum=maximum,
                step=float(step),
                help=help,
            ),
        )

    def add_float(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: float = 0.0,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        step: float = 0.1,
        help: str = "",
    ) -> PropertyRow:
        """Add a float row."""
        return self.add_row(
            section,
            PropertyRow(
                id=row_id,
                label=label,
                value=value,
                kind="float",
                minimum=minimum,
                maximum=maximum,
                step=step,
                help=help,
            ),
        )

    def add_bool(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: bool = False,
        help: str = "",
    ) -> PropertyRow:
        """Add a boolean row."""
        return self.add_row(
            section,
            PropertyRow(id=row_id, label=label, value=value, kind="bool", help=help),
        )

    def add_choice(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: str = "",
        choices: list[tuple[str, str]] | None = None,
        help: str = "",
    ) -> PropertyRow:
        """Add a combo-box row. ``choices`` is ``(display, value)`` pairs."""
        return self.add_row(
            section,
            PropertyRow(
                id=row_id,
                label=label,
                value=value,
                kind="choice",
                choices=list(choices or []),
                help=help,
            ),
        )

    def add_color(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: str = "#FF9E00",
        help: str = "",
    ) -> PropertyRow:
        """Add a color row (hex string value)."""
        return self.add_row(
            section,
            PropertyRow(id=row_id, label=label, value=value, kind="color", help=help),
        )

    def add_label(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        value: str = "",
        help: str = "",
    ) -> PropertyRow:
        """Add a read-only label row."""
        return self.add_row(
            section,
            PropertyRow(
                id=row_id,
                label=label,
                value=value,
                kind="label",
                read_only=True,
                help=help,
            ),
        )

    def add_button(
        self,
        section: PropertySection,
        row_id: str,
        label: str,
        action: Callable[[], None] | None = None,
        help: str = "",
    ) -> PropertyRow:
        """Add an action button row."""
        return self.add_row(
            section,
            PropertyRow(
                id=row_id,
                label=label,
                value="",
                kind="button",
                action=action,
                help=help,
            ),
        )
