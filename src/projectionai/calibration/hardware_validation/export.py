"""Export of hardware validation reports.

Serialises a completed :class:`CalibrationReport` into shareable
artifacts using only the standard library and existing dependencies
(Pillow for the A4 PDF and PNG images — no new dependencies):

- ``export_report_json`` — the full report as a JSON document.
- ``export_captured_images`` — the captured gray-code frames as PNGs.
- ``export_visualizations`` — correspondence/coverage/contact-sheet and
  error-histogram images rendered from the report.
- ``export_report_pdf`` — a multi-page A4 PDF (summary + visualizations).
- ``export_calibration_package`` — a zip bundle with the JSON report,
  calibration matrices, captures, and visualizations.

All functions are pure: they read a report and write files, so they are
testable with a synthetic report and no hardware.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from projectionai.calibration.hardware_validation.environment import (
    EnvironmentInfo,
)
from projectionai.calibration.hardware_validation.models import (
    CalibrationReport,
    CaptureSequence,
    ValidationMetrics,
)
from projectionai.calibration.hardware_validation.visualization import (
    render_capture_contact_sheet,
    render_correspondence_map,
    render_coverage_map,
    render_error_histogram,
)
from projectionai.infrastructure.display import DisplayInfo
from projectionai.infrastructure.projector_calibration.validation import (
    ValidationReport,
)
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationResult,
)

# A4 page in pixels at 96 dpi (210 x 297 mm).
_A4_WIDTH = 794
_A4_HEIGHT = 1123
_MARGIN = 60

# Font objects returned by Pillow (FreeTypeFont for TrueType fonts, the
# base ImageFont for the bundled default).
_Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------


def export_report_json(report: CalibrationReport, path: str | Path) -> Path:
    """Write the report to *path* as a JSON document.

    Returns:
        The resolved output path.
    """
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    path_obj.write_text(
        _json_bytes(report_to_dict(report)).decode("utf-8"), encoding="utf-8"
    )
    return path_obj


def report_to_dict(report: CalibrationReport) -> dict[str, Any]:
    """Convert a report into a JSON-safe dictionary.

    Captured frames and dense correspondence arrays are summarised (not
    inlined) so the document stays small; the full arrays travel with the
    zip package and captured-image exports.
    """
    data: dict[str, Any] = {
        "session_id": report.session_id,
        "created_at": report.created_at,
        "camera_id": report.camera_id,
        "camera_model": report.camera_model,
        "projector_display": (
            _display_dict(report.projector_display)
            if report.projector_display is not None
            else None
        ),
        "projector_resolution": (
            list(report.projector_resolution)
            if report.projector_resolution is not None
            else None
        ),
        "environment": _environment_dict(report.environment),
        "capture": (
            _capture_dict(report.capture) if report.capture is not None else None
        ),
        "correspondences": (
            _correspondences_dict(report.correspondences)
            if report.correspondences is not None
            else None
        ),
        "calibration": (
            _calibration_dict(report.calibration)
            if report.calibration is not None
            else None
        ),
        "validation": (
            _validation_dict(report.validation)
            if report.validation is not None
            else None
        ),
        "metrics": _metrics_dict(report.metrics)
        if report.metrics is not None
        else None,
        "status": report.status.value,
        "step_times": dict(report.step_times),
        "warnings": list(report.warnings),
        "errors": list(report.errors),
        "total_seconds": report.total_seconds,
    }
    return data


# ---------------------------------------------------------------------------
# Captured images
# ---------------------------------------------------------------------------


def export_captured_images(
    report: CalibrationReport, directory: str | Path
) -> tuple[Path, ...]:
    """Write each captured frame as ``frame_000.png`` in *directory*.

    Returns:
        The written image paths (empty when the report has no capture).
    """
    if report.capture is None:
        return ()
    directory_obj = Path(directory)
    directory_obj.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, frame in enumerate(report.capture.captured_frames):
        path = directory_obj / f"frame_{index:03d}.png"
        Image.fromarray(np.asarray(frame, dtype=np.uint8)).save(path, "PNG")
        paths.append(path)
    return tuple(paths)


# ---------------------------------------------------------------------------
# Visualizations
# ---------------------------------------------------------------------------


def export_visualizations(
    report: CalibrationReport, directory: str | Path
) -> tuple[Path, ...]:
    """Write rendered visualizations as PNGs in *directory*.

    Returns:
        The written image paths (may be empty for a failed run).
    """
    directory_obj = Path(directory)
    directory_obj.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, image in _build_visualizations(report):
        path = directory_obj / name
        image.save(path, "PNG")
        paths.append(path)
    return tuple(paths)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def export_report_pdf(report: CalibrationReport, path: str | Path) -> Path:
    """Write a multi-page A4 PDF summary of the report.

    The first page carries the report header, environment, metrics, and
    step timings; when the summary is longer than one page it continues
    on additional summary pages. Each available visualization gets its
    own page after the summary.

    Returns:
        The resolved output path.
    """
    pages = _render_summary_pages(report)
    for _, image in _build_visualizations(report):
        pages.append(_render_image_page(image))

    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if len(pages) == 1:
        pages[0].save(path_obj, "PDF")
    else:
        pages[0].save(path_obj, "PDF", save_all=True, append_images=pages[1:])
    return path_obj


# ---------------------------------------------------------------------------
# Zip calibration package
# ---------------------------------------------------------------------------


def export_calibration_package(report: CalibrationReport, path: str | Path) -> Path:
    """Write a zip bundle containing report, matrices, images, captures.

    Layout::

        report.json
        calibration.json
        visualizations/*.png
        captures/frame_000.png ...

    Returns:
        The resolved output path.
    """
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path_obj, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", _json_bytes(report_to_dict(report)))
        if report.calibration is not None:
            archive.writestr(
                "calibration.json", _json_bytes(_calibration_dict(report.calibration))
            )
        for name, image in _build_visualizations(report):
            archive.writestr(f"visualizations/{name}", _png_bytes(image))
        if report.capture is not None:
            for index, frame in enumerate(report.capture.captured_frames):
                archive.writestr(
                    f"captures/frame_{index:03d}.png",
                    _png_bytes(Image.fromarray(np.asarray(frame, dtype=np.uint8))),
                )
    return path_obj


# ---------------------------------------------------------------------------
# Internal: dictionary builders
# ---------------------------------------------------------------------------


def _environment_dict(environment: EnvironmentInfo) -> dict[str, Any]:
    return {
        "opencv_version": environment.opencv_version,
        "python_version": environment.python_version,
        "platform": environment.platform,
        "machine": environment.machine,
        "processor": environment.processor,
        "cpu_count": environment.cpu_count,
        "memory_bytes": environment.memory_bytes,
        "started_at": environment.started_at,
        "duration_seconds": environment.duration_seconds,
    }


def _display_dict(display: DisplayInfo) -> dict[str, Any]:
    return {
        "index": display.index,
        "name": display.name,
        "width": display.width,
        "height": display.height,
        "is_primary": display.is_primary,
    }


def _capture_dict(capture: CaptureSequence) -> dict[str, Any]:
    return {
        "camera_id": capture.camera_id,
        "projector_resolution": list(capture.projector_resolution),
        "camera_resolution": list(capture.camera_resolution),
        "num_patterns": capture.num_patterns,
        "capture_times": list(capture.capture_times),
        "total_capture_seconds": capture.total_capture_seconds,
    }


def _correspondences_dict(correspondences: CorrespondenceMap) -> dict[str, Any]:
    return {
        "image_size": list(correspondences.image_size),
        "num_correspondences": correspondences.num_correspondences,
    }


def _calibration_dict(calibration: ProjectorCalibrationResult) -> dict[str, Any]:
    return {
        "projector_intrinsics": _matrix(calibration.projector_intrinsics),
        "projector_resolution": list(calibration.projector_resolution),
        "projector_pose": _matrix(calibration.projector_pose),
        "reprojection_error": calibration.reprojection_error,
        "num_correspondences": calibration.num_correspondences,
        "coverage": calibration.coverage,
        "confidence": calibration.confidence,
        "camera_matrix": _matrix(calibration.camera_matrix),
        "distortion_coeffs": _vector(calibration.distortion_coeffs),
        "image_size": list(calibration.image_size),
    }


def _percentiles(errors: tuple[float, ...]) -> dict[str, float]:
    """Compact ``p50``/``p90``/``p99`` distribution of per-point errors.

    Returns an empty dictionary when there are no errors, keeping the
    serialized report small instead of inlining thousands of points.
    """
    if not errors:
        return {}
    p50, p90, p99 = np.percentile(errors, [50, 90, 99])
    return {"p50": float(p50), "p90": float(p90), "p99": float(p99)}


def _validation_dict(validation: ValidationReport) -> dict[str, Any]:
    return {
        "rms_error": validation.rms_error,
        "mean_error": validation.mean_error,
        "max_error": validation.max_error,
        "inlier_ratio": validation.inlier_ratio,
        "coverage": validation.coverage,
        "num_sampled": validation.num_sampled,
        "per_point_errors": _percentiles(validation.per_point_errors),
        "passed": validation.passed,
    }


def _metrics_dict(metrics: ValidationMetrics) -> dict[str, Any]:
    return {
        "rms_error": metrics.rms_error,
        "mean_error": metrics.mean_error,
        "max_error": metrics.max_error,
        "inlier_ratio": metrics.inlier_ratio,
        "coverage": metrics.coverage,
        "corner_error": metrics.corner_error,
        "confidence": metrics.confidence,
        "num_correspondences": metrics.num_correspondences,
        "missing_correspondences": metrics.missing_correspondences,
        "num_calibration_images": metrics.num_calibration_images,
        "calibration_seconds": metrics.calibration_seconds,
        "per_point_errors": _percentiles(metrics.per_point_errors),
        "passed": metrics.passed,
    }


def _matrix(values: NDArray[np.float64]) -> list[list[float]]:
    return [[float(v) for v in row] for row in np.asarray(values).tolist()]


def _vector(values: NDArray[np.float64]) -> list[float]:
    return [float(v) for v in np.asarray(values).reshape(-1)]


# ---------------------------------------------------------------------------
# Internal: visualizations / image helpers
# ---------------------------------------------------------------------------


def _build_visualizations(
    report: CalibrationReport,
) -> list[tuple[str, Image.Image]]:
    """Build the visualization images available from the report."""
    items: list[tuple[str, Image.Image]] = []
    if report.correspondences is not None:
        items.append(
            (
                "correspondence_map.png",
                _to_pil(render_correspondence_map(report.correspondences)),
            )
        )
        if report.projector_resolution is not None:
            items.append(
                (
                    "coverage_map.png",
                    _to_pil(
                        render_coverage_map(
                            report.correspondences, report.projector_resolution
                        )
                    ),
                )
            )
    if report.capture is not None:
        items.append(
            (
                "captures_contact_sheet.png",
                _to_pil(render_capture_contact_sheet(report.capture.captured_frames)),
            )
        )
    if report.validation is not None and report.validation.per_point_errors:
        items.append(
            (
                "error_histogram.png",
                _to_pil(render_error_histogram(report.validation.per_point_errors)),
            )
        )
    return items


def _to_pil(image: NDArray[np.uint8]) -> Image.Image:
    """Convert a NumPy image to PIL, promoting 2D grayscale to RGB."""
    array = np.asarray(image, dtype=np.uint8)
    if array.ndim == 2:
        array = np.stack((array,) * 3, axis=-1)
    return Image.fromarray(array)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _render_summary_pages(report: CalibrationReport) -> list[Image.Image]:
    """Render the A4 text summary, spilling onto new pages when full.

    Each line is only drawn when it fits in the remaining vertical space;
    once a page is full a fresh page is started and rendering continues,
    so no content is silently discarded.
    """
    page = Image.new("RGB", (_A4_WIDTH, _A4_HEIGHT), "white")
    draw = ImageDraw.Draw(page)
    title_font = _load_font(26)
    body_font = _load_font(15)

    lines: list[tuple[str, int]] = [(report.session_id, 28)]
    lines.append((f"Status: {report.status.value}", 20))
    lines.append((f"Created: {report.created_at}", 15))
    lines.append((f"Camera: {report.camera_id} ({report.camera_model})", 15))
    display = report.projector_display
    display_text = (
        f"{display.name} @ {display.width}x{display.height}" if display else "n/a"
    )
    lines.append((f"Projector display: {display_text}", 15))
    lines.append((f"Projector resolution: {report.projector_resolution or 'n/a'}", 15))
    lines.append((f"Total time: {report.total_seconds:.2f}s", 15))

    env = report.environment
    lines.append(("", 15))
    lines.append(("Environment", 20))
    lines.append(
        (
            f"OpenCV {env.opencv_version} / Python {env.python_version} / "
            f"{env.platform}-{env.machine}",
            15,
        )
    )
    lines.append(
        (
            f"{env.cpu_count} CPUs / {env.memory_bytes / (1024**3):.1f} GiB RAM / "
            f"started {env.started_at}",
            15,
        )
    )

    if report.metrics is not None:
        metrics = report.metrics
        lines.append(("", 15))
        lines.append(("Validation metrics", 20))
        for label, value in (
            ("RMS error (px)", f"{metrics.rms_error:.3f}"),
            ("Mean error (px)", f"{metrics.mean_error:.3f}"),
            ("Max error (px)", f"{metrics.max_error:.3f}"),
            ("Inlier ratio", f"{metrics.inlier_ratio:.1%}"),
            ("Coverage", f"{metrics.coverage:.1%}"),
            (
                "Corner error (px)",
                f"{metrics.corner_error:.3f}"
                if metrics.corner_error is not None
                else "n/a",
            ),
            ("Confidence", f"{metrics.confidence:.3f}"),
            ("Correspondences", str(metrics.num_correspondences)),
            ("Missing correspondences", str(metrics.missing_correspondences)),
            ("Calibration images", str(metrics.num_calibration_images)),
            ("Calibration time (s)", f"{metrics.calibration_seconds:.2f}"),
            ("Passed", "yes" if metrics.passed else "no"),
        ):
            lines.append((f"{label:<28} {value}", 15))

    if report.step_times:
        lines.append(("", 15))
        lines.append(("Step times (s)", 20))
        for name, seconds in report.step_times.items():
            lines.append((f"{name:<28} {seconds:.2f}", 15))

    if report.warnings:
        lines.append(("", 15))
        lines.append(("Warnings", 20))
        lines.extend((f"- {warning}", 15) for warning in report.warnings)
    if report.errors:
        lines.append(("", 15))
        lines.append(("Errors", 20))
        lines.extend((f"- {error}", 15) for error in report.errors)

    pages: list[Image.Image] = []
    page = Image.new("RGB", (_A4_WIDTH, _A4_HEIGHT), "white")
    draw = ImageDraw.Draw(page)
    max_y = _A4_HEIGHT - _MARGIN
    y = _MARGIN
    for text, size in lines:
        font = title_font if size >= 26 else body_font
        for wrapped in _wrap(text, font, _A4_WIDTH - 2 * _MARGIN):
            if y + size + 4 > max_y:
                pages.append(page)
                page = Image.new("RGB", (_A4_WIDTH, _A4_HEIGHT), "white")
                draw = ImageDraw.Draw(page)
                y = _MARGIN
            draw.text((_MARGIN, y), wrapped, font=font, fill="black")
            y += size + 4
    pages.append(page)
    return pages


def _render_image_page(image: Image.Image) -> Image.Image:
    """Render an A4 page containing one visualization image."""
    page = Image.new("RGB", (_A4_WIDTH, _A4_HEIGHT), "white")
    available = (_A4_WIDTH - 2 * _MARGIN, _A4_HEIGHT - 2 * _MARGIN)
    scaled = _fit(image.convert("RGB"), available)
    x = (_A4_WIDTH - scaled.width) // 2
    y = (_A4_HEIGHT - scaled.height) // 2
    page.paste(scaled, (x, y))
    return page


def _fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Scale *image* to fit *box* preserving aspect ratio."""
    scale = min(box[0] / image.width, box[1] / image.height, 1.0)
    if scale >= 1.0:
        return image
    return image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )


def _wrap(text: str, font: _Font, max_width: int) -> list[str]:
    """Wrap *text* to *max_width* pixels using *font*."""
    if not text:
        return [""]
    if font.getlength(text) <= max_width:
        return [text]
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _load_font(size: int) -> _Font:
    """Load a TrueType font, falling back to the bundled default."""
    for candidate in _font_candidates():
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # older Pillow without a size parameter
        return ImageFont.load_default()


def _font_candidates() -> tuple[str, ...]:
    """Platform-specific TrueType font candidates."""
    if sys.platform == "win32":
        return (
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
        )
    return (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )


def _json_bytes(data: dict[str, Any]) -> bytes:
    # ``allow_nan=False``: non-finite floats (NaN/Infinity) are invalid
    # JSON per RFC 8259 — fail the export loudly instead of writing
    # tokens that no parser can read.
    return json.dumps(data, indent=2, allow_nan=False).encode("utf-8")
