"""Tests for CalibrationResultReviewViewModel — Qt-free presentation layer."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.domain.calibration_session import CalibrationMethod, CalibrationResult
from projectionai.ui.viewmodels.calibration_result_review import (
    CalibrationResultReviewViewModel,
    ReviewDecision,
)


def _make_result(
    *,
    calibration_id: str = "cal-1",
    sequence_id: str = "seq-1",
    method: CalibrationMethod = CalibrationMethod.GRAY_CODE,
    projector_id: str = "proj-1",
    camera_id: str = "cam-0",
    surface_id: str = "surf-1",
    intrinsics: np.ndarray | None = None,
    pose: np.ndarray | None = None,
    resolution: tuple[int, int] = (1920, 1080),
    reprojection_error: float = 0.5,
    coverage: float = 0.8,
    num_correspondences: int = 100,
    confidence: float = 0.9,
    calibration_sequence_ids: tuple[str, ...] = (),
    per_point_errors: tuple[float, ...] = (),
    metadata: dict | None = None,
) -> CalibrationResult:
    if intrinsics is None:
        intrinsics = np.array(
            [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]], dtype=np.float64
        )
    if pose is None:
        pose = np.eye(4, dtype=np.float64)
        pose[2, 3] = -2.0
    return CalibrationResult(
        calibration_id=calibration_id,
        sequence_id=sequence_id,
        method=method,
        projector_id=projector_id,
        camera_id=camera_id,
        surface_id=surface_id,
        projector_intrinsics=intrinsics,
        projector_pose=pose,
        projector_resolution=resolution,
        reprojection_error=reprojection_error,
        coverage=coverage,
        num_correspondences=num_correspondences,
        confidence=confidence,
        calibration_sequence_ids=calibration_sequence_ids,
        per_point_errors=per_point_errors,
        metadata=metadata or {},
    )


def test_valid_result_has_all_fields() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    assert vm.has_result is True
    assert vm.calibration_id == "cal-1"
    assert vm.projector_id == "proj-1"
    # intrinsics
    assert vm.intrinsics["fx"] == pytest.approx(1000)
    assert vm.intrinsics["fy"] == pytest.approx(1000)
    # pose
    assert vm.pose_frame == "projector → camera"
    # quality
    assert vm.reprojection_error == pytest.approx(0.5)
    assert vm.coverage == pytest.approx(0.8)
    assert vm.confidence == pytest.approx(0.9)


def test_missing_result() -> None:
    vm = CalibrationResultReviewViewModel(None)
    assert vm.has_result is False
    assert vm.calibration_id == ""
    assert vm.status_kind == "FAILED"
    assert vm.eligibility_text == "Not eligible — no result"
    assert vm.blocking_errors == ["No calibration result"]
    assert vm.review_ok is False


def test_synthetic_source_display() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="SYNTHETIC")
    assert vm.source_mode == "SYNTHETIC"
    assert vm.source_label == "SOURCE: SYNTHETIC"
    assert "NOT VERIFIED" in vm.physical_validation_label
    assert any("Synthetic" in w for w in vm.warnings)


def test_replay_source_display() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="REPLAY")
    assert vm.source_mode == "REPLAY"
    assert "REPLAY" in vm.source_label
    assert "NOT VERIFIED" in vm.physical_validation_label


def test_live_source_display() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="LIVE")
    assert vm.source_mode == "LIVE"
    assert vm.source_label == "SOURCE: LIVE"
    assert "PENDING" in vm.physical_validation_label


def test_intrinsics_rendering() -> None:
    k = np.array([[800, 0, 320], [0, 900, 240], [0, 0, 1]], dtype=np.float64)
    r = _make_result(intrinsics=k)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.intrinsics["fx"] == 800
    assert vm.intrinsics["fy"] == 900
    assert vm.intrinsics["cx"] == 320
    assert vm.intrinsics["cy"] == 240
    assert "800" in vm.intrinsics_matrix_text
    assert "900" in vm.intrinsics_matrix_text


def test_pose_rendering() -> None:
    pose = np.eye(4)
    pose[0, 3] = 1.5
    pose[1, 3] = -0.5
    pose[2, 3] = 2.0
    r = _make_result(pose=pose)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.pose_translation == pytest.approx((1.5, -0.5, 2.0))
    assert "1.500" in vm.pose_translation_text
    # matrix text contains translation
    assert "1.5000" in vm.pose_matrix_text


def test_coverage_rendering() -> None:
    r = _make_result(coverage=0.42)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.coverage == pytest.approx(0.42)


def test_confidence_rendering() -> None:
    r = _make_result(confidence=0.77)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.confidence == pytest.approx(0.77)


def test_reprojection_rendering() -> None:
    r = _make_result(reprojection_error=1.23)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.reprojection_error == pytest.approx(1.23)


def test_multi_orientation_summary() -> None:
    r = _make_result(calibration_sequence_ids=("seq-1", "seq-2", "seq-3"))
    vm = CalibrationResultReviewViewModel(r)
    assert vm.orientation_count == 3
    assert vm.orientation_ids == ("seq-1", "seq-2", "seq-3")


def test_per_plane_consistency() -> None:
    r = _make_result(per_point_errors=(0.1, 0.2, 0.5, 1.0))
    vm = CalibrationResultReviewViewModel(r)
    stats = vm.per_point_stats
    assert stats["count"] == 4
    assert stats["mean"] == pytest.approx(0.45)
    assert stats["max"] == pytest.approx(1.0)
    assert stats["rms"] > 0


def test_hardware_pending_display() -> None:
    r = _make_result()
    gates = ("optical closure", "real frameSwapped/vsync")
    vm = CalibrationResultReviewViewModel(r, hardware_pending=gates)
    assert vm.hardware_pending == gates
    assert any("Hardware validation pending" in w for w in vm.warnings)


@pytest.mark.parametrize(
    ("reprojection_error", "expect_blocking", "expect_warnings"),
    [
        (5.0, True, False),  # blocking error
        (1.5, False, True),  # warning only
        (2.5, True, False),  # blocking error
    ],
    ids=["high-reprojection-blocks", "warning-threshold", "error-threshold"],
)
def test_reprojection_thresholds(
    reprojection_error: float,
    expect_blocking: bool,
    expect_warnings: bool,
) -> None:
    r = _make_result(reprojection_error=reprojection_error)
    vm = CalibrationResultReviewViewModel(r)
    if expect_blocking:
        assert any("Reprojection error" in e for e in vm.blocking_errors)
        assert vm.review_ok is False
        assert vm.status_kind == "FAILED"
    else:
        assert vm.blocking_errors == []
    if expect_warnings:
        assert len(vm.warnings) > 0


def test_eligibility_eligible() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="LIVE", hardware_pending=())
    # With LIVE and no HW pending, no source warning, high quality → review_ok
    # But default synthetic will still warn; test with LIVE
    assert vm.review_ok is True
    assert "Eligible" in vm.eligibility_text


def test_eligibility_not_eligible_with_blocking() -> None:
    r = _make_result(reprojection_error=10.0)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.review_ok is False
    assert "Not eligible" in vm.eligibility_text


def test_approve_accept_decision() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    assert vm.decision is None
    vm.accept()
    assert vm.decision == ReviewDecision.ACCEPTED_FOR_PREVIEW


def test_reject_decision() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    vm.reject()
    assert vm.decision == ReviewDecision.REJECTED


def test_recalibration_action() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    vm.needs_recalibration()
    assert vm.decision == ReviewDecision.NEEDS_RECALIBRATION


def test_reset_replacement_with_new_result() -> None:
    r1 = _make_result(calibration_id="cal-1")
    r2 = _make_result(calibration_id="cal-2")
    vm = CalibrationResultReviewViewModel(r1)
    assert vm.calibration_id == "cal-1"
    vm.accept()
    assert vm.decision is not None
    vm.set_result(r2)
    assert vm.calibration_id == "cal-2"
    # decision resets on new result
    assert vm.decision is None


def test_no_result_mutation() -> None:
    r = _make_result(calibration_id="cal-1", reprojection_error=0.5)
    orig_dict = r.to_dict()
    vm = CalibrationResultReviewViewModel(r)
    vm.accept()
    vm.set_source_mode("LIVE")
    vm.set_hardware_pending(("gate",))
    # Original result unchanged
    assert r.to_dict() == orig_dict
    assert r.calibration_id == "cal-1"


def test_no_solver_math_in_viewmodel() -> None:
    """ViewModel must not import or call solver/reconstruction."""
    import inspect

    src = inspect.getsource(CalibrationResultReviewViewModel)
    forbidden = ["solve_calibration", "solvePnP", "reconstruct", "decode", "Zhang"]
    for kw in forbidden:
        assert kw not in src
    # Also check module imports
    import projectionai.ui.viewmodels.calibration_result_review as mod

    mod_src = inspect.getsource(mod)
    for kw in forbidden:
        assert kw not in mod_src


def test_revision_bumps_on_mutation() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    rev = vm.revision
    vm.set_source_mode("LIVE")
    assert vm.revision == rev + 1
    vm.set_hardware_pending(("a",))
    assert vm.revision == rev + 2
    vm.accept()
    assert vm.revision == rev + 3


# ============================================================
# GATE 1 — CANONICAL RESULT IMMUTABILITY (array mutation)
# ============================================================


def test_no_array_mutation_through_vm() -> None:
    """VM must not mutate the result's numpy arrays, even by reference."""
    intr = np.array([[800, 0, 320], [0, 900, 240], [0, 0, 1]], dtype=np.float64)
    pose = np.eye(4, dtype=np.float64)
    pose[2, 3] = -1.5
    r = _make_result(intrinsics=intr, pose=pose)
    orig_intr = intr.copy()
    orig_pose = pose.copy()
    vm = CalibrationResultReviewViewModel(r)
    # Read all array-backed properties
    _ = vm.intrinsics_matrix
    _ = vm.intrinsics_matrix_text
    _ = vm.pose_matrix
    _ = vm.pose_matrix_text
    _ = vm.pose_translation
    _ = vm.pose_quaternion
    vm.accept()
    vm.set_source_mode("LIVE")
    vm.set_hardware_pending(("x",))
    vm.reset_decision()
    vm.needs_recalibration()
    vm.reject()
    # Arrays must be untouched
    assert np.array_equal(r.projector_intrinsics, orig_intr)
    assert np.array_equal(r.projector_pose, orig_pose)


# ============================================================
# GATE 2 — ELIGIBILITY SEMANTICS (critical thresholds)
# ============================================================


def test_high_reprojection_blocks_review() -> None:
    """Reprojection > 2.0 must be blocking — trace to validator max_error=2.0."""
    r = _make_result(reprojection_error=2.5)
    vm = CalibrationResultReviewViewModel(r)
    assert any("Reprojection error" in e for e in vm.blocking_errors)
    assert vm.review_ok is False
    assert vm.status_kind == "FAILED"


def test_warn_reprojection_allows_review() -> None:
    """Reprojection in (1.0, 2.0] is warning-only — trace to validator warn=1.0."""
    r = _make_result(reprojection_error=1.5)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.blocking_errors == []
    assert vm.review_ok is True
    assert any("elevated" in w for w in vm.warnings)


def test_low_coverage_blocks_review() -> None:
    """Coverage < 0.01 must be blocking — trace to _MIN_COVERAGE_ERROR."""
    r = _make_result(coverage=0.005)
    vm = CalibrationResultReviewViewModel(r)
    assert any("critically low" in e for e in vm.blocking_errors)
    assert vm.review_ok is False


def test_warn_coverage_allows_review() -> None:
    """Coverage in [0.01, 0.1) is warning-only — trace to _MIN_COVERAGE_WARN."""
    r = _make_result(coverage=0.05)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.blocking_errors == []
    assert vm.review_ok is True
    assert any("Low coverage" in w for w in vm.warnings)


def test_low_confidence_is_warning_not_blocking() -> None:
    """Confidence < 0.5 is warning-only — canonical ConfidenceCheck returns
    severity='warning', not 'error'. VM must mirror that exactly."""
    r = _make_result(confidence=0.3)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.blocking_errors == []
    assert vm.review_ok is True
    assert any("Low confidence" in w for w in vm.warnings)


def test_zero_correspondences_blocks() -> None:
    """Zero correspondences must block — trace to _MIN_SAMPLES."""
    r = _make_result(num_correspondences=0)
    vm = CalibrationResultReviewViewModel(r)
    assert any("No correspondences" in e for e in vm.blocking_errors)
    assert vm.review_ok is False


def test_few_correspondences_blocks() -> None:
    """< 3 correspondences must block — canonical SampleCountCheck severity='error'."""
    r = _make_result(num_correspondences=2)
    vm = CalibrationResultReviewViewModel(r)
    assert any("correspondences" in e for e in vm.blocking_errors)
    assert vm.review_ok is False


def test_nan_intrinsics_blocks() -> None:
    """NaN in intrinsics must block — trace to PoseSanityCheck semantics."""
    bad = np.array([[np.nan, 0, 960], [0, 1000, 540], [0, 0, 1]], dtype=np.float64)
    r = _make_result(intrinsics=bad)
    vm = CalibrationResultReviewViewModel(r)
    assert any("NaN/Inf" in e for e in vm.blocking_errors)
    assert vm.review_ok is False


def test_nan_pose_blocks() -> None:
    """NaN in pose must block."""
    bad = np.eye(4, dtype=np.float64)
    bad[0, 0] = np.nan
    r = _make_result(pose=bad)
    vm = CalibrationResultReviewViewModel(r)
    assert any("NaN/Inf" in e for e in vm.blocking_errors)
    assert vm.review_ok is False


def test_metadata_blocking_errors_propagate() -> None:
    """metadata['errors'] must become blocking errors."""
    r = _make_result(metadata={"errors": ["solver failed to converge"]})
    vm = CalibrationResultReviewViewModel(r)
    assert any("solver failed" in e for e in vm.blocking_errors)
    assert vm.review_ok is False


def test_metadata_warnings_propagate() -> None:
    """metadata['warnings'] must become warnings."""
    r = _make_result(metadata={"warnings": ["corner detection weak"]})
    vm = CalibrationResultReviewViewModel(r)
    assert any("corner detection" in w for w in vm.warnings)


# ============================================================
# GATE 3 — SOURCE PROVENANCE
# ============================================================


def test_missing_source_defaults_to_synthetic() -> None:
    """Missing/empty source_mode must not claim LIVE."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="")
    assert vm.source_mode == "SYNTHETIC"
    assert "NOT VERIFIED" in vm.physical_validation_label


def test_invalid_source_defaults_to_synthetic() -> None:
    """Unknown source string must not claim LIVE."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="UNKNOWN_MODE")
    assert vm.source_mode == "SYNTHETIC"


def test_synthetic_never_claims_verified() -> None:
    """SYNTHETIC must never display 'PHYSICAL VALIDATION: VERIFIED'."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="SYNTHETIC")
    assert vm.physical_validation_label == "PHYSICAL VALIDATION: NOT VERIFIED"
    assert "NOT VERIFIED" in vm.physical_validation_label


def test_replay_never_claims_verified() -> None:
    """REPLAY must never display 'PHYSICAL VALIDATION: VERIFIED'."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="REPLAY")
    assert vm.physical_validation_label == "PHYSICAL VALIDATION: NOT VERIFIED"


def test_live_source_shows_pending() -> None:
    """LIVE must show PENDING, not VERIFIED."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="LIVE")
    assert "PENDING" in vm.physical_validation_label
    assert "VERIFIED" not in vm.physical_validation_label


def test_set_source_mode_rejects_invalid() -> None:
    """set_source_mode must not allow invalid values to become LIVE."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="LIVE")
    vm.set_source_mode("GARBAGE")
    assert vm.source_mode == "SYNTHETIC"


def test_source_mode_case_insensitive() -> None:
    """Source mode comparison is case-insensitive."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="live")
    assert vm.source_mode == "LIVE"


# ============================================================
# GATE 4 — HARDWARE STATUS
# ============================================================


def test_accept_does_not_change_hardware_pending() -> None:
    """ACCEPTED_FOR_PREVIEW must not alter hardware_pending."""
    hw = ("optical closure", "vsync sync", "buffer policy")
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, hardware_pending=hw)
    vm.accept()
    assert vm.hardware_pending == hw


def test_accept_does_not_change_physical_validation() -> None:
    """ACCEPTED_FOR_PREVIEW must not alter physical_validation_label."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="SYNTHETIC")
    before = vm.physical_validation_label
    vm.accept()
    assert vm.physical_validation_label == before


def test_reject_does_not_change_hardware_pending() -> None:
    """REJECTED must not alter hardware_pending."""
    hw = ("optical closure",)
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, hardware_pending=hw)
    vm.reject()
    assert vm.hardware_pending == hw


# ============================================================
# GATE 5 — REVIEW DECISION LIFECYCLE
# ============================================================


def test_decision_starts_unset() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    assert vm.decision is None


def test_set_result_clears_decision() -> None:
    r1 = _make_result(calibration_id="a")
    r2 = _make_result(calibration_id="b")
    vm = CalibrationResultReviewViewModel(r1)
    vm.accept()
    assert vm.decision == ReviewDecision.ACCEPTED_FOR_PREVIEW
    vm.set_result(r2)
    assert vm.decision is None


def test_reset_clears_decision() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    vm.accept()
    vm.reset_decision()
    assert vm.decision is None


def test_rejected_cannot_retain_accepted() -> None:
    """After reject, decision must be REJECTED, not ACCEPTED_FOR_PREVIEW."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    vm.accept()
    vm.reject()
    assert vm.decision == ReviewDecision.REJECTED


def test_result_replacement_clears_stale_decision() -> None:
    """Replacing result after reject must clear stale decision."""
    r1 = _make_result(calibration_id="a")
    r2 = _make_result(calibration_id="b")
    vm = CalibrationResultReviewViewModel(r1)
    vm.reject()
    vm.set_result(r2)
    assert vm.decision is None
    assert vm.calibration_id == "b"


def test_clear_resets_decision() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    vm.needs_recalibration()
    vm.clear()
    assert vm.decision is None
    assert vm.has_result is False


# ============================================================
# GATE 8 — RESULT REPLACEMENT
# ============================================================


def test_result_replacement_updates_all_metrics() -> None:
    """Replacing result A with B must update all visible metrics."""
    r_a = _make_result(
        calibration_id="cal-A",
        projector_id="proj-A",
        camera_id="cam-A",
        surface_id="surf-A",
        coverage=0.3,
        reprojection_error=1.8,
        confidence=0.4,
        num_correspondences=10,
    )
    r_b = _make_result(
        calibration_id="cal-B",
        projector_id="proj-B",
        camera_id="cam-B",
        surface_id="surf-B",
        coverage=0.95,
        reprojection_error=0.2,
        confidence=0.99,
        num_correspondences=200,
        sequence_id="s1",
        calibration_sequence_ids=("s1", "s2", "s3"),
    )
    vm = CalibrationResultReviewViewModel(r_a)
    vm.accept()
    vm.set_result(r_b, source_mode="LIVE")
    assert vm.calibration_id == "cal-B"
    assert vm.projector_id == "proj-B"
    assert vm.camera_id == "cam-B"
    assert vm.surface_id == "surf-B"
    assert vm.coverage == pytest.approx(0.95)
    assert vm.reprojection_error == pytest.approx(0.2)
    assert vm.confidence == pytest.approx(0.99)
    assert vm.num_correspondences == 200
    assert vm.orientation_count == 3
    assert vm.decision is None


def test_result_replacement_clears_old_warnings() -> None:
    """Old warnings from result A must not persist after replacing with B."""
    r_a = _make_result(coverage=0.05)  # low coverage → warning
    r_b = _make_result(coverage=0.95)  # good coverage → no warning
    vm = CalibrationResultReviewViewModel(r_a)
    assert any("Low coverage" in w for w in vm.warnings)
    vm.set_result(r_b, source_mode="LIVE", hardware_pending=())
    assert not any("Low coverage" in w for w in vm.warnings)


def test_result_replacement_clears_old_errors() -> None:
    """Old blocking errors from result A must not persist after replacing with B."""
    r_a = _make_result(reprojection_error=5.0)  # blocking
    r_b = _make_result(reprojection_error=0.1)  # good
    vm = CalibrationResultReviewViewModel(r_a)
    assert vm.review_ok is False
    vm.set_result(r_b, source_mode="LIVE", hardware_pending=())
    assert vm.review_ok is True


def test_result_replacement_clears_stale_source_labels() -> None:
    """Source labels must reflect new result, not old."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r, source_mode="SYNTHETIC")
    assert "SYNTHETIC" in vm.source_label
    vm.set_result(r, source_mode="LIVE")
    assert "LIVE" in vm.source_label
    assert "SYNTHETIC" not in vm.source_label


def test_result_replacement_clears_stale_hw_labels() -> None:
    """Hardware pending labels must reflect new result."""
    r = _make_result()
    vm = CalibrationResultReviewViewModel(
        r, hardware_pending=("optical closure", "vsync")
    )
    assert len(vm.hardware_pending) == 2
    vm.set_result(r, hardware_pending=())
    assert vm.hardware_pending == ()


# ============================================================
# GATE 9 — METRIC INTEGRITY
# ============================================================


def test_intrinsics_direct_from_result() -> None:
    """fx/fy/cx/cy must come directly from result, no recomputation."""
    k = np.array([[1234.5, 0, 640.1], [0, 1234.5, 360.2], [0, 0, 1]], dtype=np.float64)
    r = _make_result(intrinsics=k)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.intrinsics["fx"] == pytest.approx(1234.5)
    assert vm.intrinsics["fy"] == pytest.approx(1234.5)
    assert vm.intrinsics["cx"] == pytest.approx(640.1)
    assert vm.intrinsics["cy"] == pytest.approx(360.2)


def test_coverage_is_canonical() -> None:
    """Coverage must be unique in-bounds / projector area — no proxy."""
    r = _make_result(coverage=0.73)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.coverage == pytest.approx(0.73)


def test_reprojection_is_canonical() -> None:
    r = _make_result(reprojection_error=1.234)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.reprojection_error == pytest.approx(1.234)


def test_num_correspondences_is_canonical() -> None:
    r = _make_result(num_correspondences=42)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.num_correspondences == 42


def test_per_point_errors_direct_from_result() -> None:
    errs = (0.1, 0.2, 0.3, 0.4, 0.5)
    r = _make_result(per_point_errors=errs)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.per_point_errors == errs


# ============================================================
# GATE 10 — POSE / COORDINATE CONVENTION
# ============================================================


def test_pose_frame_is_projector_to_camera() -> None:
    r = _make_result()
    vm = CalibrationResultReviewViewModel(r)
    assert vm.pose_frame == "projector → camera"


def test_pose_translation_agrees_with_matrix() -> None:
    """Translation must come from pose_matrix columns, not recomputed."""
    pose = np.eye(4, dtype=np.float64)
    pose[0, 3] = 1.5
    pose[1, 3] = -0.5
    pose[2, 3] = 2.0
    r = _make_result(pose=pose)
    vm = CalibrationResultReviewViewModel(r)
    tx, ty, tz = vm.pose_translation
    m = vm.pose_matrix
    assert tx == pytest.approx(float(m[0, 3]))
    assert ty == pytest.approx(float(m[1, 3]))
    assert tz == pytest.approx(float(m[2, 3]))


def test_pose_quaternion_agrees_with_rotation() -> None:
    """Quaternion must represent the rotation part of the pose matrix."""
    # 90-degree rotation about Z axis
    pose = np.array(
        [[0, -1, 0, 1], [1, 0, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]],
        dtype=np.float64,
    )
    r = _make_result(pose=pose)
    vm = CalibrationResultReviewViewModel(r)
    w, x, y, z = vm.pose_quaternion
    # Verify quaternion is normalized
    norm = (w**2 + x**2 + y**2 + z**2) ** 0.5
    assert norm == pytest.approx(1.0)
    # Verify it reconstructs the rotation (approximately)
    # For 90° about Z: q ≈ (cos45, 0, 0, sin45) ≈ (0.707, 0, 0, 0.707)
    assert abs(w) == pytest.approx(0.707, abs=0.01)
    assert abs(z) == pytest.approx(0.707, abs=0.01)


def test_no_transpose_in_pose_matrix() -> None:
    """pose_matrix_text must match raw result.pose, not its transpose."""
    pose = np.eye(4, dtype=np.float64)
    pose[0, 3] = 3.0
    pose[1, 3] = 4.0
    r = _make_result(pose=pose)
    vm = CalibrationResultReviewViewModel(r)
    m = vm.pose_matrix
    assert m[0, 3] == pytest.approx(3.0)
    assert m[1, 3] == pytest.approx(4.0)
    assert m[3, 0] == pytest.approx(0.0)  # not transposed


# ============================================================
# GATE 11 — MULTI-ORIENTATION DISPLAY
# ============================================================


def test_calibration_sequence_ids_includes_primary() -> None:
    """calibration_sequence_ids must include the primary sequence_id."""
    r = _make_result(
        sequence_id="seq-primary",
        calibration_sequence_ids=("seq-primary", "seq-2", "seq-3"),
    )
    vm = CalibrationResultReviewViewModel(r)
    assert "seq-primary" in vm.calibration_sequence_ids
    assert vm.orientation_count == 3


def test_fallback_to_sequence_id() -> None:
    """If calibration_sequence_ids is empty, fall back to (sequence_id,)."""
    r = _make_result(sequence_id="seq-only", calibration_sequence_ids=())
    vm = CalibrationResultReviewViewModel(r)
    assert vm.calibration_sequence_ids == ("seq-only",)
    assert vm.orientation_count == 1


def test_sequence_id_not_treated_as_complete_list() -> None:
    """sequence_id alone must not silently replace multi-orientation list."""
    r = _make_result(
        sequence_id="seq-1",
        calibration_sequence_ids=("seq-1", "seq-2"),
    )
    vm = CalibrationResultReviewViewModel(r)
    assert vm.orientation_count == 2
    assert vm.sequence_id == "seq-1"  # primary preserved


# ============================================================
# GATE 13 — NULL / INVALID RESULT
# ============================================================


def test_no_result_shows_failed_state() -> None:
    vm = CalibrationResultReviewViewModel(None)
    assert vm.status_kind == "FAILED"
    assert vm.review_ok is False
    assert "no result" in vm.eligibility_text.lower()


def test_no_result_all_properties_safe() -> None:
    """All properties must return safe defaults when result is None."""
    vm = CalibrationResultReviewViewModel(None)
    assert vm.calibration_id == ""
    assert vm.sequence_id == ""
    assert vm.projector_id == ""
    assert vm.camera_id == ""
    assert vm.surface_id == ""
    assert vm.projector_resolution == (0, 0)
    assert vm.intrinsics["fx"] == 0.0
    assert vm.reprojection_error == 0.0
    assert vm.coverage == 0.0
    assert vm.confidence == 0.0
    assert vm.num_correspondences == 0
    assert vm.per_point_errors == ()
    assert vm.decision is None
    assert vm.warnings == []
    assert vm.blocking_errors == ["No calibration result"]


def test_result_with_zero_correspondences_blocks() -> None:
    r = _make_result(num_correspondences=0)
    vm = CalibrationResultReviewViewModel(r)
    assert vm.review_ok is False
    assert vm.status_kind == "FAILED"


def test_result_with_extreme_values() -> None:
    """Result with extreme but finite values must not crash."""
    r = _make_result(
        reprojection_error=100.0,
        coverage=0.0,
        confidence=0.0,
        num_correspondences=1,
    )
    vm = CalibrationResultReviewViewModel(r)
    assert vm.review_ok is False
    assert len(vm.blocking_errors) > 0


# ============================================================
# GATE 14 — WARNING VS ERROR
# ============================================================


def test_warnings_and_errors_are_distinct() -> None:
    """Warnings and blocking errors must never collapse into the same bucket."""
    r = _make_result(reprojection_error=1.5, coverage=0.005)
    vm = CalibrationResultReviewViewModel(r)
    # 1.5 reproj → warning only; 0.005 coverage → blocking error
    assert any("elevated" in w for w in vm.warnings)
    assert any("critically low" in e for e in vm.blocking_errors)
    # They must be in separate lists
    warn_msgs = set(vm.warnings)
    err_msgs = set(vm.blocking_errors)
    assert warn_msgs.isdisjoint(err_msgs)


def test_warning_does_not_prevent_review() -> None:
    r = _make_result(reprojection_error=1.5)
    vm = CalibrationResultReviewViewModel(r)
    assert len(vm.warnings) > 0
    assert vm.review_ok is True


def test_blocking_error_prevents_review() -> None:
    r = _make_result(reprojection_error=5.0)
    vm = CalibrationResultReviewViewModel(r)
    assert len(vm.blocking_errors) > 0
    assert vm.review_ok is False


# ============================================================
# GATE 15 — RESPONSIVENESS
# ============================================================


def test_no_numpy_computation_in_watcher() -> None:
    """Warning/error properties must not do heavy numpy computation."""
    import inspect

    src = inspect.getsource(CalibrationResultReviewViewModel.warnings.fget)  # type: ignore[union-attr]
    # No dot product, SVD, eigenvalue, linalg calls
    forbidden = ["np.dot", "np.linalg", "np.einsum", "np.svd", "np.eig"]
    for fn in forbidden:
        assert fn not in src


# ============================================================
# GATE 12 — ADVANCED DETAILS (metadata truncation)
# ============================================================


def test_large_metadata_handled() -> None:
    """Large metadata does not crash the viewmodel."""
    big = {"key": "x" * 1000}
    r = _make_result(metadata=big)
    vm = CalibrationResultReviewViewModel(r)
    # Verify metadata is stored without truncation at viewmodel level
    assert vm.result is not None
    assert len(str(vm.result.metadata)) > 400


def test_empty_metadata_safe() -> None:
    r = _make_result(metadata={})
    vm = CalibrationResultReviewViewModel(r)
    assert vm.result is not None
    assert vm.result.metadata == {}
