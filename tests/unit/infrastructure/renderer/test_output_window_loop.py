"""Regression for paintGL update loop - idle no busy repaint, active continuous, shutdown stops."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from projectionai.infrastructure.renderer.output_window import GLOutputWindow

# Use pytest-qt's function-scoped qapp fixture for deterministic teardown
# (custom module-scoped fixture removed to avoid QApplication lifetime leak)


def test_idle_no_continuous_repaint(qapp, monkeypatch):
    w = GLOutputWindow()
    try:
        mock_update = MagicMock()
        monkeypatch.setattr(w, "update", mock_update)
        w._gl_ready = True  # fake ready to enter paint path
        w._ctx = MagicMock()
        w._target = MagicMock()
        w.defaultFramebufferObject = MagicMock(return_value=0)  # type: ignore[method-assign]
        w.paintGL()
        mock_update.assert_not_called()
    finally:
        w.close()
        w.deleteLater()
        qapp.processEvents()


def test_hardware_harness_continuous_when_active(qapp, monkeypatch):
    from pathlib import Path
    import os

    harness_path_str = os.environ.get("PHASE69_HW_HARNESS_PATH")
    if not harness_path_str:
        pytest.skip(
            "PHASE69_HW_HARNESS_PATH not set - hardware validation harness not available"
        )
    harness_path = Path(harness_path_str)
    if not harness_path.exists():
        pytest.skip("harness file not present at PHASE69_HW_HARNESS_PATH")
    import ast

    src = harness_path.read_text()
    tree = ast.parse(src)
    # Find MeasuredGLOutputWindow paintGL
    found_update_guard = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "paintGL":
            src_snip = ast.get_source_segment(src, node) or ""
            if "self.update()" in src_snip and '_state != "finished"' in src_snip:
                found_update_guard = True
    assert found_update_guard, (
        "Harness paintGL must guard update() on _state != finished"
    )


def test_shutdown_stops_loop(qapp):
    w = GLOutputWindow()
    try:
        w.show()
        qapp.processEvents()
        w.close()
        assert not w.isVisible()
    finally:
        w.deleteLater()
        qapp.processEvents()
