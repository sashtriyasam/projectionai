"""Tests for GizmoManager — gizmo lifecycle and mode switching."""

from __future__ import annotations

import numpy as np

from projectionai.editor.gizmo_manager import (
    GizmoManager,
    RotateGizmo,
    ScaleGizmo,
    TranslateGizmo,
)
from projectionai.editor.types import GizmoDomain, TransformMode


def test_default_state() -> None:
    mgr = GizmoManager()
    assert mgr.mode == TransformMode.NONE
    assert mgr.domain == GizmoDomain.TRANSFORM
    assert mgr.active_gizmo is None


def test_set_mode() -> None:
    mgr = GizmoManager()
    mgr.mode = TransformMode.TRANSLATE
    assert mgr.mode == TransformMode.TRANSLATE
    assert isinstance(mgr.active_gizmo, TranslateGizmo)


def test_gizmo_instances_are_cached() -> None:
    mgr = GizmoManager()
    mgr.mode = TransformMode.TRANSLATE
    g1 = mgr.active_gizmo
    g2 = mgr.active_gizmo
    assert g1 is g2


def test_rotate_gizmo() -> None:
    mgr = GizmoManager()
    mgr.mode = TransformMode.ROTATE
    assert isinstance(mgr.active_gizmo, RotateGizmo)


def test_scale_gizmo() -> None:
    mgr = GizmoManager()
    mgr.mode = TransformMode.SCALE
    assert isinstance(mgr.active_gizmo, ScaleGizmo)


def test_domain_switch() -> None:
    mgr = GizmoManager()
    assert mgr.domain == GizmoDomain.TRANSFORM
    mgr.domain = GizmoDomain.CALIBRATION
    assert mgr.domain == GizmoDomain.CALIBRATION


def test_custom_gizmo_registration() -> None:
    mgr = GizmoManager()
    gizmo = TranslateGizmo()
    mgr.register_gizmo("custom_move", gizmo)
    assert "custom_move" in mgr.custom_gizmos
    assert mgr.get_custom_gizmo("custom_move") is gizmo


def test_custom_gizmo_unregister() -> None:
    mgr = GizmoManager()
    gizmo = TranslateGizmo()
    mgr.register_gizmo("test", gizmo)
    mgr.unregister_gizmo("test")
    assert "test" not in mgr.custom_gizmos


def test_hit_test_no_gizmo() -> None:
    mgr = GizmoManager()
    origin = np.zeros(3, dtype=np.float64)
    direction = np.array([0.0, 0.0, -1.0], dtype=np.float64)
    hit, dist = mgr.hit_test_active(origin, direction)
    assert not hit
    assert dist == 0.0


def test_update_selection() -> None:
    mgr = GizmoManager()
    mgr.update_selection(frozenset({"a", "b"}))
    # Just ensure it doesn't crash
    assert mgr._selected_ids == {"a", "b"}


def test_gizmo_interaction_lifecycle() -> None:
    mgr = GizmoManager()
    mgr.mode = TransformMode.TRANSLATE
    origin = np.zeros(3, dtype=np.float64)
    direction = np.array([0.0, 0.0, -1.0], dtype=np.float64)

    # Start / update / end should not crash
    mgr.interaction_start(origin, direction)
    result = mgr.interaction_update(origin, direction)
    assert result is None  # stub gizmo returns None
    mgr.interaction_end()


def test_translate_gizmo_own_domain() -> None:
    gizmo = TranslateGizmo()
    assert gizmo.domain == GizmoDomain.TRANSFORM


def test_rotate_gizmo_own_domain() -> None:
    gizmo = RotateGizmo()
    assert gizmo.domain == GizmoDomain.TRANSFORM


def test_scale_gizmo_own_domain() -> None:
    gizmo = ScaleGizmo()
    assert gizmo.domain == GizmoDomain.TRANSFORM
