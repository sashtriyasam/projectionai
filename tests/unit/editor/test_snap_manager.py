"""Tests for SnapManager — graphics-independent snapping logic."""

from __future__ import annotations

import pytest

from projectionai.editor.snap_manager import SnapManager
from projectionai.editor.types import SnapMode


def test_snap_disabled() -> None:
    mgr = SnapManager()
    mgr.enabled = False
    assert mgr.snap_value(1.234, SnapMode.TRANSLATION) == 1.234


def test_snap_translation_default() -> None:
    mgr = SnapManager()
    mgr.enabled = True
    # Default increment is 0.25
    assert mgr.snap_translation_value(1.3) == pytest.approx(1.25)
    assert mgr.snap_translation_value(1.4) == pytest.approx(1.5)
    assert mgr.snap_translation_value(0.0) == pytest.approx(0.0)
    assert mgr.snap_translation_value(2.0) == pytest.approx(2.0)


def test_snap_rotation_default() -> None:
    mgr = SnapManager()
    mgr.enabled = True
    # Default increment is 15 degrees
    assert mgr.snap_rotation_value(10.0) == pytest.approx(15.0)
    assert mgr.snap_rotation_value(20.0) == pytest.approx(15.0)
    assert mgr.snap_rotation_value(30.0) == pytest.approx(30.0)
    assert mgr.snap_rotation_value(0.0) == pytest.approx(0.0)


def test_snap_scale_default() -> None:
    mgr = SnapManager()
    mgr.enabled = True
    # Default increment is 0.1
    assert mgr.snap_scale_value(0.55) == pytest.approx(0.6)
    assert mgr.snap_scale_value(0.54) == pytest.approx(0.5)
    assert mgr.snap_scale_value(1.0) == pytest.approx(1.0)


def test_custom_increment() -> None:
    mgr = SnapManager()
    mgr.enabled = True
    mgr.translation = 1.0
    assert mgr.snap_translation_value(1.3) == pytest.approx(1.0)
    assert mgr.snap_translation_value(1.6) == pytest.approx(2.0)

    mgr.rotation = 45.0
    assert mgr.snap_rotation_value(30.0) == pytest.approx(45.0)
    assert mgr.snap_rotation_value(90.0) == pytest.approx(90.0)

    mgr.scale = 0.5
    assert mgr.snap_scale_value(0.6) == pytest.approx(0.5)
    assert mgr.snap_scale_value(1.0) == pytest.approx(1.0)
    assert mgr.snap_scale_value(1.3) == pytest.approx(1.5)


def test_snap_vector() -> None:
    mgr = SnapManager()
    mgr.enabled = True
    mgr.translation = 1.0
    result = mgr.snap_vector([1.3, 2.7, 0.4], SnapMode.TRANSLATION)
    assert result == [1.0, 3.0, 0.0]


def test_toggle() -> None:
    mgr = SnapManager()
    assert not mgr.enabled
    mgr.toggle()
    assert mgr.enabled
    mgr.toggle()
    assert not mgr.enabled


def test_presets() -> None:
    mgr = SnapManager()
    mgr.enabled = True

    mgr.set_preset("fine")
    assert mgr.translation == 0.05
    assert mgr.rotation == 5.0
    assert mgr.scale == 0.01

    mgr.set_preset("coarse")
    assert mgr.translation == 1.0
    assert mgr.rotation == 45.0
    assert mgr.scale == 0.5


def test_snap_disabled_still_returns_input() -> None:
    mgr = SnapManager()
    mgr.enabled = False
    assert mgr.snap_rotation_value(17.3) == 17.3
    assert mgr.snap_translation_value(0.77) == 0.77


def test_snap_value_general() -> None:
    mgr = SnapManager()
    mgr.enabled = True
    assert mgr.snap_value(1.234, SnapMode.TRANSLATION) == 1.25
    assert mgr.snap_value(17.3, SnapMode.ROTATION) == 15.0


def test_clamp_increments() -> None:
    mgr = SnapManager()
    mgr.translation = 0.0  # should be clamped to 0.001
    assert mgr.translation == 0.001

    mgr.rotation = 0.0
    assert mgr.rotation == 0.1

    mgr.scale = 0.0
    assert mgr.scale == 0.001
