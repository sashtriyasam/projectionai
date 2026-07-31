"""Tests for EditorPreferences — serialisable editor settings."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from projectionai.editor.editor_preferences import EditorPreferences
from projectionai.editor.events import EditorEventBus, EditorPreferenceChanged


def test_defaults() -> None:
    prefs = EditorPreferences()
    assert prefs.get("show_grid") is True
    assert prefs.get("show_axes") is True
    assert prefs.get("snap_enabled") is False
    assert prefs.get("snap_translation") == 0.25
    assert prefs["background_color"] == [0.1, 0.1, 0.1]


def test_set_and_get() -> None:
    prefs = EditorPreferences()
    prefs.set("show_grid", False)
    assert prefs.get("show_grid") is False


def test_set_unknown_key() -> None:
    prefs = EditorPreferences()
    prefs.set("unknown_key", "value")
    assert prefs.get("unknown_key") == "value"


def test_contains() -> None:
    prefs = EditorPreferences()
    assert "show_grid" in prefs
    assert "nonexistent" not in prefs


def test_dict_access() -> None:
    prefs = EditorPreferences()
    assert prefs["snap_translation"] == 0.25
    prefs["snap_translation"] = 0.5
    assert prefs["snap_translation"] == 0.5


def test_persistence() -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        path = Path(f.name)
        json.dump({"show_grid": False, "snap_enabled": True}, f)

    try:
        prefs = EditorPreferences(path=path)
        assert prefs.get("show_grid") is False
        assert prefs.get("snap_enabled") is True
        # Defaults still apply for unset keys
        assert prefs.get("show_axes") is True
    finally:
        path.unlink(missing_ok=True)


def test_save_persists() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "prefs.json"
        prefs = EditorPreferences(path=path)
        prefs.set("show_axes", False)

        # Read the file directly
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["show_axes"] is False
        assert loaded["show_grid"] is True  # default


def test_reset_to_defaults() -> None:
    prefs = EditorPreferences()
    prefs.set("show_grid", False)
    prefs.set("snap_translation", 5.0)

    prefs.reset_to_defaults()
    assert prefs.get("show_grid") is True
    assert prefs.get("snap_translation") == 0.25


def test_load_corrupted_file() -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        path = Path(f.name)
        f.write("{invalid json")

    try:
        # Should fall back to defaults without crashing
        prefs = EditorPreferences(path=path)
        assert prefs.get("show_grid") is True
    finally:
        path.unlink(missing_ok=True)


def test_set_same_value_no_event() -> None:
    """Setting the same value should not emit a change event."""
    bus = EditorEventBus()
    events: list[EditorPreferenceChanged] = []
    bus.subscribe(EditorPreferenceChanged, lambda ev: events.append(ev))  # type: ignore[arg-type]
    prefs = EditorPreferences(event_bus=bus)
    prefs.set("show_grid", True)  # already default
    assert len(events) == 0
    assert prefs.get("show_grid") is True


def test_unknown_key_contains() -> None:
    prefs = EditorPreferences()
    assert "nonexistent_key" not in prefs
    prefs.set("nonexistent_key", 42)
    assert "nonexistent_key" in prefs
