"""Real-hardware validation of the projector calibration pipeline.

This package runs the existing gray-code projector calibration pipeline
(``GrayCodeProjectorCalibration``, ``PatternCaptureSession``,
``ReprojectionValidator``) against real cameras and projectors and turns
the outcome into shareable artifacts (JSON reports, visualizations, a PDF
report, and a zip package). It deliberately introduces **no new
algorithms**: the existing pipeline is exercised as-is on real hardware.

Layers:

1. **Models** — :class:`CalibrationReport`, :class:`CaptureSequence`,
   :class:`ValidationMetrics`, :class:`HardwareValidationSession`.
2. **Runner** — :class:`ValidationRunner` executes the 9-step validation
   flow against injected ``CameraAccess`` / ``PatternProjector`` seams so
   the whole flow is testable with stubs and no hardware.
3. **Environment** — :func:`collect_environment` snapshots the host
   runtime for the report.
4. **Visualization** — pure cv2/numpy renderers for the report.
5. **Export** — JSON / PNG / PDF / zip serialisation of the report.

Usage::

    from projectionai.calibration.hardware_validation import ValidationRunner

    runner = ValidationRunner(camera_access=cameras, projector_factory=factory)
    report = await runner.run()
"""

from __future__ import annotations

from projectionai.calibration.hardware_validation.environment import (
    EnvironmentInfo,
    collect_environment,
)
from projectionai.calibration.hardware_validation.export import (
    export_calibration_package,
    export_captured_images,
    export_report_json,
    export_report_pdf,
    export_visualizations,
    report_to_dict,
)
from projectionai.calibration.hardware_validation.models import (
    CalibrationReport,
    CaptureSequence,
    HardwareValidationError,
    HardwareValidationSession,
    ValidationMetrics,
)
from projectionai.calibration.hardware_validation.runner import (
    CameraAccess,
    ValidationRunner,
)
from projectionai.calibration.hardware_validation.visualization import (
    render_capture_contact_sheet,
    render_correspondence_map,
    render_coverage_map,
    render_error_histogram,
)

# Grouped by source module (see section comments), so RUF022's
# alphabetical order does not apply.
__all__ = [  # noqa: RUF022
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
