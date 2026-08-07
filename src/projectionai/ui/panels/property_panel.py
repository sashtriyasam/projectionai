"""PropertyPanel — base for sheet-driven right-dock panels.

Panels that render a :class:`PropertySheet` through the shared
:class:`PropertyEditorWidget` (Project Properties, Timeline Properties,
Output Settings) share this base: it binds one view model, builds the
sheet once, pushes view-model values into the sheet on every refresh,
and routes committed row edits back through ``apply_row``.

The sheet is built once (not on every refresh) so that typing in a text
field or dragging a spin box never destroys the editor mid-interaction;
``sync_sheet`` + ``editor.refresh()`` only re-read values without
rebuilding widgets.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QVBoxLayout

from projectionai.ui.panels.base import ViewModelPanel
from projectionai.ui.viewmodels.properties import PropertySheet
from projectionai.ui.widgets.property_editor import PropertyEditorWidget


class PropertyPanel(ViewModelPanel):
    """One PropertyEditorWidget whose sheet mirrors a view model."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.editor = PropertyEditorWidget()
        self.editor.row_edited.connect(self._on_row_edited)
        root.addWidget(self.editor)

    # -- Subclass contract ----------------------------------------------------

    def build_sheet(self) -> PropertySheet:
        """Return a freshly built sheet (called on first refresh)."""
        return PropertySheet(self.panel_id)

    def sync_sheet(self, sheet: PropertySheet) -> None:
        """Push current view-model values into *sheet* rows."""

    def apply_row(self, row_id: str, value: Any) -> None:
        """Commit an edited row value to the view model."""

    # -- Refresh --------------------------------------------------------------

    def refresh(self) -> None:
        """Build the sheet once, then mirror view-model values into it."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            sheet = self.editor.sheet
            if sheet is None:
                sheet = self.build_sheet()
                self.editor.set_sheet(sheet)
            self.sync_sheet(sheet)
            self.editor.refresh()
        finally:
            self._refreshing = False

    def clear(self) -> None:
        """Drop the bound sheet."""
        self.editor.set_sheet(None)

    # -- Row edits ------------------------------------------------------------

    def _on_row_edited(self, row_id: str, value: Any) -> None:
        self.apply_row(row_id, value)
