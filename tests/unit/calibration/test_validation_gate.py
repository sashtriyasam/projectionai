"""Tests for the unified validation gate (validation_gate.py).

Covers:
- GateId, GateStatus, AuthorizationLevel enums
- GateResult properties (passed/failed)
- ValidationGateResult composite predicates and helpers
- ValidationGate.check() orchestrator with various input scenarios
- HARDWARE_PENDING ≠ PASS invariant
- Source mode gating (SYNTHETIC/REPLAY cannot arm/live)
"""

from __future__ import annotations

import time

import pytest

from projectionai.calibration.types import CalibrationResult
from projectionai.calibration.validator import (
    ValidationIssue,
    ValidationReport as CalValidationReport,
)
from projectionai.calibration.validation_gate import (
    AuthorizationLevel,
    GateId,
    GateResult,
    GateStatus,
    ValidationGate,
    ValidationGateResult,
)
from projectionai.hardware.display_validator import (
    ValidationIssue as DispValidationIssue,
    ValidationReport as DispValidationReport,
    ValidationSeverity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cal_report(
    passed: bool = True,
    quality_score: float = 0.85,
    issues: list[ValidationIssue] | None = None,
) -> CalValidationReport:
    """Create a CalibrationValidator ValidationReport."""
    return CalValidationReport(
        passed=passed,
        quality_score=quality_score,
        issues=issues or [],
    )


def _disp_report(
    errors: list[DispValidationIssue] | None = None,
) -> DispValidationReport:
    """Create a DisplayValidator ValidationReport."""
    return DispValidationReport(issues=tuple(errors or []))


def _renderer_error() -> DispValidationIssue:
    return DispValidationIssue(
        severity=ValidationSeverity.ERROR,
        code="renderer_not_ready",
        message="Renderer not ready",
    )


def _window_error() -> DispValidationIssue:
    return DispValidationIssue(
        severity=ValidationSeverity.ERROR,
        code="window_not_available",
        message="Window not available",
    )


def _all_pass_result(source: str = "LIVE") -> ValidationGateResult:
    """Convenience: a result where all gates pass with a LIVE source."""
    gate = ValidationGate()
    cal = _cal_report(passed=True)
    disp = _disp_report()
    return gate.check(
        calibration_report=cal,
        display_report=disp,
        hardware_pending=(),
        source_mode=source,
        warp_ready=True,
    )


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestGateId:
    def test_all_gate_ids_exist(self) -> None:
        ids = [g.value for g in GateId]
        assert "V-01" in ids
        assert "V-07" in ids
        assert len(ids) == 7

    def test_gate_ids_are_unique(self) -> None:
        ids = [g.value for g in GateId]
        assert len(ids) == len(set(ids))


class TestGateStatus:
    def test_all_statuses(self) -> None:
        statuses = [s.value for s in GateStatus]
        assert "pass" in statuses
        assert "fail" in statuses
        assert "pending" in statuses
        assert "skip" in statuses
        assert "not_applicable" in statuses


class TestAuthorizationLevel:
    def test_hierarchy(self) -> None:
        levels = [l.value for l in AuthorizationLevel]
        assert levels == ["none", "preview", "arm", "live"]


# ---------------------------------------------------------------------------
# GateResult tests
# ---------------------------------------------------------------------------


class TestGateResult:
    def test_passed_property(self) -> None:
        r = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.PASS)
        assert r.passed is True
        assert r.failed is False

    def test_failed_property(self) -> None:
        r = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.FAIL)
        assert r.failed is True
        assert r.passed is False

    def test_pending_is_neither_passed_nor_failed(self) -> None:
        r = GateResult(gate_id=GateId.HARDWARE_PENDING, status=GateStatus.PENDING)
        assert r.passed is False
        assert r.failed is False

    def test_frozen(self) -> None:
        r = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.PASS)
        with pytest.raises(AttributeError):
            r.status = GateStatus.FAIL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ValidationGateResult composite predicates
# ---------------------------------------------------------------------------


class TestValidationGateResult:
    def test_empty_result(self) -> None:
        r = ValidationGateResult()
        assert r.can_preview is False
        assert r.can_arm is False
        assert r.can_live is False
        assert r.is_ok is True
        assert r.summary == "none"
        assert r.failed_gates == ()
        assert r.pending_gates == ()
        assert r.passed_gates == ()

    def test_preview_authorization(self) -> None:
        r = ValidationGateResult(authorization=AuthorizationLevel.PREVIEW)
        assert r.can_preview is True
        assert r.can_arm is False
        assert r.can_live is False

    def test_arm_authorization(self) -> None:
        r = ValidationGateResult(authorization=AuthorizationLevel.ARM)
        assert r.can_preview is True
        assert r.can_arm is True
        assert r.can_live is False

    def test_live_authorization(self) -> None:
        r = ValidationGateResult(authorization=AuthorizationLevel.LIVE)
        assert r.can_preview is True
        assert r.can_arm is True
        assert r.can_live is True

    def test_has_hardware_pending(self) -> None:
        r = ValidationGateResult(
            gates=(
                GateResult(
                    gate_id=GateId.HARDWARE_PENDING,
                    status=GateStatus.PENDING,
                ),
            ),
        )
        assert r.has_hardware_pending is True

    def test_no_hardware_pending(self) -> None:
        r = ValidationGateResult(
            gates=(
                GateResult(
                    gate_id=GateId.HARDWARE_PENDING,
                    status=GateStatus.PASS,
                ),
            ),
        )
        assert r.has_hardware_pending is False

    def test_gate_lookup(self) -> None:
        g = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.PASS)
        r = ValidationGateResult(gates=(g,))
        assert r.gate(GateId.CALIBRATION_QUALITY) is g
        assert r.gate(GateId.DISPLAY_ROUTING) is None

    def test_gate_passed(self) -> None:
        g = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.PASS)
        r = ValidationGateResult(gates=(g,))
        assert r.gate_passed(GateId.CALIBRATION_QUALITY) is True
        assert r.gate_passed(GateId.DISPLAY_ROUTING) is False

    def test_gate_failed(self) -> None:
        g = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.FAIL)
        r = ValidationGateResult(gates=(g,))
        assert r.gate_failed(GateId.CALIBRATION_QUALITY) is True

    def test_is_ok_with_failures(self) -> None:
        g = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.FAIL)
        r = ValidationGateResult(gates=(g,))
        assert r.is_ok is False

    def test_is_ok_with_pending_only(self) -> None:
        g = GateResult(gate_id=GateId.HARDWARE_PENDING, status=GateStatus.PENDING)
        r = ValidationGateResult(gates=(g,))
        assert r.is_ok is True

    def test_summary_with_pending(self) -> None:
        r = ValidationGateResult(
            authorization=AuthorizationLevel.PREVIEW,
            gates=(
                GateResult(gate_id=GateId.HARDWARE_PENDING, status=GateStatus.PENDING),
            ),
        )
        assert "preview" in r.summary
        assert "1 pending" in r.summary

    def test_summary_with_failures(self) -> None:
        r = ValidationGateResult(
            authorization=AuthorizationLevel.NONE,
            gates=(
                GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.FAIL),
            ),
        )
        assert "none" in r.summary
        assert "1 failed" in r.summary

    def test_failed_gates_tuple(self) -> None:
        g1 = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.FAIL)
        g2 = GateResult(gate_id=GateId.DISPLAY_ROUTING, status=GateStatus.FAIL)
        g3 = GateResult(gate_id=GateId.HARDWARE_PENDING, status=GateStatus.PASS)
        r = ValidationGateResult(gates=(g1, g2, g3))
        assert len(r.failed_gates) == 2

    def test_passed_gates_tuple(self) -> None:
        g1 = GateResult(gate_id=GateId.CALIBRATION_QUALITY, status=GateStatus.PASS)
        g2 = GateResult(gate_id=GateId.DISPLAY_ROUTING, status=GateStatus.PASS)
        r = ValidationGateResult(gates=(g1, g2))
        assert len(r.passed_gates) == 2

    def test_frozen(self) -> None:
        r = ValidationGateResult()
        with pytest.raises(AttributeError):
            r.authorization = AuthorizationLevel.LIVE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ValidationGate.check() — orchestrator tests
# ---------------------------------------------------------------------------


class TestValidationGateCheck:
    def test_all_pass_live_source(self) -> None:
        """All gates pass with LIVE source → authorization = LIVE."""
        result = _all_pass_result(source="LIVE")
        assert result.authorization is AuthorizationLevel.LIVE
        assert result.can_preview is True
        assert result.can_arm is True
        assert result.can_live is True
        assert result.is_ok is True
        assert len(result.gates) == 7

    def test_no_calibration_report(self) -> None:
        """Missing calibration report → V-01 FAIL → authorization = NONE."""
        gate = ValidationGate()
        result = gate.check(calibration_report=None)
        assert result.authorization is AuthorizationLevel.NONE
        assert result.can_preview is False
        g01 = result.gate(GateId.CALIBRATION_QUALITY)
        assert g01 is not None
        assert g01.failed

    def test_calibration_not_passed(self) -> None:
        """Calibration report with passed=False → V-01 FAIL."""
        gate = ValidationGate()
        cal = _cal_report(passed=False)
        result = gate.check(calibration_report=cal)
        assert result.authorization is AuthorizationLevel.NONE
        g01 = result.gate(GateId.CALIBRATION_QUALITY)
        assert g01 is not None
        assert g01.failed

    def test_no_display_report(self) -> None:
        """Missing display report → V-02, V-03, V-04 FAIL → NONE."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        result = gate.check(
            calibration_report=cal,
            display_report=None,
            source_mode="LIVE",
        )
        assert result.authorization is AuthorizationLevel.NONE
        g02 = result.gate(GateId.DISPLAY_ROUTING)
        assert g02 is not None
        assert g02.failed

    def test_renderer_not_ready(self) -> None:
        """Display report with renderer error → V-03 FAIL → NONE."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report(errors=[_renderer_error()])
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            source_mode="LIVE",
        )
        assert result.authorization is AuthorizationLevel.NONE
        g03 = result.gate(GateId.RENDERER_READINESS)
        assert g03 is not None
        assert g03.failed

    def test_window_not_available(self) -> None:
        """Display report with window error → V-04 FAIL → NONE."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report(errors=[_window_error()])
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            source_mode="LIVE",
        )
        assert result.authorization is AuthorizationLevel.NONE
        g04 = result.gate(GateId.WINDOW_AVAILABILITY)
        assert g04 is not None
        assert g04.failed

    def test_hardware_pending_blocks_arm(self) -> None:
        """Hardware pending → V-05 PENDING → ARM allowed, LIVE blocked."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            hardware_pending=("V-05_lens_distortion",),
            source_mode="LIVE",
        )
        assert result.authorization is AuthorizationLevel.ARM
        assert result.can_preview is True
        assert result.can_arm is True
        assert result.can_live is False
        g05 = result.gate(GateId.HARDWARE_PENDING)
        assert g05 is not None
        assert g05.status is GateStatus.PENDING

    def test_synthetic_source_caps_at_preview(self) -> None:
        """SYNTHETIC source → max authorization is PREVIEW."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            source_mode="SYNTHETIC",
        )
        assert result.authorization is AuthorizationLevel.PREVIEW
        assert result.can_arm is False
        assert result.can_live is False

    def test_replay_source_caps_at_preview(self) -> None:
        """REPLAY source → max authorization is PREVIEW."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            source_mode="REPLAY",
        )
        assert result.authorization is AuthorizationLevel.PREVIEW

    def test_warp_not_ready(self) -> None:
        """Warp not ready → V-07 FAIL → NONE."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            warp_ready=False,
            source_mode="LIVE",
        )
        assert result.authorization is AuthorizationLevel.NONE
        g07 = result.gate(GateId.WARP_READINESS)
        assert g07 is not None
        assert g07.failed

    def test_all_gates_present(self) -> None:
        """check() always produces exactly 7 gate results."""
        gate = ValidationGate()
        result = gate.check()
        assert len(result.gates) == 7
        gate_ids = {g.gate_id for g in result.gates}
        expected_ids = {gid for gid in GateId}
        assert gate_ids == expected_ids

    def test_empty_hardware_pending_passes_g05(self) -> None:
        """Empty hardware_pending tuple → V-05 PASS."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            hardware_pending=(),
            source_mode="LIVE",
        )
        g05 = result.gate(GateId.HARDWARE_PENDING)
        assert g05 is not None
        assert g05.passed

    def test_multiple_hardware_pending_items(self) -> None:
        """Multiple pending items → V-05 PENDING with count."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            hardware_pending=("V-05_lens", "V-05_focus"),
            source_mode="LIVE",
        )
        g05 = result.gate(GateId.HARDWARE_PENDING)
        assert g05 is not None
        assert g05.status is GateStatus.PENDING
        assert "2" in g05.message

    def test_cal_report_with_issues(self) -> None:
        """Calibration report with failed issues → V-01 FAIL with detail."""
        issue = ValidationIssue(message="Reprojection error too high", severity="error")
        cal = _cal_report(passed=False, issues=[issue])
        gate = ValidationGate()
        result = gate.check(calibration_report=cal)
        g01 = result.gate(GateId.CALIBRATION_QUALITY)
        assert g01 is not None
        assert g01.failed
        assert "Reprojection" in g01.message

    def test_evaluated_at_timestamp(self) -> None:
        """Result has a reasonable evaluated_at timestamp."""
        before = time.time()
        result = _all_pass_result()
        after = time.time()
        assert before <= result.evaluated_at <= after

    def test_hardware_pending_tuple_stored(self) -> None:
        """hardware_pending tuple from input is stored in result."""
        pending = ("V-05_lens",)
        gate = ValidationGate()
        result = gate.check(hardware_pending=pending)
        assert result.hardware_pending == pending

    def test_source_mode_stored(self) -> None:
        """Source mode from input is stored in result."""
        gate = ValidationGate()
        result = gate.check(source_mode="REPLAY")
        assert result.source_mode == "REPLAY"

    def test_display_errors_propagated(self) -> None:
        """Multiple display errors → multiple gates fail."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report(errors=[_renderer_error(), _window_error()])
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            source_mode="LIVE",
        )
        assert result.authorization is AuthorizationLevel.NONE
        failed_ids = {g.gate_id for g in result.failed_gates}
        assert GateId.RENDERER_READINESS in failed_ids
        assert GateId.WINDOW_AVAILABILITY in failed_ids

    def test_none_authority_with_missing_display_report(self) -> None:
        """AuthorizationLevel.NONE when display_report is missing."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        result = gate.check(
            calibration_report=cal,
            display_report=None,
            source_mode="SYNTHETIC",
        )
        # display_report=None → V-02, V-03, V-04 FAIL
        # But with SYNTHETIC source, we still get NONE because FAILs exist
        assert result.authorization is AuthorizationLevel.NONE

    def test_preview_needs_no_failures(self) -> None:
        """PREVIEW requires all gates to have no FAIL status."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            source_mode="SYNTHETIC",
            hardware_pending=("gate_a",),
        )
        # V-05 PENDING + V-06 PENDING (SYNTHETIC) → no FAILs → PREVIEW
        assert result.authorization is AuthorizationLevel.PREVIEW
        assert len(result.failed_gates) == 0
        pending_ids = {g.gate_id for g in result.pending_gates}
        assert GateId.HARDWARE_PENDING in pending_ids
        assert GateId.SOURCE_MODE in pending_ids


# ---------------------------------------------------------------------------
# HARDWARE_PENDING ≠ PASS invariant
# ---------------------------------------------------------------------------


class TestHardwarePendingNotPass:
    def test_pending_is_not_pass(self) -> None:
        """HARDWARE_PENDING status is PENDING, never PASS when items exist."""
        gate = ValidationGate()
        result = gate.check(hardware_pending=("something",))
        g05 = result.gate(GateId.HARDWARE_PENDING)
        assert g05 is not None
        assert g05.status is GateStatus.PENDING
        assert g05.status is not GateStatus.PASS

    def test_hardware_pending_allows_arm_but_blocks_live(self) -> None:
        """Hardware pending → ARM allowed, but LIVE blocked (HARDWARE_PENDING ≠ PASS)."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            hardware_pending=("pending_gate",),
            source_mode="LIVE",
        )
        assert result.can_arm is True
        assert result.can_live is False
        assert result.authorization is AuthorizationLevel.ARM
        g05 = result.gate(GateId.HARDWARE_PENDING)
        assert g05 is not None
        assert g05.status is GateStatus.PENDING

    def test_only_empty_pending_allows_live(self) -> None:
        """Only empty hardware_pending allows LIVE with LIVE source."""
        gate = ValidationGate()
        cal = _cal_report(passed=True)
        disp = _disp_report()
        result = gate.check(
            calibration_report=cal,
            display_report=disp,
            hardware_pending=(),
            source_mode="LIVE",
        )
        assert result.can_arm is True
        assert result.can_live is True
