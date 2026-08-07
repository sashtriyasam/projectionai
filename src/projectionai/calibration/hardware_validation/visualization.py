"""Visualization helpers for hardware validation runs.

Renders the intermediate artifacts of a validation run as standalone
images using only OpenCV and NumPy (no new dependencies): the decoded
camera-to-projector correspondence map, the projector-space coverage
map, a contact sheet of the captured gray-code frames, and a histogram
of the per-correspondence reprojection errors. All functions are pure
(``NDArray`` in, ``NDArray`` out) so they are testable without any
hardware and feed directly into the report exporter.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.services.projector_calibration import CorrespondenceMap

_CANVAS_WIDTH = 640
_CANVAS_HEIGHT = 400
_DEFAULT_BINS = 50


def render_correspondence_map(
    correspondences: CorrespondenceMap,
) -> NDArray[np.uint8]:
    """Render the camera-to-projector correspondence map as RGB.

    Each valid camera pixel is colored by the projector pixel that
    illuminated it: the red channel encodes normalized projector ``x``
    and the green channel normalized projector ``y`` (the blue channel
    marks validity). Camera pixels with no valid decode stay black.

    Args:
        correspondences: The decoded correspondence map.

    Returns:
        ``(height, width, 3)`` RGB image at the camera's resolution.
    """
    width, height = correspondences.image_size
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    mask = correspondences.mask
    if not np.any(mask):
        return canvas

    red = _normalized(correspondences.projector_x[mask])
    green = _normalized(correspondences.projector_y[mask])
    canvas[mask, 0] = (red * 255.0).astype(np.uint8)
    canvas[mask, 1] = (green * 255.0).astype(np.uint8)
    canvas[mask, 2] = 255
    return canvas


def render_coverage_map(
    correspondences: CorrespondenceMap,
    resolution: tuple[int, int],
) -> NDArray[np.uint8]:
    """Render which projector pixels are backed by a correspondence.

    The output has the projector's resolution: each projector pixel that
    at least one valid camera correspondence decodes to is drawn white
    on a black background.

    Args:
        correspondences: The decoded correspondence map.
        resolution: Projector ``(width, height)``.

    Returns:
        Grayscale ``(height, width)`` image.
    """
    width, height = resolution
    canvas = np.zeros((height, width), dtype=np.uint8)
    xs = correspondences.projector_x[correspondences.mask]
    ys = correspondences.projector_y[correspondences.mask]
    if len(xs) == 0:
        return canvas

    xs_int = np.floor(xs).astype(np.int64)
    ys_int = np.floor(ys).astype(np.int64)
    in_bounds = (xs_int >= 0) & (xs_int < width) & (ys_int >= 0) & (ys_int < height)
    canvas[ys_int[in_bounds], xs_int[in_bounds]] = 255
    return canvas


def render_capture_contact_sheet(
    frames: Sequence[NDArray[np.uint8]],
    columns: int = 8,
) -> NDArray[np.uint8]:
    """Render captured frames as a labeled contact sheet.

    Args:
        frames: Captured grayscale frames in projection order.
        columns: Number of frames per row.

    Returns:
        RGB contact-sheet image.

    Raises:
        ValueError: If *frames* is empty or *columns* is not positive.
    """
    if not frames:
        raise ValueError("frames must not be empty")
    if columns <= 0:
        raise ValueError(f"columns must be positive, got {columns}")

    cell_width = 160
    cell_height = 90
    rows = (len(frames) + columns - 1) // columns
    sheet = np.zeros((rows * cell_height, columns * cell_width, 3), dtype=np.uint8)

    for index, frame in enumerate(frames):
        row, col = divmod(index, columns)
        cell = _fit_cell(frame, cell_width, cell_height)
        sheet[
            row * cell_height : (row + 1) * cell_height,
            col * cell_width : (col + 1) * cell_width,
        ] = cell
        cv2.putText(
            sheet,
            str(index),
            (col * cell_width + 6, row * cell_height + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return sheet


def render_error_histogram(
    per_point_errors: Sequence[float],
    max_error: float | None = None,
    bins: int = _DEFAULT_BINS,
) -> NDArray[np.uint8]:
    """Render a histogram of per-correspondence reprojection errors.

    Args:
        per_point_errors: Per-correspondence errors in projector pixels.
        max_error: Upper bound of the x axis; defaults to the observed
            maximum error.
        bins: Number of histogram bins.

    Returns:
        RGB histogram image with labeled axes.

    Raises:
        ValueError: If *per_point_errors* is empty or *bins* is not
            positive.
    """
    if not per_point_errors:
        raise ValueError("per_point_errors must not be empty")
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins}")

    errors = np.asarray(per_point_errors, dtype=np.float64)
    upper = (
        max_error
        if max_error is not None and max_error > 0.0
        else float(np.max(errors))
    )
    if upper <= 0.0:
        upper = 1.0

    counts, _ = np.histogram(errors, bins=bins, range=(0.0, upper))
    max_count = 1.0 if float(np.max(counts)) == 0.0 else float(np.max(counts))

    canvas = np.full((_CANVAS_HEIGHT, _CANVAS_WIDTH, 3), 255, dtype=np.uint8)
    margin_left = 50
    margin_bottom = 40
    plot_width = _CANVAS_WIDTH - margin_left - 20
    plot_height = _CANVAS_HEIGHT - margin_bottom - 20

    bar_width = plot_width / bins
    for index, count in enumerate(counts):
        bar_height = round(plot_height * float(count) / max_count)
        x0 = margin_left + round(index * bar_width)
        x1 = margin_left + round((index + 1) * bar_width)
        y0 = _CANVAS_HEIGHT - margin_bottom - bar_height
        cv2.rectangle(
            canvas, (x0, y0), (x1, _CANVAS_HEIGHT - margin_bottom), (64, 64, 64), -1
        )

    cv2.putText(
        canvas,
        f"RMS {np.sqrt(np.mean(np.square(errors))):.2f} px   max {float(np.max(errors)):.2f} px",
        (margin_left, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return canvas


def _normalized(values: NDArray[np.float32]) -> NDArray[np.float64]:
    """Normalize values to ``[0, 1]``, clipping outliers to the range."""
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return np.zeros_like(values, dtype=np.float64)
    lower = float(np.min(finite))
    span = float(np.max(finite)) - lower
    if span <= 0.0:
        return np.zeros_like(values, dtype=np.float64)
    return np.clip((values - lower) / span, 0.0, 1.0)


def _fit_cell(frame: NDArray[np.uint8], width: int, height: int) -> NDArray[np.uint8]:
    """Resize a grayscale frame into an RGB cell with letterboxing."""
    gray = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    return np.asarray(rgb, dtype=np.uint8)
