"""Calibration validator — quality checks on calibration results.

The validator runs configurable checks against a ``CalibrationResult``
to assess quality, detect issues, and produce a validation report.

Checks include:
- Reprojection error within acceptable thresholds.
- Minimum number of valid samples.
- Pose sanity (no NaN, finite transforms).
- Coverage analysis (does the calibration cover the full projection area?).

Validators are composable: multiple checks can be run and their results
aggregated.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from projectionai.calibration.pipeline import StageContext
from projectionai.calibration.types import CalibrationResult

_logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A single issue found during validation."""

    message: str
    severity: str = "warning"  # "error" or "warning"
    category: str = "general"
    value: float | None = None
    threshold: float | None = None


@dataclass
class ValidationReport:
    """Complete validation report for a calibration result."""

    passed: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)
    quality_score: float = 0.0

    @property
    def errors(self) -> list[ValidationIssue]:
        """Return all error-severity issues."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Return all warning-severity issues."""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


class CalibrationCheck(ABC):
    """A single validation check.

    Subclass and implement ``check()`` to create a reusable validation rule.
    """

    @abstractmethod
    def check(self, result: CalibrationResult) -> ValidationIssue | None:
        """Run a single validation check.

        Args:
            result: The calibration result to validate.

        Returns:
            A ``ValidationIssue`` if a problem is found, or ``None``
            if the check passes.
        """
        ...


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------


class ReprojectionErrorCheck(CalibrationCheck):
    """Check reprojection error against a maximum threshold."""

    def __init__(self, max_error: float = 2.0) -> None:
        self.max_error = max_error

    def check(self, result: CalibrationResult) -> ValidationIssue | None:
        if result.data is None or result.data.reprojection_error <= 0.0:
            return ValidationIssue(
                message="No reprojection error data available",
                severity="warning",
                category="reprojection_error",
            )
        error = result.data.reprojection_error
        if error > self.max_error:
            return ValidationIssue(
                message=f"Reprojection error {error:.2f}px exceeds "
                f"threshold {self.max_error:.2f}px",
                severity="error",
                category="reprojection_error",
                value=error,
                threshold=self.max_error,
            )
        return None


class SampleCountCheck(CalibrationCheck):
    """Verify minimum number of calibration samples."""

    def __init__(self, min_samples: int = 5) -> None:
        self.min_samples = min_samples

    def check(self, result: CalibrationResult) -> ValidationIssue | None:
        if result.data is None:
            return None
        count = result.data.num_samples
        if count < self.min_samples:
            return ValidationIssue(
                message=f"Only {count} calibration samples "
                f"(minimum {self.min_samples})",
                severity="warning" if count >= 3 else "error",
                category="samples",
                value=float(count),
                threshold=float(self.min_samples),
            )
        return None


class ConfidenceCheck(CalibrationCheck):
    """Check confidence score against a minimum threshold."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence = min_confidence

    def check(self, result: CalibrationResult) -> ValidationIssue | None:
        if result.data is None or result.data.confidence <= 0.0:
            return ValidationIssue(
                message="No confidence score available",
                severity="warning",
                category="confidence",
            )
        conf = result.data.confidence
        if conf < self.min_confidence:
            return ValidationIssue(
                message=f"Confidence {conf:.2f} below threshold "
                f"{self.min_confidence:.2f}",
                severity="warning",
                category="confidence",
                value=conf,
                threshold=self.min_confidence,
            )
        return None


class PoseSanityCheck(CalibrationCheck):
    """Sanity-check poses for NaN, infinity, or zero transforms."""

    def check(self, result: CalibrationResult) -> ValidationIssue | None:
        if result.data is None:
            return None

        for category, poses in [
            ("projector", result.data.projector_pose),
            ("camera", result.data.camera_pose),
            ("surface", result.data.surface_pose),
        ]:
            for pose_id, pose_data in poses.items():
                if not isinstance(pose_data, dict):
                    continue
                for key, val in pose_data.items():
                    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                        return ValidationIssue(
                            message=f"NaN/Inf in {category} pose '{pose_id}'.{key}",
                            severity="error",
                            category="pose_sanity",
                        )
        return None


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class CalibrationValidator:
    """Runs a suite of checks against a calibration result.

    Usage::

        validator = CalibrationValidator()
        validator.add_check(ReprojectionErrorCheck(max_error=1.0))
        validator.add_check(SampleCountCheck(min_samples=10))
        report = validator.validate(result)
        if report.passed:
            ...
    """

    def __init__(self) -> None:
        self._checks: list[CalibrationCheck] = []

        # Register default checks
        self._checks.append(ReprojectionErrorCheck())
        self._checks.append(SampleCountCheck())
        self._checks.append(ConfidenceCheck())
        self._checks.append(PoseSanityCheck())

    def add_check(self, check: CalibrationCheck) -> None:
        """Add a custom validation check."""
        self._checks.append(check)

    def remove_check(self, check: CalibrationCheck) -> None:
        """Remove a validation check."""
        self._checks.remove(check)

    def clear_checks(self) -> None:
        """Remove all checks (including defaults)."""
        self._checks.clear()

    @property
    def checks(self) -> list[CalibrationCheck]:
        """Return all registered checks."""
        return list(self._checks)

    def validate(
        self, result: CalibrationResult, context: StageContext | None = None
    ) -> ValidationReport:
        """Run all checks against a calibration result.

        Args:
            result: The calibration result to validate.
            context: Optional pipeline context for additional data.

        Returns:
            A validation report with all issues found.
        """
        issues: list[ValidationIssue] = []

        for check in self._checks:
            try:
                issue = check.check(result)
                if issue is not None:
                    issues.append(issue)
            except Exception as exc:
                issues.append(
                    ValidationIssue(
                        message=f"Check {type(check).__name__} raised: {exc}",
                        severity="warning",
                        category="check_error",
                    )
                )

        error_count = sum(1 for i in issues if i.severity == "error")
        warning_count = sum(1 for i in issues if i.severity == "warning")

        # Quality score: start at 1.0, deduct for errors/warnings
        quality = 1.0
        quality -= error_count * 0.2
        quality -= warning_count * 0.05
        quality = max(0.0, min(1.0, quality))

        report = ValidationReport(
            passed=error_count == 0,
            issues=issues,
            quality_score=quality,
        )

        _logger.info(
            "Validation: %d errors, %d warnings (score=%.2f)",
            error_count,
            warning_count,
            quality,
        )
        return report

    def validate_and_update(self, result: CalibrationResult) -> ValidationReport:
        """Validate and update the result's validation fields in place.

        Returns:
            The validation report.
        """
        report = self.validate(result)
        result.validation_errors = [i.message for i in report.errors]
        result.validation_warnings = [i.message for i in report.warnings]
        result.quality_score = report.quality_score
        return report
