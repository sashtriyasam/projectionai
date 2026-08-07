"""Unit tests for the hardware validation visualization helpers."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.calibration.hardware_validation.visualization import (
    render_capture_contact_sheet,
    render_correspondence_map,
    render_coverage_map,
    render_error_histogram,
)
from projectionai.services.projector_calibration import CorrespondenceMap


def _correspondences(size: tuple[int, int] = (8, 8)) -> CorrespondenceMap:
    width, height = size
    projector_x = np.full((height, width), np.nan, dtype=np.float32)
    projector_y = np.full((height, width), np.nan, dtype=np.float32)
    mask = np.zeros((height, width), dtype=np.bool_)
    for y in range(2, 6):
        for x in range(2, 6):
            projector_x[y, x] = float(x) * 10.0
            projector_y[y, x] = float(y) * 10.0
            mask[y, x] = True
    return CorrespondenceMap(
        projector_x=projector_x,
        projector_y=projector_y,
        mask=mask,
        image_size=(width, height),
    )


class TestRenderCorrespondenceMap:
    def test_returns_rgb_at_camera_resolution(self) -> None:
        image = render_correspondence_map(_correspondences())
        assert image.shape == (8, 8, 3)
        assert image.dtype == np.uint8

    def test_valid_pixels_colored_invalid_black(self) -> None:
        image = render_correspondence_map(_correspondences())
        # Valid pixels carry a blue marker; invalid pixels stay black.
        assert np.all(image[2:6, 2:6, 2] == 255)
        assert np.all(image[0, 0] == 0)
        assert np.all(image[7, 7] == 0)

    def test_empty_mask_returns_black(self) -> None:
        empty = _correspondences()
        empty = CorrespondenceMap(
            projector_x=np.full((8, 8), np.nan, dtype=np.float32),
            projector_y=np.full((8, 8), np.nan, dtype=np.float32),
            mask=np.zeros((8, 8), dtype=np.bool_),
            image_size=(8, 8),
        )
        image = render_correspondence_map(empty)
        assert np.all(image == 0)

    def test_non_square_capture_shape_matches_mask(self) -> None:
        # image_size is (width, height); the canvas must stay (height, width, 3).
        correspondences = _correspondences((16, 8))
        image = render_correspondence_map(correspondences)
        assert image.shape == (8, 16, 3)
        assert np.all(image[2:6, 2:6, 2] == 255)

    def test_non_square_larger_canvas_stays_height_width_rgb(self) -> None:
        # Regression: a strongly non-square image_size must not transpose the
        # canvas. image_size=(64, 48) -> canvas (48, 64, 3), uint8.
        correspondences = _correspondences((64, 48))
        image = render_correspondence_map(correspondences)
        assert image.shape == (48, 64, 3)
        assert image.dtype == np.uint8
        # Valid pixels carry a blue marker; invalid pixels stay black.
        assert np.all(image[2:6, 2:6, 2] == 255)
        assert np.all(image[0, 0] == 0)
        assert np.all(image[47, 63] == 0)


class TestRenderCoverageMap:
    def test_covered_pixels_white(self) -> None:
        image = render_coverage_map(_correspondences(), (64, 48))
        assert image.shape == (48, 64)
        assert image.dtype == np.uint8
        # Correspondences at x*10 / y*10 (x,y in 2..5) land in bounds.
        assert image[20, 20] == 255
        assert np.all(image[0, :] == 0)

    def test_empty_correspondences_all_black(self) -> None:
        empty = CorrespondenceMap(
            projector_x=np.full((8, 8), np.nan, dtype=np.float32),
            projector_y=np.full((8, 8), np.nan, dtype=np.float32),
            mask=np.zeros((8, 8), dtype=np.bool_),
            image_size=(8, 8),
        )
        image = render_coverage_map(empty, (64, 48))
        assert np.all(image == 0)


class TestRenderCaptureContactSheet:
    def test_sheet_shape_from_frames_and_columns(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(3)]
        sheet = render_capture_contact_sheet(frames, columns=2)
        assert sheet.shape == (2 * 90, 2 * 160, 3)
        assert sheet.dtype == np.uint8

    def test_single_column_layout(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8) for _ in range(2)]
        sheet = render_capture_contact_sheet(frames, columns=1)
        assert sheet.shape == (2 * 90, 160, 3)

    def test_empty_frames_raise(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            render_capture_contact_sheet([])

    def test_non_positive_columns_raise(self) -> None:
        frames = [np.zeros((8, 8), dtype=np.uint8)]
        with pytest.raises(ValueError, match="columns"):
            render_capture_contact_sheet(frames, columns=0)
        with pytest.raises(ValueError, match="columns"):
            render_capture_contact_sheet(frames, columns=-1)


class TestRenderErrorHistogram:
    def test_returns_rgb_canvas(self) -> None:
        image = render_error_histogram([0.1, 0.2, 0.5, 0.9])
        assert image.shape == (400, 640, 3)
        assert image.dtype == np.uint8

    def test_max_error_parameter_respected(self) -> None:
        image = render_error_histogram([0.1, 0.2, 0.5, 0.9], max_error=1.0)
        assert image.shape == (400, 640, 3)

    def test_empty_errors_raise(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            render_error_histogram([])

    def test_non_positive_bins_raise(self) -> None:
        with pytest.raises(ValueError, match="bins"):
            render_error_histogram([0.1], bins=0)
        with pytest.raises(ValueError, match="bins"):
            render_error_histogram([0.1], bins=-5)

    def test_single_error_value_does_not_crash(self) -> None:
        image = render_error_histogram([0.5])
        assert image.shape == (400, 640, 3)
