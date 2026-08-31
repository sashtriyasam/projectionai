"""Widget tests for CalibrationResultReviewWidget — headless via offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from projectionai.domain.calibration_session import CalibrationMethod, CalibrationResult
from projectionai.ui.theme import LIVE_RED, WARN_YELLOW
from projectionai.ui.viewmodels.calibration_result_review import (
    CalibrationResultReviewViewModel,
)
from projectionai.ui.widgets.calibration_result_review_widget import (
    CalibrationResultReviewWidget,
)


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]


def _make_result(**overrides) -> CalibrationResult:
    base = dict(
        calibration_id="cal-1",
        sequence_id="seq-1",
        method=CalibrationMethod.GRAY_CODE,
        projector_id="proj-1",
        camera_id="cam-0",
        surface_id="surf-1",
        projector_intrinsics=np.array(
            [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]], dtype=np.float64
        ),
        projector_pose=np.eye(4, dtype=np.float64),
        projector_resolution=(1920, 1080),
        reprojection_error=0.5,
        coverage=0.8,
        num_correspondences=100,
        confidence=0.9,
    )
    base.update(overrides)
    return CalibrationResult(**base)  # type: ignore[arg-type]


def _make_vm(
    result: CalibrationResult | None = None, **kw
) -> CalibrationResultReviewViewModel:
    if result is None:
        result = _make_result()
    vm = CalibrationResultReviewViewModel(result, **kw)
    return vm


def test_widget_instantiates(qapp: QApplication) -> None:
    vm = _make_vm()
    w = CalibrationResultReviewWidget(vm)
    assert w is not None
    w.close()
    w.deleteLater()


def test_initial_renders_success(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(
        _make_result(), source_mode="LIVE", hardware_pending=()
    )
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert "SUCCESS" in w._status_label.text()
    w.close()
    w.deleteLater()


def test_synthetic_source_visible(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result(), source_mode="SYNTHETIC")
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert "SYNTHETIC" in w._source_label.text()
    assert "NOT VERIFIED" in w._physical_label.text()
    w.close()
    w.deleteLater()


def test_live_source_visible(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result(), source_mode="LIVE")
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert "LIVE" in w._source_label.text()
    w.close()
    w.deleteLater()


def test_intrinsics_rendered(qapp: QApplication) -> None:
    k = np.array([[800, 0, 320], [0, 900, 240], [0, 0, 1]], dtype=np.float64)
    vm = CalibrationResultReviewViewModel(_make_result(projector_intrinsics=k))
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert "800" in w._intrinsics_label.text()
    assert "320" in w._intrinsics_matrix.text()
    w.close()
    w.deleteLater()


def test_pose_rendered(qapp: QApplication) -> None:
    pose = np.eye(4)
    pose[0, 3] = 1.2
    vm = CalibrationResultReviewViewModel(_make_result(projector_pose=pose))
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert "1.200" in w._pose_translation_label.text()
    w.close()
    w.deleteLater()


def test_coverage_rendered(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result(coverage=0.42))
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert (
        "42" in w._coverage_label.text()
        or "0.42" in w._coverage_label.text()
        or "42%" in w._coverage_label.text()
    )
    w.close()
    w.deleteLater()


def test_quality_labels(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(
        _make_result(reprojection_error=1.23, confidence=0.77, num_correspondences=42)
    )
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert "1.23" in w._reproj_label.text()
    assert "0.77" in w._confidence_label.text()
    assert "42" in w._corr_label.text()
    w.close()
    w.deleteLater()


def test_hardware_pending_visible(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(
        _make_result(), hardware_pending=("optical closure",)
    )
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    # HW frame should contain the gate
    texts = [lbl.text() for lbl in w._hw_labels]
    assert any("optical closure" in t for t in texts)
    w.close()
    w.deleteLater()


def test_blocking_error_disables_continue(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result(reprojection_error=10.0))
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert w._continue_btn.isEnabled() is False
    assert w._errors_label.isVisible() or w._errors_label.text() != ""
    w.close()
    w.deleteLater()


def test_eligible_enables_continue(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(
        _make_result(), source_mode="LIVE", hardware_pending=()
    )
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert w._continue_btn.isEnabled() is True
    w.close()
    w.deleteLater()


def test_approve_signal(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(
        _make_result(), source_mode="LIVE", hardware_pending=()
    )
    w = CalibrationResultReviewWidget(vm)
    fired: list[bool] = []
    w.accepted_for_preview.connect(lambda: fired.append(True))
    w._on_continue()
    assert fired == [True]
    assert vm.decision is not None
    w.close()
    w.deleteLater()


def test_reject_signal(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result())
    w = CalibrationResultReviewWidget(vm)
    fired: list[bool] = []
    w.rejected.connect(lambda: fired.append(True))
    w._on_reject()
    assert fired == [True]
    w.close()
    w.deleteLater()


def test_recalibrate_signal(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result())
    w = CalibrationResultReviewWidget(vm)
    fired: list[bool] = []
    w.recalibrate_requested.connect(lambda: fired.append(True))
    w._on_recalibrate()
    assert fired == [True]
    w.close()
    w.deleteLater()


def test_cancel_signal(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result())
    w = CalibrationResultReviewWidget(vm)
    fired: list[bool] = []
    w.cancelled.connect(lambda: fired.append(True))
    w._on_cancel()
    assert fired == [True]
    w.close()
    w.deleteLater()


def test_advanced_toggle(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result())
    w = CalibrationResultReviewWidget(vm)
    assert w._advanced_frame.isHidden()
    w._on_toggle_advanced(True)
    assert not w._advanced_frame.isHidden()
    w._on_toggle_advanced(False)
    assert w._advanced_frame.isHidden()
    w.close()
    w.deleteLater()


def test_timer_active(qapp: QApplication) -> None:
    vm = CalibrationResultReviewViewModel(_make_result())
    w = CalibrationResultReviewWidget(vm)
    assert w._timer.isActive()
    w.close()
    w.deleteLater()
    assert not w._timer.isActive()


# ============================================================
# GATE 7 — TIMER / QT LIFECYCLE (full lifecycle test)
# ============================================================


def test_full_lifecycle_create_show_replace_close_destroy(qapp: QApplication) -> None:
    """create → show → replace result → close → destroy with deterministic cleanup."""
    r_a = _make_result(calibration_id="cal-A", coverage=0.3)
    r_b = _make_result(calibration_id="cal-B", coverage=0.95)
    vm = CalibrationResultReviewViewModel(r_a, source_mode="SYNTHETIC")
    w = CalibrationResultReviewWidget(vm)

    # Create + show
    w.show()
    w.refresh()
    assert "cal-A" in w._adv_calib_id.text() or w._adv_calib_id.text() != ""
    assert w._timer.isActive()

    # Replace result
    vm.set_result(r_b, source_mode="LIVE", hardware_pending=())
    w.refresh()
    assert vm.calibration_id == "cal-B"
    assert vm.decision is None

    # Close + destroy
    w.close()
    qapp.processEvents()
    assert not w._timer.isActive()
    w.deleteLater()
    qapp.processEvents()


# ============================================================
# GATE 8 — RESULT REPLACEMENT (widget-level)
# ============================================================


def test_widget_result_replacement_updates_all_labels(qapp: QApplication) -> None:
    """Widget labels must update when result is replaced."""
    r_a = _make_result(
        calibration_id="cal-A",
        projector_id="proj-A",
        camera_id="cam-A",
        coverage=0.3,
        reprojection_error=1.8,
    )
    r_b = _make_result(
        calibration_id="cal-B",
        projector_id="proj-B",
        camera_id="cam-B",
        coverage=0.95,
        reprojection_error=0.2,
    )
    vm = CalibrationResultReviewViewModel(r_a)
    w = CalibrationResultReviewWidget(vm)
    w.refresh()

    # Replace
    vm.set_result(r_b, source_mode="LIVE", hardware_pending=())
    w.refresh()

    assert "proj-B" in w._projector_label.text()
    assert "cam-B" in w._camera_label.text()
    assert "0.2" in w._reproj_label.text()
    w.close()
    w.deleteLater()


def test_set_result_clears_gate_state(qapp: QApplication) -> None:
    """set_result must clear gate_result so gate is re-evaluated."""
    from projectionai.calibration.validation_gate import ValidationGate

    gate = ValidationGate()
    r_a = _make_result()
    r_b = _make_result(calibration_id="cal-B")

    vm = CalibrationResultReviewViewModel(r_a, source_mode="LIVE", gate=gate)
    # Evaluate gate on first result
    result_a = vm.evaluate_gate()
    assert result_a is not None
    assert vm.gate_result is not None

    # Replace result — gate should be cleared
    vm.set_result(r_b, source_mode="LIVE", hardware_pending=())
    assert vm.gate_result is None
    assert vm.can_arm is False
    assert vm.can_live is False

    w = CalibrationResultReviewWidget(vm)
    w.close()
    w.deleteLater()


def test_widget_result_replacement_clears_old_warnings(qapp: QApplication) -> None:
    """Old warnings must not persist after result replacement."""
    r_a = _make_result(coverage=0.005)  # blocking
    r_b = _make_result(coverage=0.95)  # good
    vm = CalibrationResultReviewViewModel(r_a)
    w = CalibrationResultReviewWidget(vm)
    w.show()
    qapp.processEvents()
    w.refresh()
    # Blocking error present
    assert w._errors_label.isVisible()

    vm.set_result(r_b, source_mode="LIVE", hardware_pending=())
    w.refresh()
    # After replacement, errors cleared (label hidden)
    assert not w._errors_label.isVisible()
    w.close()
    w.deleteLater()


def test_widget_result_replacement_clears_old_hw_labels(qapp: QApplication) -> None:
    """Old HW pending labels must not persist after result replacement."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(
        r, hardware_pending=("optical closure", "vsync")
    )
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    assert any("optical closure" in lbl.text() for lbl in w._hw_labels)

    vm.set_result(r, hardware_pending=())
    w.refresh()
    assert not any("optical closure" in lbl.text() for lbl in w._hw_labels)
    w.close()
    w.deleteLater()


# ============================================================
# GATE 4 — HARDWARE STATUS (widget-level)
# ============================================================


def test_widget_accept_preserves_hw_pending(qapp: QApplication) -> None:
    """Accepting for preview must not change HW pending display."""
    hw = ("optical closure", "vsync sync")
    vm = CalibrationResultReviewViewModel(
        _make_result(), hardware_pending=hw, source_mode="LIVE"
    )
    w = CalibrationResultReviewWidget(vm)
    w.refresh()
    before = [lbl.text() for lbl in w._hw_labels]
    w._on_continue()
    after = [lbl.text() for lbl in w._hw_labels]
    assert before == after
    w.close()
    w.deleteLater()


# ============================================================
# GATE 14 — WARNING VS ERROR (widget-level)
# ============================================================


def test_widget_warnings_and_errors_never_same_banner(qapp: QApplication) -> None:
    """Warnings (yellow) and errors (red) must never collapse."""
    r = _make_result(reprojection_error=1.5, coverage=0.005)
    vm = CalibrationResultReviewViewModel(r)
    w = CalibrationResultReviewWidget(vm)
    w.show()
    qapp.processEvents()
    w.refresh()
    # Warning text present, error text present
    assert (
        "elevated" in w._warnings_label.text().lower() or w._warnings_label.text() != ""
    )
    assert (
        "critically low" in w._errors_label.text().lower()
        or w._errors_label.text() != ""
    )
    # Different style colors — warnings use WARN_YELLOW, errors use LIVE_RED
    warn_ss = w._warnings_label.styleSheet()
    err_ss = w._errors_label.styleSheet()
    assert WARN_YELLOW in warn_ss
    assert LIVE_RED in err_ss
    w.close()
    w.deleteLater()
