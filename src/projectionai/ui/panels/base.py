"""ViewModelPanel — PanelWidget base with automatic view-model binding.

All dock panels share the same observation pattern: their Qt-free
view models expose ``subscribe(handler)`` / ``unsubscribe(handler)``,
so this base attaches a refresh handler on bind and detaches it on
unbind/shutdown. Subclasses only implement ``refresh()`` and
``clear()``.
"""

from __future__ import annotations

from typing import Any

from projectionai.ui.widgets.panel_base import PanelWidget


class ViewModelPanel(PanelWidget):
    """PanelWidget that auto-refreshes from a subscribed view model."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._refreshing: bool = False

    # -- View model ---------------------------------------------------------

    def bind_viewmodel(self, viewmodel: Any) -> None:
        """Attach *viewmodel* and subscribe to its change notifications."""
        self.unbind_viewmodel()
        self._viewmodel = viewmodel
        if viewmodel is not None and hasattr(viewmodel, "subscribe"):
            viewmodel.subscribe(self._on_viewmodel_changed)
        self.refresh()

    def unbind_viewmodel(self) -> None:
        """Detach the current view model, if any."""
        if self._viewmodel is not None and hasattr(self._viewmodel, "unsubscribe"):
            self._viewmodel.unsubscribe(self._on_viewmodel_changed)
        self._viewmodel = None

    def shutdown(self) -> None:
        """Detach from the view model and drop all content."""
        self.unbind_viewmodel()
        self.clear()

    def _on_viewmodel_changed(self) -> None:
        """Re-render when the view model notifies (no-op while refreshing)."""
        if self._refreshing:
            return
        self.refresh()
