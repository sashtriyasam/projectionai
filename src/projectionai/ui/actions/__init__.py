"""UI actions package — central action registry, menus, toolbar, command palette.

Every ``QAction`` in the editor is owned by :class:`Actions`; the menus and
toolbar are assembled from the same registry so the command palette and
shortcuts reference share one source of truth.
"""

from projectionai.ui.actions.actions import Actions
from projectionai.ui.actions.command_palette import CommandPaletteDialog

__all__ = ["Actions", "CommandPaletteDialog"]
