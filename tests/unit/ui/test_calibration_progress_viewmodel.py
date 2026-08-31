"""Tests for CalibrationProgressViewModel — display facade over ProductionWorkflow.

The viewmodel is Qt-free; tests drive real ``ProductionWorkflow`` instances
(no mocks) and assert only on the viewmodel's public, machine-readable
properties. All state setup uses direct field assignment or the workflow's
own ``_set_stage`` API, matching the style of
``tests/unit/application/test_calibration_workflow.py``.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from projectionai.application.calibration_workflow import (
    ProductionWorkflow,
    StageStatus,
    WorkflowState,
    _WORKFLOW_STAGE_ORDER,
)
from projectionai.ui.viewmodels.calibration_progress import (
    _STAGE_STATUS_DISPLAY,
    CalibrationProgressViewModel,
)


@pytest.fixture
def workflow() -> ProductionWorkflow:
    return ProductionWorkflow()


@pytest.fixture
def vm(workflow: ProductionWorkflow) -> CalibrationProgressViewModel:
    return CalibrationProgressViewModel(workflow)


def test_initial_idle_state(vm: CalibrationProgressViewModel) -> None:
    assert vm.workflow_state == "Idle"
    assert vm.current_stage == ""
    assert vm.stage_status == "PENDING"


def test_stage_transition_rendering(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.state = WorkflowState.CAPTURING
    workflow._set_stage("capture", StageStatus.RUNNING, 0.5)
    assert vm.workflow_state == "Capturing patterns"
    assert vm.current_stage == "Capture"
    assert vm.stage_status == "RUNNING"


def test_progress_zero_to_one(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    assert vm.overall_progress == 0.0
    for sid in _WORKFLOW_STAGE_ORDER:
        workflow._set_stage(sid, StageStatus.DONE, 1.0)
    assert vm.overall_progress == 1.0


def test_stage_completion(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    # DONE is a terminal stage status, so the "active" stage moves on; the
    # completion is observable via progress contribution and the DONE->COMPLETE
    # display mapping the widget relies on.
    assert _STAGE_STATUS_DISPLAY[StageStatus.DONE] == "COMPLETE"
    workflow._set_stage("prepare", StageStatus.DONE, 1.0)
    assert vm.overall_progress == pytest.approx(1.0 / len(_WORKFLOW_STAGE_ORDER))
    assert vm.stage_status == "PENDING"  # no RUNNING/FAILED stage remains


def test_warning_display(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.warning = "storage path not set"
    assert "storage path not set" in vm.warnings


def test_hardware_pending_passthrough(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    gates = ("optical closure", "settle-time", "repeatability")
    workflow.hardware_pending = gates
    assert vm.hardware_pending == gates


def test_cancellation_flags(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.state = WorkflowState.CANCELLED
    assert vm.can_cancel is False
    assert vm.can_retry is False
    assert vm.stage_status == "CANCELLED"


def test_failure_flags(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.state = WorkflowState.FAILED
    assert vm.can_retry is True
    assert vm.can_cancel is False


def test_retry_availability(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    assert vm.can_retry is False  # IDLE
    workflow.state = WorkflowState.FAILED
    assert vm.can_retry is True


def test_eta_unavailable(vm: CalibrationProgressViewModel) -> None:
    # No stages started -> progress 0 and elapsed 0 -> no ETA.
    assert vm.estimated_remaining is None


def test_eta_available(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.state = WorkflowState.CAPTURING
    workflow._set_stage("capture", StageStatus.RUNNING, 1.0)
    # Pin started_at deterministically so elapsed is a fixed positive span.
    sr = workflow.stages["capture"]
    assert sr.started_at is not None
    workflow.stages["capture"] = replace(sr, started_at=time.time() - 10.0)

    eta = vm.estimated_remaining
    assert eta is not None
    assert isinstance(eta, float)
    assert eta > 0.0


def test_workflow_reset_clears_display(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.state = WorkflowState.FAILED
    workflow.error = "solve exploded"
    workflow.warning = "degenerate geometry"
    workflow._set_stage("solve", StageStatus.FAILED, 0.0, error="solve exploded")

    workflow.reset()

    assert vm.workflow_state == "Idle"
    assert vm.current_stage == ""
    assert vm.stage_status == "PENDING"
    assert vm.overall_progress == 0.0
    assert vm.warnings == []
    assert vm.errors == []
    assert vm.can_retry is False


def test_set_workflow_swaps_observed_workflow(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    workflow.state = WorkflowState.FAILED
    assert vm.workflow_state == "Failed"

    other = ProductionWorkflow()
    revision_before = vm.revision
    vm.set_workflow(other)

    assert vm.workflow_state == "Idle"
    assert vm.can_retry is False
    assert vm.revision > revision_before


def test_refresh_bumps_revision(vm: CalibrationProgressViewModel) -> None:
    before = vm.revision
    vm.refresh()
    assert vm.revision == before + 1
    vm.refresh()
    assert vm.revision == before + 2


# ---------------------------------------------------------------------------
# Gate 8 — Error category preserves original exception context
# ---------------------------------------------------------------------------


def test_error_category_maps_known_patterns(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    """error_category returns the correct label for known error substrings."""
    workflow._set_stage(
        "decode", StageStatus.FAILED, 0.0, error="No valid correspondences"
    )
    assert vm.error_category == "DECODE_ERROR"

    workflow.reset()
    workflow._set_stage(
        "reconstruct", StageStatus.FAILED, 0.0, error="Too few correspondences"
    )
    assert vm.error_category == "RECONSTRUCTION_ERROR"

    workflow.reset()
    workflow._set_stage(
        "solve", StageStatus.FAILED, 0.0, error="No reconstructions provided"
    )
    assert vm.error_category == "SOLVER_ERROR"

    workflow.reset()
    workflow._set_stage(
        "solve", StageStatus.FAILED, 0.0, error="near-degenerate geometry"
    )
    assert vm.error_category == "DEGENERATE_GEOMETRY"

    workflow.reset()
    workflow._set_stage("prepare", StageStatus.FAILED, 0.0, error="cancelled")
    assert vm.error_category == "CANCELLED"


def test_error_category_empty_when_no_errors(vm: CalibrationProgressViewModel) -> None:
    """error_category is empty string when no errors exist."""
    assert vm.error_category == ""


def test_error_category_unknown_for_unmapped(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    """error_category returns UNKNOWN_ERROR for unmapped error messages."""
    workflow._set_stage(
        "decode", StageStatus.FAILED, 0.0, error="Something completely new"
    )
    assert vm.error_category == "UNKNOWN_ERROR"


def test_error_category_preserves_original_exception(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    """error_category does NOT consume the original exception; error string is preserved."""
    original_msg = "No valid correspondences found in decode"
    workflow._set_stage("decode", StageStatus.FAILED, 0.0, error=original_msg)
    # Category is derived from the error string
    assert vm.error_category == "DECODE_ERROR"
    # The original error string is still accessible
    assert vm.errors[0] == original_msg


def test_error_category_first_error_wins(
    vm: CalibrationProgressViewModel, workflow: ProductionWorkflow
) -> None:
    """error_category categorizes based on the first error, not later ones."""
    workflow._set_stage(
        "prepare", StageStatus.FAILED, 0.0, error="Hardware-pending device"
    )
    workflow._set_stage(
        "decode", StageStatus.FAILED, 0.0, error="No valid correspondences"
    )
    assert vm.error_category == "HARDWARE_PENDING"
    assert len(vm.errors) == 2
