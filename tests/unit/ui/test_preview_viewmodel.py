"""Tests for PreviewViewModel — state machine, transitions, mesh diagnostics, safety boundaries."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from projectionai.domain.warp_mesh import WarpMesh, WarpMeshGeneration
from projectionai.ui.viewmodels.preview import (
    MeshDiagnostics,
    PreviewContent,
    PreviewState,
    PreviewViewModel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_valid_warp_mesh() -> WarpMesh:
    """Create a minimal valid WarpMesh for testing."""
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


def _make_nan_warp_mesh() -> WarpMesh:
    """Create a WarpMesh with NaN values for diagnostics testing."""
    mesh = _make_valid_warp_mesh()
    verts = mesh.vertices.copy()
    verts[0, 0] = float("nan")
    return WarpMesh(
        surface_id=mesh.surface_id,
        projector_id=mesh.projector_id,
        vertices=verts,
        projector_uvs=mesh.projector_uvs,
        content_uvs=mesh.content_uvs,
        indices=mesh.indices,
        grid_rows=mesh.grid_rows,
        grid_cols=mesh.grid_cols,
        generation_method=mesh.generation_method,
    )


@pytest.fixture
def vm() -> PreviewViewModel:
    return PreviewViewModel()


# ---------------------------------------------------------------------------
# State model tests
# ---------------------------------------------------------------------------


class TestPreviewState:
    def test_initial_state(self, vm: PreviewViewModel) -> None:
        assert vm.state == PreviewState.IDLE

    def test_initial_revision(self, vm: PreviewViewModel) -> None:
        assert vm.revision == 0

    def test_initial_content(self, vm: PreviewViewModel) -> None:
        assert vm.content == PreviewContent.IDENTITY

    def test_label_returns_uppercase(self, vm: PreviewViewModel) -> None:
        assert vm.label == "IDLE"


class TestStateTransitions:
    def test_idle_to_loading(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        assert vm.state == PreviewState.LOADING
        assert vm.revision == 1

    def test_loading_to_ready(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        assert vm.state == PreviewState.READY
        assert vm.revision == 2

    def test_loading_to_error(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        assert vm.state == PreviewState.ERROR

    def test_ready_to_running(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.state == PreviewState.RUNNING

    def test_running_to_frozen(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        assert vm.state == PreviewState.FROZEN

    def test_frozen_to_running(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        vm._transition(PreviewState.RUNNING)
        assert vm.state == PreviewState.RUNNING

    def test_running_to_blackout(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.BLACKOUT)
        assert vm.state == PreviewState.BLACKOUT

    def test_blackout_to_running(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.BLACKOUT)
        vm._transition(PreviewState.RUNNING)
        assert vm.state == PreviewState.RUNNING

    def test_invalid_transition_raises(self, vm: PreviewViewModel) -> None:
        with pytest.raises(ValueError, match="Invalid preview transition"):
            vm._transition(PreviewState.RUNNING)  # can't go from IDLE to RUNNING

    def test_invalid_idle_to_ready_raises(self, vm: PreviewViewModel) -> None:
        with pytest.raises(ValueError, match="Invalid preview transition"):
            vm._transition(PreviewState.READY)  # must go through LOADING

    def test_closed_is_terminal(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.CLOSED)
        assert vm.state == PreviewState.CLOSED
        # No transitions out of CLOSED
        with pytest.raises(ValueError, match="Invalid preview transition"):
            vm._transition(PreviewState.IDLE)


class TestTransitionCallbacks:
    def test_handler_called_on_transition(self, vm: PreviewViewModel) -> None:
        handler = MagicMock()
        vm.subscribe(handler)
        vm._transition(PreviewState.LOADING)
        handler.assert_called_once_with(PreviewState.IDLE, PreviewState.LOADING)

    def test_multiple_handlers_called(self, vm: PreviewViewModel) -> None:
        h1 = MagicMock()
        h2 = MagicMock()
        vm.subscribe(h1)
        vm.subscribe(h2)
        vm._transition(PreviewState.LOADING)
        h1.assert_called_once()
        h2.assert_called_once()

    def test_unsubscribe_removes_handler(self, vm: PreviewViewModel) -> None:
        handler = MagicMock()
        vm.subscribe(handler)
        vm.unsubscribe(handler)
        vm._transition(PreviewState.LOADING)
        handler.assert_not_called()

    def test_close_idempotent(self, vm: PreviewViewModel) -> None:
        vm.close()
        assert vm.state == PreviewState.CLOSED
        vm.close()  # should not raise
        assert vm.state == PreviewState.CLOSED


# ---------------------------------------------------------------------------
# Action tests
# ---------------------------------------------------------------------------


class TestStart:
    def test_start_from_ready(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        assert vm.start() is True
        assert vm.state == PreviewState.RUNNING

    def test_start_from_idle_fails(self, vm: PreviewViewModel) -> None:
        assert vm.start() is False
        assert vm.state == PreviewState.IDLE

    def test_start_from_running_fails(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.start() is False


class TestStop:
    def test_stop_from_running(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.stop() is True
        assert vm.state == PreviewState.READY

    def test_stop_from_frozen(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        assert vm.stop() is True
        assert vm.state == PreviewState.READY

    def test_stop_from_blackout(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.BLACKOUT)
        assert vm.stop() is True
        assert vm.state == PreviewState.READY

    def test_stop_from_idle_fails(self, vm: PreviewViewModel) -> None:
        assert vm.stop() is False


class TestFreeze:
    def test_freeze_from_running(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.freeze() is True
        assert vm.state == PreviewState.FROZEN

    def test_freeze_from_ready_fails(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        assert vm.freeze() is False


class TestUnfreeze:
    def test_unfreeze_from_frozen(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        assert vm.unfreeze() is True
        assert vm.state == PreviewState.RUNNING

    def test_unfreeze_from_running_fails(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.unfreeze() is False


class TestBlackout:
    def test_blackout_from_running(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.blackout() is True
        assert vm.state == PreviewState.BLACKOUT

    def test_blackout_from_frozen(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        assert vm.blackout() is True
        assert vm.state == PreviewState.BLACKOUT

    def test_blackout_from_ready(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        assert vm.blackout() is True
        assert vm.state == PreviewState.BLACKOUT

    def test_blackout_from_idle_fails(self, vm: PreviewViewModel) -> None:
        assert vm.blackout() is False


class TestUnblackout:
    def test_unblackout_from_blackout(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.BLACKOUT)
        assert vm.unblackout() is True
        assert vm.state == PreviewState.RUNNING

    def test_unblackout_from_running_fails(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.unblackout() is False


class TestReset:
    def test_reset_from_error(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        assert vm.reset() is True
        assert vm.state == PreviewState.IDLE
        assert vm.warp_mesh is None
        assert vm.projection_mapping is None
        assert vm.diagnostics is None
        assert vm.error is None
        assert vm.calibration_result is None

    def test_reset_from_idle_fails(self, vm: PreviewViewModel) -> None:
        assert vm.reset() is False


# ---------------------------------------------------------------------------
# Content management tests
# ---------------------------------------------------------------------------


class TestContent:
    def test_set_content(self, vm: PreviewViewModel) -> None:
        vm.set_content(PreviewContent.CHECKERBOARD)
        assert vm.content == PreviewContent.CHECKERBOARD

    def test_cycle_content(self, vm: PreviewViewModel) -> None:
        assert vm.content == PreviewContent.IDENTITY
        vm.cycle_content()
        assert vm.content == PreviewContent.CHECKERBOARD

    def test_cycle_content_wraps_around(self, vm: PreviewViewModel) -> None:
        contents = list(PreviewContent)
        for _ in range(len(contents)):
            vm.cycle_content()
        assert vm.content == PreviewContent.IDENTITY


# ---------------------------------------------------------------------------
# is_active / is_displayable
# ---------------------------------------------------------------------------


class TestIsActive:
    def test_idle_not_active(self, vm: PreviewViewModel) -> None:
        assert vm.is_active is False

    def test_ready_active(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        assert vm.is_active is True

    def test_running_active(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        assert vm.is_active is True

    def test_frozen_active(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.FROZEN)
        assert vm.is_active is True

    def test_blackout_active(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        vm._transition(PreviewState.RUNNING)
        vm._transition(PreviewState.BLACKOUT)
        assert vm.is_active is True


class TestIsDisplayable:
    def test_not_displayable_when_idle(self, vm: PreviewViewModel) -> None:
        assert vm.is_displayable is False

    def test_not_displayable_after_manual_transition(
        self, vm: PreviewViewModel
    ) -> None:
        """Without a real CalibrationResult, displayable stays False."""
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.READY)
        # No mesh was built, so is_displayable is False
        assert vm.is_displayable is False


# ---------------------------------------------------------------------------
# MeshDiagnostics tests
# ---------------------------------------------------------------------------


class TestMeshDiagnostics:
    def test_valid_mesh(self) -> None:
        mesh = _make_valid_warp_mesh()
        diag = MeshDiagnostics(mesh)
        assert diag.is_valid is True
        assert diag.vertex_count == 4
        assert diag.face_count == 2
        assert diag.grid_rows == 1
        assert diag.grid_cols == 1
        assert diag.has_nan is False
        assert diag.has_inf is False

    def test_nan_mesh_invalid(self) -> None:
        mesh = _make_nan_warp_mesh()
        diag = MeshDiagnostics(mesh)
        assert diag.is_valid is False
        assert diag.has_nan is True

    def test_summary_ok(self) -> None:
        mesh = _make_valid_warp_mesh()
        diag = MeshDiagnostics(mesh)
        s = diag.summary()
        assert "OK" in s
        assert "4 verts" in s
        assert "2 faces" in s

    def test_summary_invalid(self) -> None:
        mesh = _make_nan_warp_mesh()
        diag = MeshDiagnostics(mesh)
        s = diag.summary()
        assert "INVALID" in s

    def test_empty_mesh(self) -> None:
        mesh = WarpMesh()
        diag = MeshDiagnostics(mesh)
        assert diag.is_valid is False
        assert diag.vertex_count == 0
        assert diag.face_count == 0


# ---------------------------------------------------------------------------
# update_from_workflow tests (mocked calibration_to_warp_mesh)
# ---------------------------------------------------------------------------


class TestUpdateFromWorkflow:
    def test_none_result_goes_to_error(self, vm: PreviewViewModel) -> None:
        vm.update_from_workflow(None)
        assert vm.state == PreviewState.ERROR
        assert vm.error == "No calibration result provided"

    @patch(
        "projectionai.ui.viewmodels.preview.calibration_to_warp_mesh",
        side_effect=RuntimeError("mesh fail"),
    )
    def test_mesh_build_failure_goes_to_error(
        self, mock_mesh: MagicMock, vm: PreviewViewModel
    ) -> None:
        result = MagicMock()
        result.calibration_id = "cal1"
        vm.update_from_workflow(result)
        assert vm.state == PreviewState.ERROR
        assert "mesh fail" in (vm.error or "")

    def test_update_ignored_when_not_idle(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        vm.reset()  # back to IDLE
        vm._transition(PreviewState.LOADING)
        # Now in LOADING — update should be ignored
        result = MagicMock()
        vm.update_from_workflow(result)
        assert vm.state == PreviewState.LOADING  # unchanged

    def test_reset_clears_mesh_and_mapping(self, vm: PreviewViewModel) -> None:
        vm._transition(PreviewState.LOADING)
        vm._transition(PreviewState.ERROR)
        # Manually set mesh/mapping to non-None
        vm._warp_mesh = _make_valid_warp_mesh()
        vm._projection_mapping = MagicMock()
        vm.reset()
        assert vm.warp_mesh is None
        assert vm.projection_mapping is None
        assert vm.diagnostics is None


# ---------------------------------------------------------------------------
# Safety boundary tests — preview must NOT call OutputManager
# ---------------------------------------------------------------------------


class TestSafetyBoundaries:
    def test_no_output_manager_import(self) -> None:
        """preview.py must not import or call OutputManager."""
        import projectionai.ui.viewmodels.preview as mod

        with open(mod.__file__) as f:
            source = f.read()
        # Only check for actual import/usage lines, not docstring mentions
        import_lines = [
            line
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        for line in import_lines:
            assert "OutputManager" not in line
            assert "go_live" not in line
            assert ".arm(" not in line

    def test_label_and_color(self, vm: PreviewViewModel) -> None:
        assert isinstance(vm.label, str)
        assert isinstance(vm.color, str)
        assert len(vm.color) > 0
