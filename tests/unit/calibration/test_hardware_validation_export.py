"""Unit tests for the hardware validation report exporters.

Every export function is pure: it reads a :class:`CalibrationReport` and
writes files. These tests drive them with a fully populated synthetic
report and verify the on-disk artifacts (JSON document, PNG frames,
visualization images, multi-page A4 PDF, and the zip calibration
package) without any hardware.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from projectionai.calibration.hardware_validation.environment import EnvironmentInfo
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
    ValidationMetrics,
)
from projectionai.calibration.types import CalibrationStatus
from projectionai.infrastructure.display import DisplayInfo
from projectionai.infrastructure.projector_calibration.validation import (
    ValidationReport,
)
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationResult,
)


def _environment() -> EnvironmentInfo:
    return EnvironmentInfo(
        opencv_version="5.0.0",
        python_version="3.12",
        platform="win32",
        machine="AMD64",
        processor="x86_64",
        cpu_count=8,
        memory_bytes=16 * 1024**3,
        started_at="2026-01-01T00:00:00+00:00",
    )


def _capture_sequence() -> CaptureSequence:
    return CaptureSequence(
        camera_id="cam-0",
        projector_resolution=(32, 16),
        camera_resolution=(8, 8),
        num_patterns=2,
        captured_frames=(
            np.zeros((8, 8), dtype=np.uint8),
            np.full((8, 8), 255, dtype=np.uint8),
        ),
        capture_times=(0.1, 0.2),
        total_capture_seconds=0.3,
    )


def _correspondence_map() -> CorrespondenceMap:
    projector_x = np.full((8, 8), np.nan, dtype=np.float32)
    projector_y = np.full((8, 8), np.nan, dtype=np.float32)
    mask = np.zeros((8, 8), dtype=np.bool_)
    for y in range(2, 6):
        for x in range(2, 6):
            projector_x[y, x] = float(x) * 10.0
            projector_y[y, x] = float(y) * 10.0
            mask[y, x] = True
    return CorrespondenceMap(
        projector_x=projector_x,
        projector_y=projector_y,
        mask=mask,
        image_size=(8, 8),
    )


def _calibration_result() -> ProjectorCalibrationResult:
    return ProjectorCalibrationResult(
        projector_intrinsics=np.eye(3, dtype=np.float64),
        projector_resolution=(32, 16),
        projector_pose=np.eye(4, dtype=np.float64),
        reprojection_error=0.5,
        num_correspondences=16,
        coverage=0.9,
        confidence=0.95,
        per_point_errors=(0.4, 0.6),
        camera_matrix=np.eye(3, dtype=np.float64),
        distortion_coeffs=np.zeros(5, dtype=np.float64),
        image_size=(8, 8),
    )


def _validation() -> ValidationReport:
    return ValidationReport(
        rms_error=0.5,
        mean_error=0.4,
        max_error=0.9,
        inlier_ratio=1.0,
        coverage=0.9,
        num_sampled=16,
        per_point_errors=(0.4, 0.6),
        passed=True,
    )


def _metrics() -> ValidationMetrics:
    return ValidationMetrics(
        rms_error=0.5,
        mean_error=0.4,
        max_error=0.9,
        inlier_ratio=1.0,
        coverage=0.9,
        corner_error=0.7,
        confidence=0.95,
        num_correspondences=16,
        missing_correspondences=48,
        num_calibration_images=2,
        calibration_seconds=0.1,
        per_point_errors=(0.4, 0.6),
        passed=True,
    )


def _report() -> CalibrationReport:
    return CalibrationReport(
        session_id="hwval-export",
        created_at="2026-01-01T00:00:00+00:00",
        camera_id="cam-0",
        camera_model="Synthetic",
        projector_display=DisplayInfo(
            index=0, name="projector", width=1280, height=720, is_primary=True
        ),
        projector_resolution=(32, 16),
        environment=_environment(),
        capture=_capture_sequence(),
        correspondences=_correspondence_map(),
        calibration=_calibration_result(),
        validation=_validation(),
        metrics=_metrics(),
        status=CalibrationStatus.COMPLETED,
        step_times={"connect_camera": 0.01, "capture": 0.3},
        warnings=("low coverage",),
        errors=(),
        total_seconds=0.5,
    )


def _failed_report() -> CalibrationReport:
    return replace(
        _report(),
        status=CalibrationStatus.FAILED,
        capture=None,
        correspondences=None,
        calibration=None,
        validation=None,
        metrics=None,
        errors=("No cameras detected",),
    )


class TestReportToDict:
    def test_top_level_fields(self) -> None:
        data = report_to_dict(_report())
        assert data["session_id"] == "hwval-export"
        assert data["status"] == "completed"
        assert data["camera_id"] == "cam-0"
        assert data["camera_model"] == "Synthetic"
        assert data["projector_resolution"] == [32, 16]
        assert data["step_times"] == {"connect_camera": 0.01, "capture": 0.3}
        assert data["warnings"] == ["low coverage"]
        assert data["errors"] == []
        assert data["total_seconds"] == pytest.approx(0.5)

    def test_display_summary(self) -> None:
        data = report_to_dict(_report())
        assert data["projector_display"] == {
            "index": 0,
            "name": "projector",
            "width": 1280,
            "height": 720,
            "is_primary": True,
        }

    def test_capture_summarised_not_inlined(self) -> None:
        data = report_to_dict(_report())
        capture = data["capture"]
        assert capture["num_patterns"] == 2
        assert capture["projector_resolution"] == [32, 16]
        assert capture["camera_resolution"] == [8, 8]
        assert capture["capture_times"] == [0.1, 0.2]
        assert capture["total_capture_seconds"] == pytest.approx(0.3)
        assert "captured_frames" not in capture  # arrays travel in the package

    def test_matrices_serialised_as_lists(self) -> None:
        data = report_to_dict(_report())
        calibration = data["calibration"]
        assert calibration["projector_intrinsics"] == [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        assert calibration["distortion_coeffs"] == [0.0, 0.0, 0.0, 0.0, 0.0]
        assert calibration["image_size"] == [8, 8]

    def test_environment_and_validation(self) -> None:
        data = report_to_dict(_report())
        assert data["environment"]["opencv_version"] == "5.0.0"
        assert data["environment"]["cpu_count"] == 8
        assert data["validation"]["rms_error"] == pytest.approx(0.5)
        assert data["validation"]["passed"] is True
        assert data["metrics"]["corner_error"] == pytest.approx(0.7)
        assert data["metrics"]["passed"] is True

    def test_per_point_errors_compact_summary(self) -> None:
        data = report_to_dict(_report())
        for section in ("validation", "metrics"):
            summary = data[section]["per_point_errors"]
            assert set(summary) == {"p50", "p90", "p99"}
            assert summary["p50"] <= summary["p90"] <= summary["p99"]
            # (0.4, 0.6) under numpy's default linear interpolation:
            # p50 = 0.4 + 0.5*(0.2) = 0.5, p90 = 0.4 + 0.9*(0.2) = 0.58,
            # p99 = 0.4 + 0.99*(0.2) = 0.598.
            assert summary["p50"] == pytest.approx(0.5)
            assert summary["p90"] == pytest.approx(0.58)
            assert summary["p99"] == pytest.approx(0.598)

    def test_per_point_errors_empty_summary(self) -> None:
        report = replace(
            _report(),
            validation=replace(_validation(), per_point_errors=()),
            metrics=replace(_metrics(), per_point_errors=()),
        )
        data = report_to_dict(report)
        assert data["validation"]["per_point_errors"] == {}
        assert data["metrics"]["per_point_errors"] == {}


class TestExportReportJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        path = export_report_json(_report(), tmp_path / "report.json")
        assert path == tmp_path / "report.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["session_id"] == "hwval-export"
        assert data["status"] == "completed"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = export_report_json(
            _report(), tmp_path / "nested" / "deep" / "report.json"
        )
        assert path.exists()
        assert path.parent.is_dir()

    def test_non_finite_metric_fails_export(self, tmp_path: Path) -> None:
        report = replace(
            _report(),
            metrics=replace(_metrics(), rms_error=float("nan")),
        )
        with pytest.raises(ValueError, match="Out of range float"):
            export_report_json(report, tmp_path / "report.json")
        assert not (tmp_path / "report.json").exists()


class TestExportCapturedImages:
    def test_writes_one_png_per_frame(self, tmp_path: Path) -> None:
        paths = export_captured_images(_report(), tmp_path)
        assert len(paths) == 2
        assert (tmp_path / "frame_000.png").exists()
        assert (tmp_path / "frame_001.png").exists()
        for path in paths:
            image = Image.open(path)
            assert image.size == (8, 8)
            image.close()

    def test_returns_empty_when_no_capture(self, tmp_path: Path) -> None:
        report = replace(_report(), capture=None)
        assert export_captured_images(report, tmp_path) == ()
        assert not (tmp_path / "frame_000.png").exists()


class TestExportVisualizations:
    def test_writes_all_available_images(self, tmp_path: Path) -> None:
        paths = export_visualizations(_report(), tmp_path)
        names = {path.name for path in paths}
        assert {
            "correspondence_map.png",
            "coverage_map.png",
            "captures_contact_sheet.png",
            "error_histogram.png",
        } <= names
        for path in paths:
            assert path.exists()
            assert path.suffix == ".png"

    def test_returns_empty_for_failed_report(self, tmp_path: Path) -> None:
        assert export_visualizations(_failed_report(), tmp_path) == ()

    def test_coverage_map_skipped_when_resolution_unknown(self, tmp_path: Path) -> None:
        report = replace(_report(), projector_resolution=None)
        paths = export_visualizations(report, tmp_path)
        names = {path.name for path in paths}
        assert "correspondence_map.png" in names
        assert "coverage_map.png" not in names


class TestExportReportPdf:
    def test_writes_multi_page_pdf(self, tmp_path: Path) -> None:
        path = export_report_pdf(_report(), tmp_path / "report.pdf")
        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF")
        assert path.stat().st_size > 1000  # summary + visualization pages

    def test_failed_report_still_gets_summary_page(self, tmp_path: Path) -> None:
        path = export_report_pdf(_failed_report(), tmp_path / "failed.pdf")
        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF")

    def test_long_summary_spills_onto_extra_pages(self, tmp_path: Path) -> None:
        # A report with many step times/warnings overflows one A4 page;
        # the renderer must continue on additional summary pages instead
        # of silently dropping the overflow.
        report = replace(
            _report(),
            step_times={f"step_{i:03d}": 0.01 for i in range(120)},
            warnings=tuple(f"warning {i}" for i in range(60)),
        )
        long_path = export_report_pdf(report, tmp_path / "long.pdf")
        baseline_path = export_report_pdf(_report(), tmp_path / "baseline.pdf")
        assert long_path.stat().st_size > baseline_path.stat().st_size
        # The long report carries at least one extra summary page.
        assert long_path.read_bytes().count(
            b"/Type /Page"
        ) > baseline_path.read_bytes().count(b"/Type /Page")


class TestExportCalibrationPackage:
    def test_zip_layout(self, tmp_path: Path) -> None:
        path = export_calibration_package(_report(), tmp_path / "package.zip")
        assert path.exists()
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        assert "report.json" in names
        assert "calibration.json" in names
        assert "visualizations/correspondence_map.png" in names
        assert "visualizations/coverage_map.png" in names
        assert "visualizations/captures_contact_sheet.png" in names
        assert "visualizations/error_histogram.png" in names
        assert "captures/frame_000.png" in names
        assert "captures/frame_001.png" in names

    def test_package_omits_optional_sections_when_missing(self, tmp_path: Path) -> None:
        report = replace(
            _report(),
            capture=None,
            calibration=None,
            correspondences=None,
            validation=None,
        )
        path = export_calibration_package(report, tmp_path / "minimal.zip")
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        assert names == {"report.json"}
