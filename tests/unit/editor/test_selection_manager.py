"""Tests for SelectionManager — graphics-independent selection logic."""

from __future__ import annotations

import pytest

from projectionai.editor.selection_manager import SelectionManager
from projectionai.editor.types import SelectionMode


def test_single_select() -> None:
    mgr = SelectionManager()
    mgr.select("obj1")
    assert mgr.selected == {"obj1"}
    assert mgr.active == "obj1"
    assert mgr.count == 1


def test_replace_select() -> None:
    mgr = SelectionManager()
    mgr.select("obj1")
    mgr.select("obj2", mode=SelectionMode.REPLACE)
    assert mgr.selected == {"obj2"}
    assert mgr.active == "obj2"


def test_add_select() -> None:
    mgr = SelectionManager()
    mgr.select("obj1")
    mgr.select("obj2", mode=SelectionMode.ADD)
    assert mgr.selected == {"obj1", "obj2"}
    assert mgr.active == "obj2"


def test_toggle_select_add() -> None:
    mgr = SelectionManager()
    mgr.select("obj1")
    mgr.select("obj2", mode=SelectionMode.TOGGLE)
    assert "obj2" in mgr.selected
    assert mgr.active == "obj2"


def test_toggle_select_remove() -> None:
    mgr = SelectionManager()
    mgr.select("obj1")
    mgr.select("obj2", mode=SelectionMode.ADD)
    mgr.select("obj1", mode=SelectionMode.TOGGLE)
    assert mgr.selected == {"obj2"}
    assert mgr.active == "obj2"


def test_deselect() -> None:
    mgr = SelectionManager()
    mgr.select("obj1")
    mgr.deselect("obj1")
    assert mgr.is_empty
    assert mgr.active is None


def test_clear() -> None:
    mgr = SelectionManager()
    mgr.select_multiple(["a", "b", "c"])
    mgr.clear()
    assert mgr.is_empty
    assert mgr.active is None


def test_select_multiple_replace() -> None:
    mgr = SelectionManager()
    mgr.select("old")
    mgr.select_multiple(["a", "b", "c"])
    assert mgr.selected == {"a", "b", "c"}
    assert mgr.active == "c"


def test_select_multiple_add() -> None:
    mgr = SelectionManager()
    mgr.select("a")
    mgr.select_multiple(["b", "c"], mode=SelectionMode.ADD)
    assert mgr.selected == {"a", "b", "c"}


def test_select_multiple_toggle() -> None:
    mgr = SelectionManager()
    mgr.select_multiple(["a", "b", "c"])
    mgr.select_multiple(["b", "d"], mode=SelectionMode.TOGGLE)
    assert mgr.selected == {"a", "c", "d"}


def test_set_active() -> None:
    mgr = SelectionManager()
    mgr.select_multiple(["a", "b"])
    mgr.set_active("a")
    assert mgr.active == "a"


def test_set_active_not_selected() -> None:
    mgr = SelectionManager()
    mgr.select("a")
    mgr.set_active("b")  # not in selection — should be ignored
    assert mgr.active == "a"


def test_is_selected() -> None:
    mgr = SelectionManager()
    mgr.select("a")
    assert mgr.is_selected("a")
    assert not mgr.is_selected("b")


def test_any_selected() -> None:
    mgr = SelectionManager()
    mgr.select("a")
    assert mgr.any_selected(["b", "a"])
    assert not mgr.any_selected(["b", "c"])


def test_empty_initial_state() -> None:
    mgr = SelectionManager()
    assert mgr.is_empty
    assert mgr.active is None
    assert mgr.count == 0
    assert mgr.state.object_ids == set()
    assert mgr.state.active_id is None


def test_box_select_replace() -> None:
    mgr = SelectionManager()
    mgr.select("old")
    all_ids = ["a", "b", "c", "d"]
    contained = ["a", "b"]
    mgr.box_select(all_ids, contained)
    assert mgr.selected == {"a", "b"}
    assert mgr.active == "b"


def test_box_select_add() -> None:
    mgr = SelectionManager()
    mgr.select("c")
    mgr.box_select(["a", "b", "c"], ["a", "b"], mode=SelectionMode.ADD)
    assert mgr.selected == {"c", "a", "b"}


def test_selection_state_snapshot() -> None:
    mgr = SelectionManager()
    mgr.select_multiple(["x", "y"])
    state = mgr.state
    assert state.object_ids == {"x", "y"}
    assert state.active_id == "y"


def test_active_after_toggle_remove() -> None:
    mgr = SelectionManager()
    mgr.select("a")
    mgr.select("b", mode=SelectionMode.ADD)
    mgr.select("b", mode=SelectionMode.TOGGLE)
    assert mgr.active == "a"


def test_active_after_clear() -> None:
    mgr = SelectionManager()
    mgr.select("a")
    mgr.clear()
    assert mgr.active is None
