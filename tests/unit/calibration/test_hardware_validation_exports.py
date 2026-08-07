"""Contract tests for the ``hardware_validation`` package export surface.

``__all__`` groups its 16 names by the module they are imported from, one
comment per group. This test locks the exact ordered export list and
verifies every exported name is actually bound on the package.
"""

from __future__ import annotations

import projectionai.calibration.hardware_validation as hwv

_EXPECTED_ALL = [
    # Models
    "CalibrationReport",
    "CaptureSequence",
    "HardwareValidationError",
    "HardwareValidationSession",
    "ValidationMetrics",
    # Runner
    "CameraAccess",
    "ValidationRunner",
    # Environment
    "EnvironmentInfo",
    "collect_environment",
    # Export
    "export_calibration_package",
    "export_captured_images",
    "export_report_json",
    "export_report_pdf",
    "export_visualizations",
    "report_to_dict",
    # Visualization
    "render_capture_contact_sheet",
    "render_correspondence_map",
    "render_coverage_map",
    "render_error_histogram",
]


def test_all_lists_expected_names_in_module_groups() -> None:
    assert hwv.__all__ == _EXPECTED_ALL


def test_every_exported_name_is_bound() -> None:
    assert len(hwv.__all__) == len(set(hwv.__all__))
    for name in hwv.__all__:
        assert getattr(hwv, name) is not None
