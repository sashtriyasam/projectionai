from __future__ import annotations

import hashlib

import numpy as np
import pytest

from projectionai.domain.calibration_session import CalibrationMethod, PatternAxis
from projectionai.infrastructure.projector_calibration.patterns import (
    GrayCodePatternGenerator,
    gray_encode,
)
from projectionai.services.pattern_engine import (
    PatternEngine,
    canonical_to_legacy,
    get_pattern_engine,
    graycode_to_canonical,
)
from projectionai.services.projector_calibration import PatternAxis as LegacyAxis
from projectionai.services.projector_calibration import ProjectorCalibrationError


def _bit_is_set(value: int, bit: int) -> bool:
    encoded = int(gray_encode(np.uint32(value)))
    return bool((encoded >> bit) & 1)


class TestBitsFor:
    def test_bits_for_values(self) -> None:
        assert PatternEngine.bits_for(2) == 1
        assert PatternEngine.bits_for(3) == 2
        assert PatternEngine.bits_for(256) == 8
        assert PatternEngine.bits_for(720) == 10
        assert PatternEngine.bits_for(1280) == 11
        assert PatternEngine.bits_for(1920) == 11
        assert PatternEngine.bits_for(1080) == 11

    def test_bits_for_non_power_two(self) -> None:
        assert GrayCodePatternGenerator.bits_for(127) == 7
        assert GrayCodePatternGenerator.bits_for(95) == 7
        assert GrayCodePatternGenerator.bits_for(1366) == 11
        assert GrayCodePatternGenerator.bits_for(768) == 10

    def test_bits_for_rejects(self) -> None:
        with pytest.raises(ProjectorCalibrationError):
            PatternEngine.bits_for(1)


class TestGrayEncode:
    def test_known(self) -> None:
        expected = {0: 0, 1: 1, 2: 3, 3: 2, 4: 6, 5: 7, 6: 5, 7: 4}
        for v, c in expected.items():
            assert int(gray_encode(np.uint32(v))) == c

    def test_encode_is_xor_shift(self) -> None:
        for v in range(0, 4096, 13):
            assert int(gray_encode(np.uint32(v))) == (v ^ (v >> 1))


class TestPatternEngineGeneration:
    def test_column_row_ordering(self) -> None:
        eng = PatternEngine()
        seq = eng.generate(1280, 720)
        axes = [p.axis for p in seq.patterns]
        assert (
            axes == [PatternAxis.COLUMN] * seq.bits_x + [PatternAxis.ROW] * seq.bits_y
        )
        for idx, p in enumerate(seq.patterns):
            assert p.pattern_id == idx

    def test_x_axis_vertical_stripes(self) -> None:
        eng = PatternEngine()
        seq = eng.generate(640, 480)
        cols = [p for p in seq.patterns if p.axis == PatternAxis.COLUMN]
        for pat in cols:
            bit = pat.bit_index
            assert pat.image.shape == (480, 640)
            assert np.array_equal(pat.image[0], pat.image[479])
            for x in (0, 1, 63, 64, 319, 639):
                expected = 255 if _bit_is_set(x, bit) else 0
                assert pat.image[0, x] == expected

    def test_y_axis_horizontal_stripes(self) -> None:
        eng = PatternEngine()
        seq = eng.generate(640, 480)
        rows = [p for p in seq.patterns if p.axis == PatternAxis.ROW]
        for pat in rows:
            bit = pat.bit_index
            assert np.array_equal(pat.image[:, 0], pat.image[:, 639])
            for y in (0, 1, 239, 240, 479):
                expected = 255 if _bit_is_set(y, bit) else 0
                assert pat.image[y, 0] == expected

    def test_invert_complement(self) -> None:
        eng = PatternEngine(invert=False)
        inv_eng = PatternEngine(invert=True)
        normal = eng.generate(640, 480)
        inverted = inv_eng.generate(640, 480)
        assert len(normal.patterns) == len(inverted.patterns)
        for n, inv in zip(normal.patterns, inverted.patterns, strict=True):
            assert inv.bit_value == 0
            assert n.bit_value == 1
            assert np.array_equal(inv.image, 255 - n.image)
            assert inv.pattern_id == n.pattern_id
            assert inv.axis == n.axis
            assert inv.bit_index == n.bit_index

    def test_resolution_independence(self) -> None:
        cases = [
            (320, 240),
            (640, 480),
            (1280, 720),
            (1920, 1080),
            (127, 95),
            (1366, 768),
        ]
        for w, h in cases:
            eng = PatternEngine()
            seq = eng.generate(w, h)
            assert seq.width == w and seq.height == h
            assert seq.bits_x == GrayCodePatternGenerator.bits_for(w)
            assert seq.bits_y == GrayCodePatternGenerator.bits_for(h)
            assert len(seq.patterns) == seq.bits_x + seq.bits_y
            for p in seq.patterns:
                assert p.image.shape == (h, w)
                assert p.image.dtype == np.uint8
                assert p.width == w and p.height == h

    def test_determinism(self) -> None:
        eng = PatternEngine()
        a = eng.generate(1280, 720)
        b = eng.generate(1280, 720)
        assert a.sequence_id == b.sequence_id
        for pa, pb in zip(a.patterns, b.patterns, strict=True):
            assert np.array_equal(pa.image, pb.image)
        h = hashlib.sha256(a.patterns[0].image.tobytes()).hexdigest()
        h2 = hashlib.sha256(b.patterns[0].image.tobytes()).hexdigest()
        assert h == h2

    def test_caching(self) -> None:
        PatternEngine.clear_cache()
        eng = PatternEngine()
        a = eng.generate(640, 480)
        assert PatternEngine.cache_size() == 1
        b = eng.generate(640, 480)
        assert a is b
        eng2 = PatternEngine(invert=True)
        c = eng2.generate(640, 480)
        assert PatternEngine.cache_size() == 2
        assert c is not a
        PatternEngine.clear_cache()
        assert PatternEngine.cache_size() == 0

    def test_domain_legacy_adapter(self) -> None:
        eng = PatternEngine()
        domain_seq = eng.generate(640, 480)
        legacy = canonical_to_legacy(domain_seq)
        assert legacy.width == 640 and legacy.height == 480
        assert len(legacy.patterns) == len(domain_seq.patterns)
        for dp, lp in zip(domain_seq.patterns, legacy.patterns, strict=True):
            assert dp.pattern_id == lp.spec.pattern_id
            assert dp.bit_index == lp.spec.bit_index
            assert np.array_equal(dp.image, lp.image)
        restored = graycode_to_canonical(legacy)
        assert restored.width == domain_seq.width
        assert len(restored.patterns) == len(domain_seq.patterns)
        for a, b in zip(domain_seq.patterns, restored.patterns, strict=True):
            assert np.array_equal(a.image, b.image)

    def test_legacy_adapter_preserves_invert(self) -> None:
        eng = PatternEngine(invert=True)
        domain_seq = eng.generate(640, 480)
        legacy = canonical_to_legacy(domain_seq)
        for lp in legacy.patterns:
            assert lp.spec.bit_value == 0

    def test_invalid_resolution(self) -> None:
        eng = PatternEngine()
        with pytest.raises(ProjectorCalibrationError):
            eng.generate(1, 480)
        with pytest.raises(ProjectorCalibrationError):
            eng.generate(640, 0)

    def test_invalid_method(self) -> None:
        eng = PatternEngine()
        with pytest.raises(ValueError, match="Unsupported method"):
            eng.generate(640, 480, method=CalibrationMethod.CHESSBOARD)

    def test_get_pattern_engine_factory(self) -> None:
        eng = get_pattern_engine(invert=True)
        assert eng.invert is True

    def test_generate_legacy_direct(self) -> None:
        eng = PatternEngine()
        legacy = eng.generate_legacy(320, 240)
        assert legacy.width == 320 and legacy.height == 240
        assert legacy.patterns[0].spec.axis == LegacyAxis.COLUMN
