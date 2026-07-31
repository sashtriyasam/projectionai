"""Tests for calibration validator."""

from __future__ import annotations

from projectionai.calibration.types import (
    CalibrationData,
    CalibrationResult,
)
from projectionai.calibration.validator import (
    CalibrationCheck,
    CalibrationValidator,
    ConfidenceCheck,
    PoseSanityCheck,
    ReprojectionErrorCheck,
    SampleCountCheck,
    ValidationIssue,
    ValidationReport,
)


def _make_result(
    reprojection_error: float = 0.0,
    num_samples: int = 10,
    confidence: float = 0.8,
) -> CalibrationResult:
    return CalibrationResult(
        success=True,
        data=CalibrationData(
            reprojection_error=reprojection_error,
            num_samples=num_samples,
            confidence=confidence,
        ),
    )


class TestValidationIssue:
    def test_defaults(self) -> None:
        issue = ValidationIssue(message="Test")
        assert issue.severity == "warning"
        assert issue.category == "general"

    def test_error_severity(self) -> None:
        issue = ValidationIssue(message="Bad", severity="error")
        assert issue.severity == "error"


class TestValidationReport:
    def test_defaults(self) -> None:
        report = ValidationReport()
        assert not report.passed
        assert report.issues == []
        assert report.error_count == 0
        assert report.warning_count == 0

    def test_error_and_warning_counts(self) -> None:
        report = ValidationReport(
            passed=False,
            issues=[
                ValidationIssue("E1", severity="error"),
                ValidationIssue("E2", severity="error"),
                ValidationIssue("W1", severity="warning"),
            ],
        )
        assert report.error_count == 2
        assert report.warning_count == 1


class TestReprojectionErrorCheck:
    def test_passes_within_threshold(self) -> None:
        check = ReprojectionErrorCheck(max_error=2.0)
        result = _make_result(reprojection_error=1.0)
        assert check.check(result) is None

    def test_fails_exceeds_threshold(self) -> None:
        check = ReprojectionErrorCheck(max_error=2.0)
        result = _make_result(reprojection_error=5.0)
        issue = check.check(result)
        assert issue is not None
        assert issue.severity == "error"
        assert "5.00" in issue.message

    def test_warning_when_no_data(self) -> None:
        check = ReprojectionErrorCheck()
        result = CalibrationResult(success=True)
        issue = check.check(result)
        assert issue is not None
        assert issue.severity == "warning"


class TestSampleCountCheck:
    def test_passes_with_enough_samples(self) -> None:
        check = SampleCountCheck(min_samples=5)
        result = _make_result(num_samples=10)
        assert check.check(result) is None

    def test_fails_with_few_samples(self) -> None:
        check = SampleCountCheck(min_samples=5)
        result = _make_result(num_samples=2)
        issue = check.check(result)
        assert issue is not None
        assert "2" in issue.message

    def test_error_for_very_few(self) -> None:
        check = SampleCountCheck(min_samples=5)
        result = _make_result(num_samples=1)
        issue = check.check(result)
        assert issue is not None
        assert issue.severity == "error"

    def test_no_data_no_issue(self) -> None:
        check = SampleCountCheck()
        result = CalibrationResult(success=True)
        assert check.check(result) is None


class TestConfidenceCheck:
    def test_passes_with_high_confidence(self) -> None:
        check = ConfidenceCheck(min_confidence=0.5)
        result = _make_result(confidence=0.9)
        assert check.check(result) is None

    def test_fails_with_low_confidence(self) -> None:
        check = ConfidenceCheck(min_confidence=0.5)
        result = _make_result(confidence=0.2)
        issue = check.check(result)
        assert issue is not None
        assert issue.severity == "warning"

    def test_warning_when_no_confidence(self) -> None:
        check = ConfidenceCheck()
        result = CalibrationResult(success=True, data=CalibrationData())
        issue = check.check(result)
        assert issue is not None
        assert issue.severity == "warning"


class TestPoseSanityCheck:
    def test_passes_with_valid_poses(self) -> None:
        check = PoseSanityCheck()
        data = CalibrationData(
            projector_pose={"p1": {"x": 1.0, "y": 2.0}},
            camera_pose={"c1": {"x": 0.0}},
            surface_pose={"s1": {"width": 2.0}},
        )
        result = CalibrationResult(success=True, data=data)
        assert check.check(result) is None

    def test_detects_nan(self) -> None:
        check = PoseSanityCheck()

        data = CalibrationData(
            projector_pose={"p1": {"x": float("nan")}},
        )
        result = CalibrationResult(success=True, data=data)
        issue = check.check(result)
        assert issue is not None
        assert issue.severity == "error"

    def test_detects_inf(self) -> None:
        check = PoseSanityCheck()
        data = CalibrationData(
            projector_pose={"p1": {"x": float("inf")}},
        )
        result = CalibrationResult(success=True, data=data)
        issue = check.check(result)
        assert issue is not None

    def test_detects_nan_in_camera(self) -> None:
        check = PoseSanityCheck()

        data = CalibrationData(
            camera_pose={"c1": {"rotation": float("nan")}},
        )
        result = CalibrationResult(success=True, data=data)
        issue = check.check(result)
        assert issue is not None

    def test_no_data_is_fine(self) -> None:
        check = PoseSanityCheck()
        result = CalibrationResult(success=True)
        assert check.check(result) is None

    def test_non_dict_pose_ignored(self) -> None:
        """Non-dict pose entries should be skipped without error."""
        check = PoseSanityCheck()
        data = CalibrationData(
            projector_pose={"p1": "string_value_not_a_dict"},
        )
        result = CalibrationResult(success=True, data=data)
        assert check.check(result) is None


class TestCalibrationValidator:
    def test_default_checks_registered(self) -> None:
        validator = CalibrationValidator()
        assert len(validator.checks) >= 4

    def test_validate_passing_result(self) -> None:
        validator = CalibrationValidator()
        result = _make_result()
        report = validator.validate(result)
        assert report.passed
        assert report.quality_score >= 0.5

    def test_validate_failing_result(self) -> None:
        validator = CalibrationValidator()
        result = _make_result(reprojection_error=10.0, num_samples=1, confidence=0.1)
        report = validator.validate(result)
        assert not report.passed
        assert report.error_count >= 1

    def test_add_custom_check(self) -> None:
        validator = CalibrationValidator()

        class AlwaysFailCheck(CalibrationCheck):
            def check(self, result: CalibrationResult) -> ValidationIssue:
                return ValidationIssue("Always fails", severity="error")

        validator.add_check(AlwaysFailCheck())
        result = _make_result()
        report = validator.validate(result)
        assert not report.passed

    def test_remove_check(self) -> None:
        validator = CalibrationValidator()
        check = validator.checks[0]
        validator.remove_check(check)
        assert check not in validator.checks

    def test_clear_checks(self) -> None:
        validator = CalibrationValidator()
        validator.clear_checks()
        assert len(validator.checks) == 0

    def test_validate_and_updates_result(self) -> None:
        validator = CalibrationValidator()
        result = _make_result(reprojection_error=10.0)
        report = validator.validate_and_update(result)
        assert len(result.validation_errors) >= 1
        assert result.quality_score == report.quality_score

    def test_check_exception_is_caught(self) -> None:
        validator = CalibrationValidator()

        class ExplodingCheck(CalibrationCheck):
            def check(self, result: CalibrationResult) -> ValidationIssue:
                msg = "Boom!"
                raise RuntimeError(msg)

        validator.add_check(ExplodingCheck())
        result = _make_result()
        report = validator.validate(result)
        assert report.warning_count >= 1

    def test_quality_score_perfect(self) -> None:
        validator = CalibrationValidator()
        result = _make_result(reprojection_error=0.1, num_samples=50, confidence=0.99)
        report = validator.validate(result)
        assert report.quality_score >= 0.9
