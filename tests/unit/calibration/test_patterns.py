"""Tests for gray-code structured light pattern generation."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.infrastructure.projector_calibration.correspondence import gray_decode
from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
    gray_encode,
)
from projectionai.services.projector_calibration import (
    PatternAxis,
    ProjectorCalibrationError,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_PROJECTOR_RESOLUTION,
)

WIDTH, HEIGHT = SYNTHETIC_PROJECTOR_RESOLUTION


def _bit_is_set(value: int, bit: int) -> bool:
    """Whether bit ``bit`` of the gray-encoded ``value`` is set."""
    encoded = int(gray_encode(np.uint32(value)))
    return bool((encoded >> bit) & 1)


class TestBitsFor:
    def test_rounds_up_to_cover_size(self) -> None:
        assert GrayCodePatternGenerator.bits_for(2) == 1
        assert GrayCodePatternGenerator.bits_for(3) == 2
        assert GrayCodePatternGenerator.bits_for(256) == 8
        assert GrayCodePatternGenerator.bits_for(720) == 10
        assert GrayCodePatternGenerator.bits_for(1280) == 11

    def test_rejects_size_below_two(self) -> None:
        with pytest.raises(ProjectorCalibrationError):
            GrayCodePatternGenerator.bits_for(1)
        with pytest.raises(ProjectorCalibrationError):
            GrayCodePatternGenerator.bits_for(0)


class TestGrayEncode:
    def test_known_gray_codes(self) -> None:
        # Binary -> gray: value XOR (value >> 1).
        expected = {0: 0, 1: 1, 2: 3, 3: 2, 4: 6, 5: 7, 6: 5, 7: 4}
        for value, code in expected.items():
            assert int(gray_encode(np.uint32(value))) == code

    def test_roundtrips_through_gray_decode(self) -> None:
        for value in range(0, 2048, 7):
            code = gray_encode(np.uint32(value))
            assert int(gray_decode(code, 11)) == value


class TestBuildSequence:
    def test_metadata(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        assert sequence.width == WIDTH
        assert sequence.height == HEIGHT
        assert sequence.bits_x == 11
        assert sequence.bits_y == 10
        assert sequence.resolution == (WIDTH, HEIGHT)

    def test_pattern_count_is_bits_x_plus_bits_y(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        assert len(sequence.patterns) == 21

    def test_column_patterns_precede_row_patterns(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        axes = [p.spec.axis for p in sequence.patterns]
        assert axes == [PatternAxis.COLUMN] * 11 + [PatternAxis.ROW] * 10

    def test_specs_carry_sequential_ids_and_bit_indices(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        for index, pattern in enumerate(sequence.patterns):
            assert pattern.spec.pattern_id == index
            assert pattern.spec.bit_value == 1

    def test_all_pattern_images_have_projector_shape(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        for pattern in sequence.patterns:
            assert pattern.image.shape == (HEIGHT, WIDTH)

    def test_column_patterns_are_vertical_stripes(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        columns = [p for p in sequence.patterns if p.spec.axis is PatternAxis.COLUMN]
        assert len(columns) == 11
        for pattern in columns:
            bit = pattern.spec.bit_index
            assert pattern.image.shape == (HEIGHT, WIDTH)
            # Every row is identical — stripes vary only along x.
            assert np.array_equal(pattern.image[0], pattern.image[HEIGHT - 1])
            for x in (0, 1, 63, 64, WIDTH // 2 - 1, WIDTH // 2, WIDTH - 1):
                expected = 255 if _bit_is_set(x, bit) else 0
                assert pattern.image[0, x] == expected

    def test_row_patterns_are_horizontal_stripes(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        rows = [p for p in sequence.patterns if p.spec.axis is PatternAxis.ROW]
        assert len(rows) == 10
        for pattern in rows:
            bit = pattern.spec.bit_index
            # Every column is identical — stripes vary only along y.
            assert np.array_equal(pattern.image[:, 0], pattern.image[:, WIDTH - 1])
            for y in (0, 1, HEIGHT // 2 - 1, HEIGHT // 2, HEIGHT - 1):
                expected = 255 if _bit_is_set(y, bit) else 0
                assert pattern.image[y, 0] == expected

    def test_inverted_sequence_displays_inverse_bits(self) -> None:
        generator = GrayCodePatternGenerator(invert=True)
        assert generator.invert
        normal = GrayCodePatternGenerator().build_sequence(WIDTH, HEIGHT)
        inverted = generator.build_sequence(WIDTH, HEIGHT)
        assert len(inverted.patterns) == len(normal.patterns)
        for normal_pattern, inverted_pattern in zip(
            normal.patterns, inverted.patterns, strict=True
        ):
            assert inverted_pattern.spec.bit_value == 0
            assert inverted_pattern.spec.pattern_id == normal_pattern.spec.pattern_id
            # Complement of the normal pattern (white where normal is black).
            assert np.array_equal(inverted_pattern.image, 255 - normal_pattern.image)

    def test_minimal_resolution_produces_two_patterns(self) -> None:
        sequence = GrayCodePatternGenerator().build_sequence(2, 2)
        assert len(sequence.patterns) == 2
        assert sequence.bits_x == 1
        assert sequence.bits_y == 1

    def test_rejects_resolution_below_two(self) -> None:
        with pytest.raises(ProjectorCalibrationError):
            GrayCodePatternGenerator().build_sequence(1, 720)
        with pytest.raises(ProjectorCalibrationError):
            GrayCodePatternGenerator().build_sequence(1280, 0)
