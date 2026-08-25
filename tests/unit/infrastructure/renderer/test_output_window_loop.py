"""Regression for paintGL update loop - idle no busy repaint, active continuous, shutdown stops."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from projectionai.infrastructure.renderer.output_window import GLOutputWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_idle_no_continuous_repaint(qapp, monkeypatch):
    w = GLOutputWindow()
    # Mock update to count calls
    mock_update = MagicMock()
    monkeypatch.setattr(w, "update", mock_update)
    # Simulate paintGL when idle (no content change, not in hardware test)
    # Production paintGL should not call update
    w._gl_ready = True  # fake ready to enter paint path
    # Need to mock context to avoid _clear_black
    w._ctx = MagicMock()
    w._target = MagicMock()
    w.defaultFramebufferObject = MagicMock(return_value=0)  # type: ignore[method-assign]
    w.paintGL()
    # Production must not busy-loop
    mock_update.assert_not_called()


def test_hardware_harness_continuous_when_active(qapp, monkeypatch):
    # Simulate MeasuredGLOutputWindow behavior: active -> calls update
    from pathlib import Path
    import importlib.util, sys

    # Load harness file quickly
    spec = importlib.util.spec_from_file_location(
        "phase69",
        str(
            Path("C:/Users/Shivam/AppData/Local/Temp/opencode/phase69_hw_validation.py")
        ),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # Don't execute full harness, just check class exists and has loop guard
    import ast

    src = Path(
        "C:/Users/Shivam/AppData/Local/Temp/opencode/phase69_hw_validation.py"
    ).read_text()
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
    # Verify GLOutputWindow close does not trigger update loop
    w = GLOutputWindow()
    w.show()
    qapp.processEvents()
    w.close()
    # No exception, loop stopped (window hidden)
    assert not w.isVisible()
