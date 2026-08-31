"""Unified validation gate — single source of truth for "Is the system authorized?"

This module answers three questions:
- ``can_preview``: Is software review passed (calibration quality OK, no blocking errors)?
- ``can_arm``: Is it safe to arm projector output?
- ``can_live``: Is it safe to go live?

It orchestrates existing validators (CalibrationValidator, DisplayValidator)
without replacing them.  Each domain validator remains authoritative for its
own checks; this module collects their results and computes composite
authorization.

Design constraints (from 7.11 scope):
- HARDWARE_PENDING ≠ PASS: never collapse into a single boolean.
- ``can_preview ≠ can_arm ≠ can_live``: three explicit authorization levels.
- Source mode (SYNTHETIC/REPLAY/LIVE) gates arm/live — preview is always
  software-only.
- No new persistence, no new state machine, no replacement models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from projectionai.calibration.validator import ValidationReport as CalReport
    from projectionai.hardware.display_validator import ValidationReport as DispReport


# ---------------------------------------------------------------------------
# Gate taxonomy
# ---------------------------------------------------------------------------


class GateId(StrEnum):
    """Canonical gate identifiers — V-01..V-07 for software authorization gates.

    Physical hardware validation gates use H-01..H-07 (see 10_VALIDATION_GATES).
    """

    CALIBRATION_QUALITY = "V-01"
    DISPLAY_ROUTING = "V-02"
    RENDERER_READINESS = "V-03"
    WINDOW_AVAILABILITY = "V-04"
    HARDWARE_PENDING = "V-05"
    SOURCE_MODE = "V-06"
    WARP_READINESS = "V-07"


class GateStatus(StrEnum):
    """Per-gate verdict."""

    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"
    SKIP = "skip"
    NOT_APPLICABLE = "not_applicable"


class AuthorizationLevel(StrEnum):
    """Composite authorization — highest level the system currently qualifies for."""

    NONE = "none"
    PREVIEW = "preview"
    ARM = "arm"
    LIVE = "live"


# ---------------------------------------------------------------------------
# Per-gate result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    """One gate's verdict."""

    gate_id: GateId
    status: GateStatus
    message: str = ""
    source_validator: str = ""

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status is GateStatus.FAIL


# ---------------------------------------------------------------------------
# Composite gate result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationGateResult:
    """Aggregated result from all gates.

    Immutable after construction — consumers read properties, never mutate.
    """

    gates: tuple[GateResult, ...] = ()
    authorization: AuthorizationLevel = AuthorizationLevel.NONE
    source_mode: str = "SYNTHETIC"
    evaluated_at: float = field(default_factory=time.time)
    hardware_pending: tuple[str, ...] = ()

    # -- Composite predicates ------------------------------------------------

    @property
    def can_preview(self) -> bool:
        """True when software review passed (no blocking gate failures)."""
        return self.authorization.value in ("preview", "arm", "live")

    @property
    def can_arm(self) -> bool:
        """True when the system is authorized to arm projector output."""
        return self.authorization.value in ("arm", "live")

    @property
    def can_live(self) -> bool:
        """True when the system is authorized to go live."""
        return self.authorization is AuthorizationLevel.LIVE

    @property
    def has_hardware_pending(self) -> bool:
        """True when any physical-readiness gate is still pending."""
        return any(
            g.gate_id is GateId.HARDWARE_PENDING and g.status is GateStatus.PENDING
            for g in self.gates
        )

    # -- Gate lookups --------------------------------------------------------

    def gate(self, gate_id: GateId) -> GateResult | None:
        """Return the result for *gate_id*, or ``None`` if not evaluated."""
        for g in self.gates:
            if g.gate_id is gate_id:
                return g
        return None

    def gate_passed(self, gate_id: GateId) -> bool:
        """Convenience: ``True`` when the gate exists and passed."""
        r = self.gate(gate_id)
        return r is not None and r.passed

    def gate_failed(self, gate_id: GateId) -> bool:
        """Convenience: ``True`` when the gate exists and failed."""
        r = self.gate(gate_id)
        return r is not None and r.failed

    # -- Failure helpers -----------------------------------------------------

    @property
    def failed_gates(self) -> tuple[GateResult, ...]:
        """All gates that failed."""
        return tuple(g for g in self.gates if g.failed)

    @property
    def pending_gates(self) -> tuple[GateResult, ...]:
        """All gates still pending."""
        return tuple(g for g in self.gates if g.status is GateStatus.PENDING)

    @property
    def passed_gates(self) -> tuple[GateResult, ...]:
        """All gates that passed."""
        return tuple(g for g in self.gates if g.passed)

    @property
    def is_ok(self) -> bool:
        """True when no gate failed (pending gates are allowed)."""
        return not self.failed_gates

    @property
    def summary(self) -> str:
        """One-line human summary, e.g. ``"preview (2 pending)"``."""
        parts = [self.authorization.value]
        n_fail = len(self.failed_gates)
        n_pend = len(self.pending_gates)
        if n_fail:
            parts.append(f"{n_fail} failed")
        if n_pend:
            parts.append(f"{n_pend} pending")
        return " ".join(parts) if len(parts) > 1 else self.authorization.value


# ---------------------------------------------------------------------------
# ValidationGate orchestrator
# ---------------------------------------------------------------------------


class ValidationGate:
    """Orchestrate existing validators and compute composite authorization.

    Usage::

        gate = ValidationGate()
        result = gate.check(
            calibration_report=cal_report,
            display_report=disp_report,
            hardware_pending=("V-05_lens_distortion",),
            source_mode="SYNTHETIC",
        )
        if result.can_arm:
            await output_manager.arm()

    The gate does NOT:
    - Replace CalibrationValidator or DisplayValidator
    - Own persistence or state
    - Introduce concurrency
    """

    def check(
        self,
        *,
        calibration_report: CalReport | None = None,
        display_report: DispReport | None = None,
        hardware_pending: tuple[str, ...] = (),
        source_mode: str = "SYNTHETIC",
        warp_ready: bool = True,
    ) -> ValidationGateResult:
        """Evaluate all gates and return the composite result.

        Args:
            calibration_report: Output of ``CalibrationValidator.validate()``.
                ``None`` means no calibration exists yet (gate FAILS).
            display_report: Output of ``DisplayValidator.validate()``.
                ``None`` means display state unknown (gate FAILS for arm/live).
            hardware_pending: Tuple of pending hardware gate strings from
                ``ProductionWorkflow.hardware_pending``.  Each non-empty
                string is a HARDWARE_PENDING gate that has NOT passed.
            source_mode: One of ``SYNTHETIC``, ``REPLAY``, ``LIVE``.
            warp_ready: Whether the warp pipeline is ready (V-07).

        Returns:
            Frozen :class:`ValidationGateResult` with per-gate statuses
            and the highest authorization level achieved.
        """
        gates: list[GateResult] = []

        # -- V-01: Calibration quality ----------------------------------------
        gates.append(self._check_calibration(calibration_report))

        # -- V-02: Display routing --------------------------------------------
        gates.append(self._check_display_routing(display_report))

        # -- V-03: Renderer readiness -----------------------------------------
        gates.append(self._check_renderer(display_report))

        # -- V-04: Window availability ----------------------------------------
        gates.append(self._check_window(display_report))

        # -- V-05: Hardware pending -------------------------------------------
        gates.append(self._check_hardware_pending(hardware_pending))

        # -- V-06: Source mode ------------------------------------------------
        gates.append(self._check_source_mode(source_mode))

        # -- V-07: Warp readiness ---------------------------------------------
        gates.append(self._check_warp(warp_ready))

        # -- Compute authorization level --------------------------------------
        authorization = self._compute_authorization(gates, source_mode=source_mode)

        return ValidationGateResult(
            gates=tuple(gates),
            authorization=authorization,
            source_mode=source_mode,
            hardware_pending=hardware_pending,
        )

    # -- Individual gate evaluators ------------------------------------------

    def _check_calibration(self, report: CalReport | None) -> GateResult:
        """V-01: Calibration quality."""
        if report is None:
            return GateResult(
                gate_id=GateId.CALIBRATION_QUALITY,
                status=GateStatus.FAIL,
                message="No calibration result available",
                source_validator="CalibrationValidator",
            )
        if report.passed:
            return GateResult(
                gate_id=GateId.CALIBRATION_QUALITY,
                status=GateStatus.PASS,
                message=f"Quality score {report.quality_score:.2f}",
                source_validator="CalibrationValidator",
            )
        # Collect failure reasons from the report
        issues = [issue for issue in report.issues if issue.severity == "error"]
        detail = (
            "; ".join(str(i) for i in issues[:3]) if issues else "quality check failed"
        )
        return GateResult(
            gate_id=GateId.CALIBRATION_QUALITY,
            status=GateStatus.FAIL,
            message=detail,
            source_validator="CalibrationValidator",
        )

    def _check_display_routing(self, report: DispReport | None) -> GateResult:
        """V-02: Display routing."""
        if report is None:
            return GateResult(
                gate_id=GateId.DISPLAY_ROUTING,
                status=GateStatus.FAIL,
                message="Display state unknown",
                source_validator="DisplayValidator",
            )
        if report.is_ok:
            return GateResult(
                gate_id=GateId.DISPLAY_ROUTING,
                status=GateStatus.PASS,
                message="Display routing valid",
                source_validator="DisplayValidator",
            )
        err_msgs = [e.message for e in report.errors[:3]]
        return GateResult(
            gate_id=GateId.DISPLAY_ROUTING,
            status=GateStatus.FAIL,
            message="; ".join(err_msgs) if err_msgs else "display validation failed",
            source_validator="DisplayValidator",
        )

    def _check_renderer(self, report: DispReport | None) -> GateResult:
        """V-03: Renderer readiness."""
        if report is None:
            return GateResult(
                gate_id=GateId.RENDERER_READINESS,
                status=GateStatus.FAIL,
                message="Renderer state unknown",
                source_validator="DisplayValidator",
            )
        # Look for renderer-specific error in the report
        for issue in report.errors:
            if issue.code == "renderer_not_ready":
                return GateResult(
                    gate_id=GateId.RENDERER_READINESS,
                    status=GateStatus.FAIL,
                    message=issue.message,
                    source_validator="DisplayValidator",
                )
        return GateResult(
            gate_id=GateId.RENDERER_READINESS,
            status=GateStatus.PASS,
            message="Renderer ready",
            source_validator="DisplayValidator",
        )

    def _check_window(self, report: DispReport | None) -> GateResult:
        """V-04: Window availability."""
        if report is None:
            return GateResult(
                gate_id=GateId.WINDOW_AVAILABILITY,
                status=GateStatus.FAIL,
                message="Window state unknown",
                source_validator="DisplayValidator",
            )
        for issue in report.errors:
            if issue.code == "window_not_available":
                return GateResult(
                    gate_id=GateId.WINDOW_AVAILABILITY,
                    status=GateStatus.FAIL,
                    message=issue.message,
                    source_validator="DisplayValidator",
                )
        return GateResult(
            gate_id=GateId.WINDOW_AVAILABILITY,
            status=GateStatus.PASS,
            message="Window available",
            source_validator="DisplayValidator",
        )

    def _check_hardware_pending(self, pending: tuple[str, ...]) -> GateResult:
        """V-05: Hardware pending — HARDWARE_PENDING ≠ PASS.

        Any non-empty pending tuple means physical readiness is NOT proven.
        The gate status is PENDING (not FAIL) to distinguish "not yet checked"
        from "checked and failed".
        """
        if not pending:
            return GateResult(
                gate_id=GateId.HARDWARE_PENDING,
                status=GateStatus.PASS,
                message="No hardware gates pending",
                source_validator="ProductionWorkflow",
            )
        return GateResult(
            gate_id=GateId.HARDWARE_PENDING,
            status=GateStatus.PENDING,
            message=f"{len(pending)} hardware gate(s) pending: {', '.join(pending)}",
            source_validator="ProductionWorkflow",
        )

    def _check_source_mode(self, mode: str) -> GateResult:
        """V-06: Source mode — SYNTHETIC/REPLAY cannot arm or live."""
        normalised = mode.upper() if mode else "SYNTHETIC"
        if normalised == "LIVE":
            return GateResult(
                gate_id=GateId.SOURCE_MODE,
                status=GateStatus.PASS,
                message="Source mode LIVE — physical validation applicable",
                source_validator="ValidationGate",
            )
        return GateResult(
            gate_id=GateId.SOURCE_MODE,
            status=GateStatus.PENDING,
            message=f"Source mode {normalised} — physical validation not applicable",
            source_validator="ValidationGate",
        )

    def _check_warp(self, ready: bool) -> GateResult:
        """V-07: Warp readiness."""
        if ready:
            return GateResult(
                gate_id=GateId.WARP_READINESS,
                status=GateStatus.PASS,
                message="Warp pipeline ready",
                source_validator="WarpPipeline",
            )
        return GateResult(
            gate_id=GateId.WARP_READINESS,
            status=GateStatus.FAIL,
            message="Warp pipeline not ready",
            source_validator="WarpPipeline",
        )

    # -- Authorization computation -------------------------------------------

    def _compute_authorization(
        self,
        gates: list[GateResult],
        *,
        source_mode: str,
    ) -> AuthorizationLevel:
        """Derive the highest authorization level from gate results.

        Rules:
        1. Any FAIL → authorization capped at NONE.
        2. PREVIEW requires: V-01 PASS, V-07 PASS, no FAILs.
        3. ARM requires: PREVIEW + V-02 PASS + V-03 PASS + V-04 PASS
           + V-06 PASS (source LIVE). Hardware pending (V-05) does NOT block ARM.
        4. LIVE requires: ARM + V-05 PASS (no hardware pending).
        5. Source SYNTHETIC/REPLAY → max authorization is PREVIEW.
        """
        by_id = {g.gate_id: g for g in gates}

        # Any FAIL → NONE
        if any(g.failed for g in gates):
            return AuthorizationLevel.NONE

        # V-01 must pass for any authorization
        g01 = by_id.get(GateId.CALIBRATION_QUALITY)
        if g01 is None or not g01.passed:
            return AuthorizationLevel.NONE

        # V-07 must pass for any authorization
        g07 = by_id.get(GateId.WARP_READINESS)
        if g07 is None or not g07.passed:
            return AuthorizationLevel.NONE

        # PREVIEW is the minimum when calibration + warp pass
        level = AuthorizationLevel.PREVIEW

        # Source SYNTHETIC/REPLAY → cap at PREVIEW
        if source_mode.upper() in ("SYNTHETIC", "REPLAY"):
            return level

        # For ARM: require display/window/renderer + source LIVE (but NOT hardware pending)
        g02 = by_id.get(GateId.DISPLAY_ROUTING)
        g03 = by_id.get(GateId.RENDERER_READINESS)
        g04 = by_id.get(GateId.WINDOW_AVAILABILITY)
        g06 = by_id.get(GateId.SOURCE_MODE)

        if (
            g02 is not None
            and g02.passed
            and g03 is not None
            and g03.passed
            and g04 is not None
            and g04.passed
            and g06 is not None
            and g06.passed
        ):
            level = AuthorizationLevel.ARM

        # For LIVE: require ARM + hardware pending clear
        if level is AuthorizationLevel.ARM:
            g05 = by_id.get(GateId.HARDWARE_PENDING)
            if g05 is not None and g05.passed:
                level = AuthorizationLevel.LIVE

        return level
