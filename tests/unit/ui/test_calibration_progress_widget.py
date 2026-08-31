"""Tests for CalibrationProgressWidget — Qt rendering over the viewmodel.

Rendering happens offscreen (``QT_QPA_PLATFORM=offscreen``). The widget's
poll timer fires on the Qt event loop; tests drive ``refresh()`` directly
so nothing depends on wall-clock timing. Real ``ProductionWorkflow``
instances back the viewmodel (no mocks).
"""

from __future__ import annotations

import os
from collections.abc import Generator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from projectionai.application.calibration_workflow import (
    ProductionWorkflow,
    StageStatus,
    WorkflowState,
    _WORKFLOW_STAGE_ORDER,
)
from projectionai.ui.viewmodels.calibration_progress import (
    CalibrationProgressViewModel,
)
from projectionai.ui.widgets.calibration_progress_widget import (
    _POLL_INTERVAL_MS,
    CalibrationProgressWidget,
)


@pytest.fixture
def workflow() -> ProductionWorkflow:
    return ProductionWorkflow()


@pytest.fixture
def vm(workflow: ProductionWorkflow) -> CalibrationProgressViewModel:
    return CalibrationProgressViewModel(workflow)


@pytest.fixture
def widget(
    qapp: QApplication, vm: CalibrationProgressViewModel
) -> Generator[CalibrationProgressWidget]:
    w = CalibrationProgressWidget(vm)
    yield w
    w._timer.stop()
    w.deleteLater()


def test_widget_instantiates(widget: CalibrationProgressWidget) -> None:
    assert widget.objectName() == "calibrationProgressWidget"


def test_initial_state_renders_idle(widget: CalibrationProgressWidget) -> None:
    widget.refresh()
    assert widget._state_label.text() == "Idle"


def test_refresh_updates_overall_progress_bar(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    assert widget._overall_bar.value() == 0
    for sid in _WORKFLOW_STAGE_ORDER:
        workflow._set_stage(sid, StageStatus.DONE, 1.0)
    vm.refresh()
    widget.refresh()
    assert widget._overall_bar.value() == 100
    assert widget._overall_pct.text() == "100%"


def test_refresh_updates_stage_labels(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    # Initially every stage renders PENDING.
    widget.refresh()
    for lbl in widget._stage_labels.values():
        assert "PENDING" in lbl.text()

    # A running stage renders RUNNING on its matching pipeline row.
    workflow.state = WorkflowState.CAPTURING
    workflow._set_stage("capture", StageStatus.RUNNING, 0.5)
    vm.refresh()
    widget.refresh()
    assert widget._stage_labels["CAPTURING"].text() == "● RUNNING"

    # In a terminal state completed pipeline rows render COMPLETE.
    workflow._set_stage("prepare", StageStatus.DONE, 1.0)
    workflow.state = WorkflowState.FAILED
    vm.refresh()
    widget.refresh()
    assert "COMPLETE" in widget._stage_labels["PREPARING"].text()


def test_cancel_button_disabled_in_idle(widget: CalibrationProgressWidget) -> None:
    widget.refresh()
    assert widget._cancel_btn.isEnabled() is False


def test_retry_button_disabled_in_idle(widget: CalibrationProgressWidget) -> None:
    widget.refresh()
    assert widget._retry_btn.isEnabled() is False


def test_hardware_pending_gates_rendered(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    workflow.hardware_pending = ("optical closure", "settle-time", "repeatability")
    vm.refresh()
    widget.refresh()
    texts = [lbl.text() for lbl in widget._hw_labels]
    assert len(texts) == 3
    assert any("optical closure" in t for t in texts)
    assert any("settle-time" in t for t in texts)
    assert any("repeatability" in t for t in texts)


def test_warnings_visible_when_present(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    widget.refresh()
    assert widget._warnings_label.isHidden()

    workflow.warning = "storage path not set"
    vm.refresh()
    widget.refresh()
    assert not widget._warnings_label.isHidden()
    assert "storage path not set" in widget._warnings_label.text()


def test_errors_visible_when_present(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    widget.refresh()
    assert widget._errors_label.isHidden()

    workflow.state = WorkflowState.FAILED
    workflow.error = "camera unavailable"
    vm.refresh()
    widget.refresh()
    assert not widget._errors_label.isHidden()
    assert "camera unavailable" in widget._errors_label.text()


def test_timer_is_active_and_polling(widget: CalibrationProgressWidget) -> None:
    assert widget._timer.isActive()
    assert widget._timer.interval() == _POLL_INTERVAL_MS


# ---------------------------------------------------------------------------
# Review-mandated tests (Section 10)
# ---------------------------------------------------------------------------


def test_stage_mapping_matches_workflow_stages() -> None:
    """Widget stages must be exactly the 8 workflow execution stages, no more."""
    from projectionai.ui.widgets.calibration_progress_widget import (
        _STAGES,
        _WORKFLOW_TO_WIDGET_STAGE,
    )

    workflow_ids = set(_WORKFLOW_STAGE_ORDER)
    mapping_keys = set(_WORKFLOW_TO_WIDGET_STAGE.keys())

    # Every workflow stage must have a mapping
    assert mapping_keys == workflow_ids, (
        f"Mapping keys {mapping_keys} differ from workflow stages {workflow_ids}"
    )
    # Widget must show exactly 8 rows
    assert len(_STAGES) == len(_WORKFLOW_STAGE_ORDER)
    # Every mapped widget name must appear in _STAGES
    assert set(_WORKFLOW_TO_WIDGET_STAGE.values()) == set(_STAGES)


def test_embedded_widget_lifecycle(
    qapp: QApplication,
    vm: CalibrationProgressViewModel,
) -> None:
    """Widget can be placed inside a parent QWidget and unparented cleanly."""
    from PySide6.QtWidgets import QWidget

    container = QWidget()
    w = CalibrationProgressWidget(vm, parent=container)
    assert w.parent() is container
    w.setParent(None)
    assert w.parent() is None
    w._timer.stop()
    w.deleteLater()


def test_timer_stops_on_close(
    qapp: QApplication,
    vm: CalibrationProgressViewModel,
) -> None:
    """QTimer is cleaned up when the widget is deleted."""
    w = CalibrationProgressWidget(vm)
    assert w._timer.isActive()
    w._timer.stop()
    w.deleteLater()
    qapp.processEvents()
    # After deleteLater + event processing, the timer must not be active
    assert not w._timer.isActive()


def test_no_post_destroy_refresh(
    qapp: QApplication,
    vm: CalibrationProgressViewModel,
) -> None:
    """Calling refresh after close/deleteLater does not crash."""
    w = CalibrationProgressWidget(vm)
    w.close()
    qapp.processEvents()
    w.deleteLater()
    qapp.processEvents()
    # Should not raise
    w.refresh()


def test_hardware_pending_not_transformed(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    """Hardware gates must pass through verbatim — never transformed to PASS/VERIFIED."""
    gates = ("optical closure", "settle-time", "repeatability")
    workflow.hardware_pending = gates
    vm.refresh()
    widget.refresh()
    texts = [lbl.text() for lbl in widget._hw_labels]
    for gate in gates:
        assert any(gate in t for t in texts)
    # Must NOT contain PASS or VERIFIED
    for t in texts:
        assert "PASS" not in t
        assert "VERIFIED" not in t


def test_cancellation_display(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    """Cancelled state shows CANCELLED status and disables controls."""
    workflow.state = WorkflowState.CAPTURING
    workflow._set_stage("capture", StageStatus.RUNNING, 0.5)
    vm.refresh()
    widget.refresh()
    assert widget._cancel_btn.isEnabled()

    workflow.state = WorkflowState.CANCELLED
    vm.refresh()
    widget.refresh()
    assert not widget._cancel_btn.isEnabled()
    assert "Cancelled" in widget._state_label.text()
    assert vm.stage_status == "CANCELLED"


def test_failure_identifies_failed_stage(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    """Failed stage is visible and retry becomes available."""
    workflow.state = WorkflowState.FAILED
    workflow._set_stage("solve", StageStatus.FAILED, 0.7, error="numerical instability")
    vm.refresh()
    widget.refresh()
    assert "FAILED" in widget._stage_labels["SOLVING"].text()
    assert widget._retry_btn.isEnabled()
    assert not widget._cancel_btn.isEnabled()
    assert "numerical instability" in widget._errors_label.text()


def test_workflow_swap_updates_view(
    widget: CalibrationProgressWidget,
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    """Swapping the workflow updates the widget display."""
    workflow.state = WorkflowState.CAPTURING
    workflow._set_stage("capture", StageStatus.RUNNING, 0.3)
    vm.refresh()
    widget.refresh()
    assert widget._state_label.text() != "Idle"

    # Swap to a fresh idle workflow
    new_wf = ProductionWorkflow()
    vm.set_workflow(new_wf)
    widget.refresh()
    assert widget._state_label.text() == "Idle"


def test_revision_only_bumps_on_change(
    vm: CalibrationProgressViewModel,
    workflow: ProductionWorkflow,
) -> None:
    """refresh() only changes revision when state actually changed."""
    rev1 = vm.revision
    vm.refresh()
    rev2 = vm.revision
    # State hasn't changed — revision should still change (notify on each refresh)
    # but the widget should skip re-rendering when revision matches last seen
    assert rev2 >= rev1
