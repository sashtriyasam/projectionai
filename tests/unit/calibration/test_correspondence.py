"""Tests for gray-code correspondence decoding."""

from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
import pytest

from projectionai.infrastructure.projector_calibration.correspondence import (
    CorrespondenceMatcher,
    gray_decode,
)
from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
    gray_encode,
)
from projectionai.services.projector_calibration import (
    PatternSequence,
    ProjectorCalibrationError,
    StructuredLightPattern,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_PROJECTOR_RESOLUTION,
    synthetic_captures,
    synthetic_sequence,
)

WIDTH, HEIGHT = SYNTHETIC_PROJECTOR_RESOLUTION


class TestGrayDecode:
    def test_known_codes(self) -> None:
        # Gray -> binary is the prefix XOR of the code.
        assert int(gray_decode(np.uint32(0), 8)) == 0
        assert int(gray_decode(np.uint32(1), 8)) == 1
        assert int(gray_decode(np.uint32(3), 8)) == 2
        assert int(gray_decode(np.uint32(2), 8)) == 3
        assert int(gray_decode(np.uint32(7), 8)) == 5

    def test_roundtrips_gray_encode(self) -> None:
        for value in range(0, 2048, 7):
            assert int(gray_decode(gray_encode(np.uint32(value)), 11)) == value


class TestDecode:
    def test_full_synthetic_scene_decodes_dense_map(self) -> None:
        matcher = CorrespondenceMatcher()
        sequence = synthetic_sequence()
        result = matcher.decode(synthetic_captures(), sequence)

        assert result.image_size == (WIDTH, HEIGHT)
        assert result.mask.shape == (HEIGHT, WIDTH)
        assert 0 < result.num_correspondences < HEIGHT * WIDTH
        # The lit quad covers most of the camera view (smoke: ~84%).
        assert result.num_correspondences > 0.8 * HEIGHT * WIDTH

    def test_masked_coordinates_are_in_bounds(self) -> None:
        result = CorrespondenceMatcher().decode(
            synthetic_captures(), synthetic_sequence()
        )
        xs = result.projector_x[result.mask]
        ys = result.projector_y[result.mask]
        assert np.all(xs >= 0) and np.all(xs < WIDTH)
        assert np.all(ys >= 0) and np.all(ys < HEIGHT)
        assert np.all(np.isfinite(xs)) and np.all(np.isfinite(ys))

    def test_unlit_pixels_are_invalid(self) -> None:
        result = CorrespondenceMatcher().decode(
            synthetic_captures(), synthetic_sequence()
        )
        # Pixels outside the lit quad render at mid-gray and decode invalid,
        # so the corner regions carry NaN projector coordinates.
        assert result.num_correspondences < HEIGHT * WIDTH
        invalid = ~result.mask
        assert np.all(np.isnan(result.projector_x[invalid]))
        assert np.all(np.isnan(result.projector_y[invalid]))

    def test_grayscale_captures_decode_identically(self) -> None:
        matcher = CorrespondenceMatcher()
        sequence = synthetic_sequence()
        rgb_captures = synthetic_captures()
        gray_captures = [
            np.asarray(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), np.uint8)
            for frame in rgb_captures
        ]
        from_rgb = matcher.decode(rgb_captures, sequence)
        from_gray = matcher.decode(gray_captures, sequence)
        assert np.array_equal(from_rgb.mask, from_gray.mask)
        np.testing.assert_array_equal(
            from_rgb.projector_x[from_rgb.mask],
            from_gray.projector_x[from_gray.mask],
        )

    def test_inverted_sequence_decodes_identically(self) -> None:
        matcher = CorrespondenceMatcher()
        normal_sequence = synthetic_sequence()
        inverted_sequence = GrayCodePatternGenerator(invert=True).build_sequence(
            WIDTH, HEIGHT
        )
        normal = matcher.decode(synthetic_captures(), normal_sequence)
        inverted = matcher.decode(
            synthetic_captures(inverted_sequence), inverted_sequence
        )
        # Lit pixels must decode to the same projector coordinates under
        # inversion. (The synthetic scene's mid-gray unlit border decodes
        # out-of-range only for the non-inverted orientation, so mask
        # equality is not asserted across the border.)
        assert np.all(inverted.mask[normal.mask])
        np.testing.assert_array_equal(
            normal.projector_x[normal.mask], inverted.projector_x[normal.mask]
        )
        np.testing.assert_array_equal(
            normal.projector_y[normal.mask], inverted.projector_y[normal.mask]
        )

    def test_rejects_empty_captures(self) -> None:
        with pytest.raises(ProjectorCalibrationError, match="No captures"):
            CorrespondenceMatcher().decode([], synthetic_sequence())

    def test_rejects_capture_count_mismatch(self) -> None:
        sequence = synthetic_sequence()
        captures = synthetic_captures()
        with pytest.raises(ProjectorCalibrationError, match="patterns"):
            CorrespondenceMatcher().decode(captures[:-1], sequence)

    def test_rejects_shape_mismatch(self) -> None:
        sequence = synthetic_sequence()
        captures = synthetic_captures()
        captures[1] = np.zeros((64, 64, 3), np.uint8)
        with pytest.raises(ProjectorCalibrationError, match="shape"):
            CorrespondenceMatcher().decode(captures, sequence)

    def test_rejects_non_image_ndim(self) -> None:
        sequence = synthetic_sequence()
        captures = synthetic_captures()
        captures[0] = np.zeros((2, 2, 2, 2), np.uint8)
        with pytest.raises(ProjectorCalibrationError, match="grayscale"):
            CorrespondenceMatcher().decode(captures, sequence)

    def test_minimal_resolution_decodes(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(2, 2)
        captures = synthetic_captures(sequence)
        result = CorrespondenceMatcher().decode(captures, sequence)
        # image_size comes from the capture frames, not the sequence.
        assert result.image_size == SYNTHETIC_PROJECTOR_RESOLUTION
        assert result.num_correspondences > 0
        # Decoded coordinates stay within the 2x2 projector resolution.
        valid = result.mask
        assert np.max(result.projector_x[valid]) < 2.0
        assert np.max(result.projector_y[valid]) < 2.0

    def test_pairs_captures_by_projection_order_not_pattern_id(self) -> None:
        # pattern_id is metadata; only the pattern order is contractual, so
        # decoding must pair captures positionally even when the ids do not
        # match the positions (old code indexed gray by pattern_id and this
        # raised IndexError on offset ids).
        matcher = CorrespondenceMatcher()
        sequence = synthetic_sequence()
        remapped = PatternSequence(
            patterns=tuple(
                StructuredLightPattern(
                    spec=replace(
                        pattern.spec, pattern_id=pattern.spec.pattern_id + 100
                    ),
                    image=pattern.image,
                )
                for pattern in sequence.patterns
            ),
            width=sequence.width,
            height=sequence.height,
            bits_x=sequence.bits_x,
            bits_y=sequence.bits_y,
        )
        result = matcher.decode(synthetic_captures(sequence), remapped)
        assert result.num_correspondences > 0.8 * HEIGHT * WIDTH
