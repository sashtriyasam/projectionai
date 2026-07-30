"""Selection manager — tracks selected objects with history support."""

from __future__ import annotations

from collections.abc import Iterable

from projectionai.editor.events import EditorEventBus, SelectionChanged
from projectionai.editor.types import SelectionMode, SelectionState


class SelectionManager:
    """Manages object selection in the viewport.

    Supports single-click selection, multi-selection (toggle, add),
    box selection, and a simple selection history stack for cycling
    through previously selected objects.

    The manager is graphics-independent. It only tracks object IDs
    (strings). Hit-testing is performed by the viewport controller
    before calling selection methods.
    """

    def __init__(self, event_bus: EditorEventBus | None = None) -> None:
        self._event_bus = event_bus
        self._selected: set[str] = set()
        self._active: str | None = None  # last-clicked / primary selection
        self._history: list[str] = []  # ordered by selection time (newest last)
        self._max_history: int = 64

    # -- Properties ---------------------------------------------------------

    @property
    def selected(self) -> frozenset[str]:
        """Frozenset of currently selected object IDs."""
        return frozenset(self._selected)

    @property
    def active(self) -> str | None:
        """The active (primary) selection, or ``None``."""
        return self._active

    @property
    def count(self) -> int:
        """Number of selected objects."""
        return len(self._selected)

    @property
    def is_empty(self) -> bool:
        """``True`` if nothing is selected."""
        return len(self._selected) == 0

    @property
    def state(self) -> SelectionState:
        """Snapshot of the current selection state."""
        return SelectionState(
            object_ids=set(self._selected),
            active_id=self._active,
        )

    # -- Selection operations -----------------------------------------------

    def select(
        self,
        object_id: str,
        mode: SelectionMode = SelectionMode.REPLACE,
    ) -> None:
        """Select a single object.

        Args:
            object_id: The object to select.
            mode: How to combine with the current selection.
        """
        if mode == SelectionMode.REPLACE:
            self._selected.clear()
            self._selected.add(object_id)
            self._active = object_id
        elif mode == SelectionMode.ADD:
            self._selected.add(object_id)
            self._active = object_id
        elif mode == SelectionMode.TOGGLE:
            if object_id in self._selected:
                self._selected.discard(object_id)
                if self._active == object_id:
                    self._active = next(
                        (
                            oid
                            for oid in reversed(self._history)
                            if oid in self._selected
                        ),
                        None,
                    )
            else:
                self._selected.add(object_id)
                self._active = object_id

        self._record_history(object_id)
        self._emit()

    def deselect(self, object_id: str) -> None:
        """Deselect a single object."""
        self._selected.discard(object_id)
        if self._active == object_id:
            self._active = next(
                (oid for oid in reversed(self._history) if oid in self._selected),
                None,
            )
        self._emit()

    def select_multiple(
        self,
        object_ids: Iterable[str],
        mode: SelectionMode = SelectionMode.REPLACE,
    ) -> None:
        """Select multiple objects at once.

        Args:
            object_ids: Objects to select.
            mode: How to combine with current selection.
        """
        ids = list(object_ids)
        if not ids:
            if mode == SelectionMode.REPLACE:
                self.clear()
            return

        if mode == SelectionMode.REPLACE:
            self._selected = set(ids)
            self._active = ids[-1]
        elif mode == SelectionMode.ADD:
            self._selected.update(ids)
            self._active = ids[-1]
        elif mode == SelectionMode.TOGGLE:
            for oid in ids:
                if oid in self._selected:
                    self._selected.discard(oid)
                else:
                    self._selected.add(oid)
            self._active = (
                ids[-1]
                if ids[-1] in self._selected
                else next(iter(self._selected), None)
            )

        for oid in ids:
            self._record_history(oid)
        self._emit()

    def clear(self) -> None:
        """Clear the entire selection."""
        self._selected.clear()
        self._active = None
        self._emit()

    def set_active(self, object_id: str) -> None:
        """Change the active (primary) selection without changing the set.

        Args:
            object_id: Must already be in the selection set.
        """
        if object_id in self._selected:
            self._active = object_id
            self._emit()

    # -- History ------------------------------------------------------------

    def previous_selection(self) -> str | None:
        """Cycle to the previously selected object in history.

        Returns:
            The previous object ID, or ``None`` if history is empty.
        """
        if not self._history:
            return None
        if self._active is None:
            prev = self._history[-1]
        else:
            try:
                idx = self._history.index(self._active)
            except ValueError:
                prev = self._history[-1]
            else:
                prev = self._history[idx - 1]
        self._selected = {prev}
        self._active = prev
        self._emit()
        return prev

    # -- Queries ------------------------------------------------------------

    def is_selected(self, object_id: str) -> bool:
        """Check if an object is currently selected."""
        return object_id in self._selected

    def any_selected(self, object_ids: Iterable[str]) -> bool:
        """Check if any of the given objects are selected."""
        return any(oid in self._selected for oid in object_ids)

    # -- Box selection (graphics independent) -------------------------------

    def box_select(
        self,
        object_ids: Iterable[str],
        contained_ids: Iterable[str],
        mode: SelectionMode = SelectionMode.REPLACE,
    ) -> None:
        """Select objects that fall within a screen-space bounding box.

        Args:
            object_ids: All candidate object IDs in the scene.
            contained_ids: Object IDs that passed the containment test
                (computed externally by the viewport).
            mode: How to combine with current selection.
        """
        self.select_multiple(contained_ids, mode=mode)

    # -- Internal -----------------------------------------------------------

    def _record_history(self, object_id: str) -> None:
        """Record an object in the selection history."""
        if object_id in self._history:
            self._history.remove(object_id)
        self._history.append(object_id)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def _emit(self) -> None:
        if self._event_bus:
            self._event_bus.emit(
                SelectionChanged(
                    object_ids=tuple(self._selected) if self._selected else (),
                    active_id=self._active,
                )
            )
