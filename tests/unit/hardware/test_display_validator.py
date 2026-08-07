"""Tests for the display validator — pre-flight output checks."""

from __future__ import annotations

from projectionai.hardware.display_validator import (
    DisplayValidator,
    ValidateInputs,
    ValidationReport,
    ValidationSeverity,
)
from projectionai.hardware.models import DisplayInfo, DisplayKind, DisplayMode
from projectionai.infrastructure.display.mock_provider import make_display

VALIDATOR = DisplayValidator()


def _monitor(display_id: str = "mon-1") -> DisplayInfo:
    return make_display(
        display_id,
        0,
        "Dell U2720Q",
        manufacturer="Dell",
        model="U2720Q",
        width=1920,
        height=1080,
    )


def _projector(display_id: str = "proj-1") -> DisplayInfo:
    return make_display(
        display_id,
        1,
        "Epson EB-2250U",
        manufacturer="Epson",
        model="EB-2250U",
        width=1920,
        height=1200,
    )


def _codes(report: ValidationReport, severity: ValidationSeverity) -> set[str]:
    return {issue.code for issue in report.issues if issue.severity is severity}


def test_empty_inputs_is_ok() -> None:
    report = VALIDATOR.validate(ValidateInputs(displays=[_projector()]))
    assert report.is_ok
    assert report.errors == ()
    assert report.summary == "all checks passed"


def test_renderer_not_ready_blocks() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(displays=[_projector()], renderer_ready=False)
    )
    assert "renderer_not_ready" in _codes(report, ValidationSeverity.ERROR)
    assert not report.is_ok


def test_no_display_connected_blocks() -> None:
    report = VALIDATOR.validate(ValidateInputs(displays=[]))
    assert "no_display_connected" in _codes(report, ValidationSeverity.ERROR)
    assert not report.is_ok


def test_live_display_not_found_blocks() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(displays=[_projector()], live_display_id="ghost")
    )
    assert "live_display_not_found" in _codes(report, ValidationSeverity.ERROR)


def test_preview_display_not_found_blocks() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(displays=[_projector()], preview_display_id="ghost")
    )
    assert "preview_display_not_found" in _codes(report, ValidationSeverity.ERROR)


def test_no_projector_available_blocks_when_no_target() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(
            displays=[_monitor()], live_display_id=None, require_projector=True
        )
    )
    assert "no_projector_available" in _codes(report, ValidationSeverity.ERROR)
    assert not report.is_ok


def test_live_target_not_projector_warns() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(displays=[_monitor()], live_display_id="mon-1")
    )
    assert "live_target_not_projector" in _codes(report, ValidationSeverity.WARNING)
    assert report.is_ok


def test_unsupported_resolution_blocks() -> None:
    proj = _projector()
    report = VALIDATOR.validate(
        ValidateInputs(
            displays=[proj],
            live_display_id="proj-1",
            target_mode=DisplayMode(800, 600, 60.0),
        )
    )
    assert "resolution_unsupported" in _codes(report, ValidationSeverity.ERROR)
    assert not report.is_ok


def test_low_resolution_warns() -> None:
    small = make_display(
        "proj-1", 1, "Epson", manufacturer="Epson", width=800, height=600
    )
    report = VALIDATOR.validate(
        ValidateInputs(displays=[small], live_display_id="proj-1")
    )
    assert "low_resolution" in _codes(report, ValidationSeverity.WARNING)


def test_low_refresh_rate_warns() -> None:
    low = make_display("proj-1", 1, "Epson", manufacturer="Epson", refresh_rate=30.0)
    report = VALIDATOR.validate(
        ValidateInputs(displays=[low], live_display_id="proj-1")
    )
    assert "low_refresh_rate" in _codes(report, ValidationSeverity.WARNING)


def test_software_renderer_warns() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(
            displays=[_projector()],
            live_display_id="proj-1",
            gpu_name="llvmpipe (LLVM 15.0.7)",
        )
    )
    assert "software_renderer" in _codes(report, ValidationSeverity.WARNING)


def test_duplicate_output_warns() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(
            displays=[_projector()],
            live_display_id="proj-1",
            preview_display_id="proj-1",
        )
    )
    assert "duplicate_output" in _codes(report, ValidationSeverity.WARNING)


def test_window_not_available_blocks_live_switch() -> None:
    report = VALIDATOR.validate(
        ValidateInputs(
            displays=[_projector()],
            live_display_id="proj-1",
            window_available=False,
        )
    )
    assert "window_not_available" in _codes(report, ValidationSeverity.ERROR)
    assert not report.is_ok


def test_projector_kind_is_respected() -> None:
    assert _projector().kind is DisplayKind.PROJECTOR
