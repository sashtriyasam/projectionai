"""Qt-free review ViewModel for a canonical CalibrationResult.

Presentation + eligibility only — never recalculates calibration.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.calibration.validation_gate import (
    ValidationGate,
    ValidationGateResult,
)
from projectionai.domain.calibration_session import CalibrationResult
from projectionai.ui.viewmodels.observable import Observable

# Reuse canonical validator thresholds where defined
_REPROJECTION_MAX_ERROR = 2.0
_REPROJECTION_WARN_ERROR = 1.0
_MIN_SAMPLES = 5
_MIN_CONFIDENCE = 0.5
_MIN_COVERAGE_WARN = 0.1
_MIN_COVERAGE_ERROR = 0.01
_GATE_STALE_SECONDS = 300.0  # gate result older than 5 min is stale


class ReviewDecision(StrEnum):
    """Review state — separate from calibration state."""

    ACCEPTED_FOR_PREVIEW = "accepted_for_preview"
    REJECTED = "rejected"
    NEEDS_RECALIBRATION = "needs_recalibration"


class CalibrationResultReviewViewModel(Observable):
    """Thin, Qt-free facade over a canonical CalibrationResult.

    - Consumes ``CalibrationResult`` as-is; never calls ``solve_*``.
    - Exposes formatted intrinsics, pose, quality, and eligibility.
    - Stores *review* decision separately (does not mutate the result).
    """

    def __init__(
        self,
        result: CalibrationResult | None = None,
        *,
        source_mode: str = "SYNTHETIC",
        hardware_pending: tuple[str, ...] = (),
        gate: ValidationGate | None = None,
    ) -> None:
        super().__init__()
        self._result: CalibrationResult | None = result
        self._source_mode: str = source_mode.upper() if source_mode else "SYNTHETIC"
        if self._source_mode not in ("SYNTHETIC", "REPLAY", "LIVE"):
            self._source_mode = "SYNTHETIC"
        self._hardware_pending: tuple[str, ...] = tuple(hardware_pending)
        self._gate: ValidationGate | None = gate
        self._gate_result: ValidationGateResult | None = None
        self._gate_evaluated_at: float | None = None
        self._decision: ReviewDecision | None = None

    # -- Result wiring -----------------------------------------------------

    @property
    def result(self) -> CalibrationResult | None:
        return self._result

    @property
    def has_result(self) -> bool:
        return self._result is not None

    def set_result(
        self,
        result: CalibrationResult | None,
        *,
        source_mode: str | None = None,
        hardware_pending: tuple[str, ...] | None = None,
    ) -> None:
        self._result = result
        self._gate_result = None
        self._gate_evaluated_at = None
        if source_mode is not None:
            sm = source_mode.upper()
            self._source_mode = (
                sm if sm in ("SYNTHETIC", "REPLAY", "LIVE") else "SYNTHETIC"
            )
        if hardware_pending is not None:
            self._hardware_pending = tuple(hardware_pending)
        self._decision = None
        self._notify()

    def clear(self) -> None:
        self._result = None
        self._gate_result = None
        self._gate_evaluated_at = None
        self._decision = None
        self._notify()

    def set_source_mode(self, mode: str) -> None:
        sm = mode.upper()
        if sm not in ("SYNTHETIC", "REPLAY", "LIVE"):
            sm = "SYNTHETIC"
        if sm != self._source_mode:
            self._source_mode = sm
            self._gate_result = None
            self._gate_evaluated_at = None
            self._notify()

    def set_hardware_pending(self, gates: tuple[str, ...]) -> None:
        self._hardware_pending = tuple(gates)
        self._gate_result = None
        self._gate_evaluated_at = None
        self._notify()

    def set_gate(self, gate: ValidationGate | None) -> None:
        self._gate = gate
        self._gate_result = None
        self._notify()

    def evaluate_gate(
        self,
        *,
        calibration_report: Any | None = None,
        display_report: Any | None = None,
    ) -> ValidationGateResult | None:
        if self._gate is None:
            return None
        result = self._gate.check(
            calibration_report=calibration_report,
            display_report=display_report,
            hardware_pending=self._hardware_pending,
            source_mode=self._source_mode,
        )
        self._gate_result = result
        self._gate_evaluated_at = time.monotonic()
        self._notify()
        return result

    # -- Identity ----------------------------------------------------------

    @property
    def calibration_id(self) -> str:
        return self._result.calibration_id if self._result else ""

    @property
    def sequence_id(self) -> str:
        return self._result.sequence_id if self._result else ""

    @property
    def calibration_sequence_ids(self) -> tuple[str, ...]:
        if not self._result:
            return ()
        # Prefer calibration_sequence_ids, fallback to single sequence_id
        ids = self._result.calibration_sequence_ids
        if ids:
            return ids
        return (self._result.sequence_id,)

    @property
    def method(self) -> str:
        if not self._result:
            return ""
        m = self._result.method
        return str(m.value) if hasattr(m, "value") else str(m)

    @property
    def projector_id(self) -> str:
        return self._result.projector_id if self._result else ""

    @property
    def camera_id(self) -> str:
        return self._result.camera_id if self._result else ""

    @property
    def surface_id(self) -> str:
        return self._result.surface_id if self._result else ""

    @property
    def projector_resolution(self) -> tuple[int, int]:
        return self._result.projector_resolution if self._result else (0, 0)

    @property
    def projector_resolution_text(self) -> str:
        w, h = self.projector_resolution
        return f"{w} x {h}" if w and h else "—"

    # -- Intrinsics --------------------------------------------------------

    @property
    def intrinsics(self) -> dict[str, float]:
        if not self._result:
            return {"fx": 0.0, "fy": 0.0, "cx": 0.0, "cy": 0.0}
        k = self._result.projector_intrinsics
        return {
            "fx": float(k[0, 0]),
            "fy": float(k[1, 1]),
            "cx": float(k[0, 2]),
            "cy": float(k[1, 2]),
        }

    @property
    def intrinsics_matrix(self) -> NDArray[np.float64]:
        if not self._result:
            return np.eye(3, dtype=np.float64)
        return np.array(self._result.projector_intrinsics, dtype=np.float64)

    @property
    def intrinsics_matrix_text(self) -> str:
        k = self.intrinsics_matrix
        return (
            f"[ {k[0, 0]:8.2f} {k[0, 1]:8.2f} {k[0, 2]:8.2f} ]\n"
            f"[ {k[1, 0]:8.2f} {k[1, 1]:8.2f} {k[1, 2]:8.2f} ]\n"
            f"[ {k[2, 0]:8.2f} {k[2, 1]:8.2f} {k[2, 2]:8.2f} ]"
        )

    # -- Pose --------------------------------------------------------------

    @property
    def pose_matrix(self) -> NDArray[np.float64]:
        if not self._result:
            return np.eye(4, dtype=np.float64)
        return np.array(self._result.projector_pose, dtype=np.float64)

    @property
    def pose_matrix_text(self) -> str:
        m = self.pose_matrix
        rows = []
        for r in range(4):
            rows.append(
                f"[ {m[r, 0]:8.4f} {m[r, 1]:8.4f} {m[r, 2]:8.4f} {m[r, 3]:8.4f} ]"
            )
        return "\n".join(rows)

    @property
    def pose_frame(self) -> str:
        return "projector → camera"

    @property
    def pose_translation(self) -> tuple[float, float, float]:
        m = self.pose_matrix
        return (float(m[0, 3]), float(m[1, 3]), float(m[2, 3]))

    @property
    def pose_translation_text(self) -> str:
        x, y, z = self.pose_translation
        return f"({x:.3f}, {y:.3f}, {z:.3f})"

    @property
    def pose_quaternion(self) -> tuple[float, float, float, float]:
        """Quaternion (w,x,y,z) from pose rotation, or identity on failure."""
        m = self.pose_matrix
        r = m[:3, :3]
        q = _rotation_to_quat(r)
        if q is None:
            return (1.0, 0.0, 0.0, 0.0)
        return q

    @property
    def pose_quaternion_text(self) -> str:
        w, x, y, z = self.pose_quaternion
        return f"({w:.4f}, {x:.4f}, {y:.4f}, {z:.4f})"

    # -- Quality -----------------------------------------------------------

    @property
    def reprojection_error(self) -> float:
        return float(self._result.reprojection_error) if self._result else 0.0

    @property
    def coverage(self) -> float:
        return float(self._result.coverage) if self._result else 0.0

    @property
    def confidence(self) -> float:
        return float(self._result.confidence) if self._result else 0.0

    @property
    def num_correspondences(self) -> int:
        return int(self._result.num_correspondences) if self._result else 0

    @property
    def orientation_count(self) -> int:
        return len(self.calibration_sequence_ids)

    @property
    def orientation_ids(self) -> tuple[str, ...]:
        return self.calibration_sequence_ids

    @property
    def per_point_errors(self) -> tuple[float, ...]:
        return tuple(self._result.per_point_errors) if self._result else ()

    @property
    def per_point_stats(self) -> dict[str, float]:
        errs = self.per_point_errors
        if not errs:
            return {"count": 0.0, "mean": 0.0, "max": 0.0, "rms": 0.0}
        arr = np.array(errs, dtype=np.float64)
        return {
            "count": float(len(errs)),
            "mean": float(np.mean(arr)),
            "max": float(np.max(arr)),
            "rms": float(np.sqrt(np.mean(arr * arr))),
        }

    # -- Source / hardware -------------------------------------------------

    @property
    def source_mode(self) -> str:
        return self._source_mode

    @property
    def source_label(self) -> str:
        return f"SOURCE: {self._source_mode}"

    @property
    def physical_validation_label(self) -> str:
        if self._source_mode in ("SYNTHETIC", "REPLAY"):
            return "PHYSICAL VALIDATION: NOT VERIFIED"
        return "PHYSICAL VALIDATION: PENDING"

    @property
    def hardware_pending(self) -> tuple[str, ...]:
        return self._hardware_pending

    # -- Warnings / blocking errors ---------------------------------------

    @property
    def warnings(self) -> list[str]:
        if not self._result:
            return []
        out: list[str] = []
        r = self._result
        # Gate warnings (pending gates)
        if self._gate_result is not None:
            for g in self._gate_result.pending_gates:
                out.append(f"Gate {g.gate_id.value} pending: {g.message}")
            if self.is_gate_stale:
                out.append("Gate result is stale — re-evaluate before use")
        # Source-based warnings
        if self._source_mode == "SYNTHETIC":
            out.append("Synthetic source — physical validation not verified")
        elif self._source_mode == "REPLAY":
            out.append("Replay source — physical validation not verified")
        # Hardware pending
        if self._hardware_pending:
            out.append(
                f"Hardware validation pending ({len(self._hardware_pending)} gates)"
            )
        # Quality warnings (non-blocking)
        if _REPROJECTION_WARN_ERROR < r.reprojection_error <= _REPROJECTION_MAX_ERROR:
            out.append(
                f"Reprojection error {r.reprojection_error:.2f}px elevated "
                f"(warn > {_REPROJECTION_WARN_ERROR:.1f}px)"
            )
        if _MIN_COVERAGE_ERROR < r.coverage < _MIN_COVERAGE_WARN:
            out.append(
                f"Low coverage {r.coverage:.1%} (warn < {_MIN_COVERAGE_WARN:.0%})"
            )
        if 0 < r.confidence < _MIN_CONFIDENCE:
            out.append(
                f"Low confidence {r.confidence:.2f} (warn < {_MIN_CONFIDENCE:.1f})"
            )
        if 0 < len(self.calibration_sequence_ids) < 3:
            out.append(
                f"Only {len(self.calibration_sequence_ids)} orientation(s) — "
                "use 3+ for robust calibration"
            )
        # Per-point max warning
        stats = self.per_point_stats
        if stats["count"] > 0 and stats["max"] > 3.0:
            out.append(f"Max per-point error {stats['max']:.2f}px elevated")
        # Metadata warnings pass-through
        for w in (
            r.metadata.get("warnings", [])
            if isinstance(r.metadata.get("warnings"), list)
            else []
        ):
            if isinstance(w, str) and w not in out:
                out.append(w)
        return out

    @property
    def blocking_errors(self) -> list[str]:
        if not self._result:
            return ["No calibration result"]
        out: list[str] = []
        r = self._result
        # Gate failures (blocking)
        if self._gate_result is not None:
            for g in self._gate_result.failed_gates:
                out.append(f"Gate {g.gate_id.value} failed: {g.message}")
        # Data sanity
        if not np.all(np.isfinite(r.projector_intrinsics)):
            out.append("NaN/Inf in projector intrinsics")
        if not np.all(np.isfinite(r.projector_pose)):
            out.append("NaN/Inf in projector pose")
        if r.reprojection_error > _REPROJECTION_MAX_ERROR:
            out.append(
                f"Reprojection error {r.reprojection_error:.2f}px exceeds "
                f"threshold {_REPROJECTION_MAX_ERROR:.1f}px"
            )
        if r.coverage < _MIN_COVERAGE_ERROR:
            out.append(
                f"Coverage {r.coverage:.1%} critically low (< {_MIN_COVERAGE_ERROR:.0%})"
            )
        if r.num_correspondences == 0:
            out.append("No correspondences")
        elif r.num_correspondences < _MIN_SAMPLES:
            out.append(
                f"Only {r.num_correspondences} correspondences (minimum {_MIN_SAMPLES})"
            )
        # Metadata blocking errors
        for e in (
            r.metadata.get("errors", [])
            if isinstance(r.metadata.get("errors"), list)
            else []
        ):
            if isinstance(e, str) and e not in out:
                out.append(e)
        return out

    # -- Gate staleness ----------------------------------------------------

    @property
    def is_gate_stale(self) -> bool:
        """True when a gate result exists but was evaluated more than 5 min ago."""
        if self._gate_result is None or self._gate_evaluated_at is None:
            return False
        return (time.monotonic() - self._gate_evaluated_at) > _GATE_STALE_SECONDS

    @property
    def gate_age_seconds(self) -> float | None:
        """Seconds since the gate was last evaluated, or None if never evaluated."""
        if self._gate_evaluated_at is None:
            return None
        return time.monotonic() - self._gate_evaluated_at

    # -- Eligibility / status ---------------------------------------------

    @property
    def gate_result(self) -> ValidationGateResult | None:
        return self._gate_result

    @property
    def can_preview(self) -> bool:
        if self._gate_result is not None:
            return self._gate_result.can_preview
        return len(self.blocking_errors) == 0 and self.has_result

    @property
    def can_arm(self) -> bool:
        if self._gate_result is not None:
            return self._gate_result.can_arm
        return False

    @property
    def can_live(self) -> bool:
        if self._gate_result is not None:
            return self._gate_result.can_live
        return False

    @property
    def review_ok(self) -> bool:
        return self.can_preview

    @property
    def status_kind(self) -> str:
        if not self.has_result:
            return "FAILED"
        if self.blocking_errors:
            return "FAILED"
        if self._gate_result is not None and not self._gate_result.is_ok:
            return "FAILED"
        if self.warnings:
            return "WARNING"
        return "SUCCESS"

    @property
    def status_text(self) -> str:
        if not self.has_result:
            return "NO RESULT"
        if self.blocking_errors:
            return "FAILED"
        if self._gate_result is not None and not self._gate_result.is_ok:
            return "GATE FAILED"
        if self.warnings:
            # Keep SUCCESS vs WARNING distinct but show hardware note separately
            return "SUCCESS — REVIEW WARNINGS"
        return "SUCCESS"

    @property
    def eligibility_text(self) -> str:
        if not self.has_result:
            return "Not eligible — no result"
        if self._gate_result is not None:
            auth = self._gate_result.authorization.value
            if self._gate_result.is_ok:
                pending = self._gate_result.pending_gates
                if pending:
                    return f"Eligible for {auth} ({len(pending)} gate(s) pending)"
                return f"Eligible for {auth}"
            failed = self._gate_result.failed_gates
            names = ", ".join(g.gate_id.value for g in failed)
            return f"Not eligible — {auth} ({names} failed)"
        if self.review_ok:
            return "Eligible for preview (software review passed)"
        return "Not eligible — blocking errors"

    @property
    def gate_failure_summary(self) -> str:
        """Human-readable summary of gate failures, or empty if none."""
        if self._gate_result is None:
            return ""
        failed = self._gate_result.failed_gates
        pending = self._gate_result.pending_gates
        parts: list[str] = []
        for g in failed:
            parts.append(f"{g.gate_id.value}: {g.message}")
        for g in pending:
            parts.append(f"{g.gate_id.value}: {g.message} (pending)")
        return "; ".join(parts)

    # -- Review decision ---------------------------------------------------

    @property
    def decision(self) -> ReviewDecision | None:
        return self._decision

    def accept(self) -> None:
        self._decision = ReviewDecision.ACCEPTED_FOR_PREVIEW
        self._notify()

    def reject(self) -> None:
        self._decision = ReviewDecision.REJECTED
        self._notify()

    def needs_recalibration(self) -> None:
        self._decision = ReviewDecision.NEEDS_RECALIBRATION
        self._notify()

    def reset_decision(self) -> None:
        self._decision = None
        self._notify()

    # -- Advanced / technical ---------------------------------------------

    @property
    def camera_matrix_text(self) -> str:
        if not self._result or self._result.camera_matrix is None:
            return "—"
        k = self._result.camera_matrix
        return (
            f"[ {k[0, 0]:8.2f} {k[0, 1]:8.2f} {k[0, 2]:8.2f} ]\n"
            f"[ {k[1, 0]:8.2f} {k[1, 1]:8.2f} {k[1, 2]:8.2f} ]\n"
            f"[ {k[2, 0]:8.2f} {k[2, 1]:8.2f} {k[2, 2]:8.2f} ]"
        )

    @property
    def distortion_text(self) -> str:
        if not self._result or self._result.distortion_coeffs is None:
            return "—"
        coeffs = self._result.distortion_coeffs
        return ", ".join(f"{float(c):.4f}" for c in coeffs)

    @property
    def created_at_text(self) -> str:
        if not self._result:
            return "—"
        return time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(self._result.created_at)
        )


def _rotation_to_quat(
    r: NDArray[np.float64],
) -> tuple[float, float, float, float] | None:
    if r.shape != (3, 3) or not np.all(np.isfinite(r)):
        return None
    if not np.allclose(r @ r.T, np.eye(3), atol=1e-6):
        return None
    if np.linalg.det(r) < 0.0:
        return None
    trace = float(np.trace(r))
    if trace > 0.0:
        s = float(np.sqrt(trace + 1.0)) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = float(np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = float(np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = float(np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    n = float(np.sqrt(w * w + x * x + y * y + z * z))
    if n == 0.0 or not np.isfinite(n):
        return None
    return (float(w) / n, float(x) / n, float(y) / n, float(z) / n)
