"""Tests for PreviewWidget — button enable/disable, refresh, signal emission."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from projectionai.domain.warp_mesh import WarpMesh, WarpMeshGeneration
from projectionai.ui.viewmodels.preview import (
    PreviewContent,
    PreviewState,
    PreviewViewModel,
)
from projectionai.ui.widgets.preview_widget import PreviewWidget


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_valid_warp_mesh() -> WarpMesh:
    vertices = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float64,
    )
    projector_uvs = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float64,
    )
    content_uvs = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float64,
    )
    indices = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
    return WarpMesh(
        surface_id="test_surface",
        projector_id="test_projector",
        vertices=vertices,
        projector_uvs=projector_uvs,
        content_uvs=content_uvs,
        indices=indices,
        grid_rows=1,
        grid_cols=1,
        generation_method=WarpMeshGeneration.GRID,
    )


@pytest.fixture
def vm() -> PreviewViewModel:
    return PreviewViewModel()


@pytest.fixture
def widget(qapp, vm: PreviewViewModel) -> Generator[PreviewWidget, None, None]:
    w = PreviewWidget(vm)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_without_error(self, widget: PreviewWidget) -> None:
        assert widget is not None

    def test_initial_state_label(self, widget: PreviewWidget) -> None:
        assert widget._status_label.text() == "IDLE"

    def test_initial_content_label(self, widget: PreviewWidget) -> None:
        assert widget._content_label.text() == "IDENTITY"

    def test_error_hidden_initially(self, widget: PreviewWidget) -> None:
        assert widget._error_label.isHidden()


# ---------------------------------------------------------------------------
# Button enable/disable by state
# ---------------------------------------------------------------------------


class TestButtonStates:
    def test_idle_buttons(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        widget.refresh()
        assert vm.state == PreviewState.IDLE
        assert widget._start_btn.isEnabled() is False
        assert widget._stop_btn.isEnabled() is False
        assert widget._freeze_btn.isEnabled() is False
        assert widget._blackout_btn.isEnabled() is False
        assert widget._reset_btn.isEnabled() is False

    def test_ready_buttons(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._warp_mesh = _make_valid_warp_mesh()
        widget.refresh()
        assert widget._start_btn.isEnabled() is True
        assert widget._stop_btn.isEnabled() is False
        assert widget._freeze_btn.isEnabled() is False
        assert widget._blackout_btn.isEnabled() is True
        assert widget._reset_btn.isEnabled() is False

    def test_running_buttons(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        widget.refresh()
        assert widget._start_btn.isEnabled() is False
        assert widget._stop_btn.isEnabled() is True
        assert widget._freeze_btn.isEnabled() is True
        assert widget._blackout_btn.isEnabled() is True
        assert widget._reset_btn.isEnabled() is False

    def test_frozen_buttons(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        widget.refresh()
        assert widget._start_btn.isEnabled() is False
        assert widget._stop_btn.isEnabled() is True
        assert widget._freeze_btn.isEnabled() is False
        assert widget._blackout_btn.isEnabled() is True

    def test_error_buttons(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        widget.refresh()
        assert widget._reset_btn.isEnabled() is True
        assert widget._start_btn.isEnabled() is False


# ---------------------------------------------------------------------------
# Button actions
# ---------------------------------------------------------------------------


class TestButtonActions:
    def test_start_emits_signal(
        self, widget: PreviewWidget, vm: PreviewViewModel
    ) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        spy = MagicMock()
        widget.preview_started.connect(spy)
        widget._on_start()
        spy.assert_called_once()
        assert vm.state == PreviewState.RUNNING

    def test_stop_emits_signal(
        self, widget: PreviewWidget, vm: PreviewViewModel
    ) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        spy = MagicMock()
        widget.preview_stopped.connect(spy)
        widget._on_stop()
        spy.assert_called_once()
        assert vm.state == PreviewState.READY

    def test_freeze(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        widget._on_freeze()
        assert vm.state == PreviewState.FROZEN

    def test_blackout(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        widget._on_blackout()
        assert vm.state == PreviewState.BLACKOUT

    def test_reset(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        widget._on_reset()
        assert vm.state == PreviewState.IDLE

    def test_close_emits_signal(
        self, widget: PreviewWidget, vm: PreviewViewModel
    ) -> None:
        spy = MagicMock()
        widget.preview_closed.connect(spy)
        widget._on_close()
        spy.assert_called_once()
        assert vm.state == PreviewState.CLOSED

    def test_cycle(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        assert vm.content == PreviewContent.IDENTITY
        widget._on_cycle()
        widget.refresh()
        assert vm.content == PreviewContent.CHECKERBOARD
        assert "CHECKERBOARD" in widget._content_label.text()


# ---------------------------------------------------------------------------
# Refresh / diagnostics display
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_diag_labels_populated(
        self, widget: PreviewWidget, vm: PreviewViewModel
    ) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._warp_mesh = _make_valid_warp_mesh()
        from projectionai.ui.viewmodels.preview import MeshDiagnostics

        vm._diagnostics = MeshDiagnostics(vm._warp_mesh)
        vm._revision += 1
        widget.refresh()
        assert "4" in widget._diag_verts.text()
        assert "2" in widget._diag_faces.text()
        assert "1x1" in widget._diag_grid.text()

    def test_error_displayed(self, widget: PreviewWidget, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        vm._error = "boom"
        vm._revision += 1
        widget.refresh()
        assert widget._error_label.text() == "Error: boom"
        # isVisible() may return False in headless Qt; check text presence
        assert "boom" in widget._error_label.text()

    def test_no_diag_when_none(
        self, widget: PreviewWidget, vm: PreviewViewModel
    ) -> None:
        widget.refresh()
        assert "—" in widget._diag_verts.text()

    def test_revision_skips_rebuild(
        self, widget: PreviewWidget, vm: PreviewViewModel
    ) -> None:
        widget._last_revision = vm.revision
        # Should not update labels
        widget._status_label.setText("OLD")
        widget.refresh()
        assert widget._status_label.text() == "OLD"
