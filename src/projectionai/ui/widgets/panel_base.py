"""Panel base widget — shared structure for all dock panels.

Every panel exposes a stable ``panel_id`` (used by the workspace
system), an optional view model reference, and a convenience
``refresh()`` hook. Panels are plain :class:`QWidget` subclasses;
the :class:`MainWindow` wraps them in :class:`QDockWidget` instances
registered under the same id.

``run_async`` schedules an async view-model call on the application's
event loop. The app boots under ``anyio.run`` (asyncio) with
``qapp.exec()`` nested inside it, so ``ensure_future`` is safe from Qt
callbacks; in offscreen tests with no running loop it falls back to
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from PySide6.QtWidgets import QWidget

from projectionai.ui.theme import PANEL_BG

_LOGGER = logging.getLogger(__name__)

#: Strong references to in-flight fire-and-forget tasks so they are not
#: garbage-collected mid-await (see ``run_async``).
_FOREGROUND_TASKS: set[asyncio.Future[Any]] = set()


def _on_task_done(task: asyncio.Future[Any]) -> None:
    """Drop the task from the keep-alive set and surface failures."""
    _FOREGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception as exc:
        _LOGGER.exception("Async panel task failed: %s", exc)


def run_async(coro: Coroutine[Any, Any, Any]) -> None:
    """Schedule *coro* on the running loop, or run it synchronously.

    Fire-and-forget: the view model calls ``_notify()`` after the
    awaited mutation, which wakes the panel's subscription handler.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    task = asyncio.ensure_future(coro)
    _FOREGROUND_TASKS.add(task)
    task.add_done_callback(_on_task_done)


class PanelWidget(QWidget):
    """Base class for all dockable panels."""

    #: Stable identifier used by the workspace/dock persistence system.
    panel_id: str = "panel"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(self.panel_id)
        self._viewmodel: Any | None = None

    # -- View model ---------------------------------------------------------

    @property
    def viewmodel(self) -> Any | None:
        """Return the bound view model, if any."""
        return self._viewmodel

    def bind_viewmodel(self, viewmodel: Any) -> None:
        """Attach a view model and refresh the panel."""
        self._viewmodel = viewmodel
        self.refresh()

    # -- Refresh ------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the view model and rebuild panel content.

        Called on bind and on workspace/state changes. Subclasses
        override this to populate their widgets.
        """

    def clear(self) -> None:
        """Drop all panel content (e.g., project closed)."""

    # -- Styling helper -----------------------------------------------------

    @staticmethod
    def panel_stylesheet() -> str:
        """Return the base panel background stylesheet."""
        return f"QWidget {{ background-color: {PANEL_BG}; }}"
