"""Tests for the built-in test pattern generators."""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.hardware.patterns import (
    PATTERNS,
    PatternKind,
    PatternSpec,
    get_pattern,
    pattern_to_rgba,
)


def _pixel(buf: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    """Return the BGRA pixel at (x, y)."""
    idx = (y * width + x) * 4
    return (buf[idx], buf[idx + 1], buf[idx + 2], buf[idx + 3])


SOLIDS: dict[PatternKind, tuple[int, int, int, int]] = {
    PatternKind.BLACK: (0, 0, 0, 255),
    PatternKind.WHITE: (255, 255, 255, 255),
    PatternKind.RED: (0, 0, 255, 255),  # BGRA red
    PatternKind.GREEN: (0, 255, 0, 255),
    PatternKind.BLUE: (255, 0, 0, 255),  # BGRA blue
}


def test_all_patterns_registered() -> None:
    kinds = {spec.kind for spec in PATTERNS}
    assert kinds == set(PatternKind)


def test_each_pattern_renders_correct_buffer_size() -> None:
    for spec in PATTERNS:
        buf = spec.render(320, 180)
        assert len(buf) == 320 * 180 * 4


def test_render_rejects_zero_and_negative_dimensions() -> None:
    colour_bars = get_pattern(PatternKind.COLOUR_BARS)
    for width, height in ((0, 100), (100, 0), (-16, 100), (100, -16)):
        with pytest.raises(ValueError, match="positive"):
            colour_bars.render(width, height)


def test_render_guard_applies_to_all_patterns() -> None:
    invalid = ((0, 64), (64, 0), (-16, 64), (64, -1))
    for spec in PATTERNS:
        for width, height in invalid:
            with pytest.raises(ValueError, match="positive"):
                spec.render(width, height)


def test_get_pattern_returns_spec() -> None:
    spec = get_pattern(PatternKind.CROSSHAIR)
    assert isinstance(spec, PatternSpec)
    assert spec.kind is PatternKind.CROSSHAIR
    assert spec.name == "Crosshair"


def test_get_pattern_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_pattern("not-a-pattern")  # type: ignore[arg-type]


def test_checkerboard_alternates() -> None:
    buf = get_pattern(PatternKind.CHECKERBOARD).render(256, 64)
    light = _pixel(buf, 256, 0, 0)
    dark = _pixel(buf, 256, 64, 0)
    assert light != dark
    assert light == (224, 224, 224, 255)  # BGRA light grey
    assert dark == (32, 32, 32, 255)  # BGRA dark grey


def test_grid_has_white_lines_on_dark() -> None:
    buf = get_pattern(PatternKind.GRID).render(128, 128)
    line = _pixel(buf, 128, 0, 0)  # horizontal line at y=0
    bg = _pixel(buf, 128, 16, 16)  # between lines
    assert line == (255, 255, 255, 255)
    assert bg == (16, 16, 16, 255)


def test_crosshair_has_red_centre() -> None:
    buf = get_pattern(PatternKind.CROSSHAIR).render(200, 200)
    centre = _pixel(buf, 200, 100, 100)
    assert centre == (0, 0, 255, 255)  # BGRA red


def test_colour_bars_has_eight_bars() -> None:
    buf = get_pattern(PatternKind.COLOUR_BARS).render(320, 64)
    first = _pixel(buf, 320, 10, 0)
    assert first == (255, 255, 255, 255)  # white bar
    last = _pixel(buf, 320, 310, 0)
    assert last == (16, 16, 16, 255)  # black bar


def test_colour_bars_narrow_width_fits_exactly() -> None:
    buf = get_pattern(PatternKind.COLOUR_BARS).render(5, 2)
    assert len(buf) == 5 * 2 * 4
    assert _pixel(buf, 5, 0, 0) == (255, 255, 255, 255)  # white bar
    assert _pixel(buf, 5, 4, 0) == (255, 0, 255, 255)  # magenta, 5th bar


def test_alignment_grid_has_dots_and_lines() -> None:
    buf = get_pattern(PatternKind.ALIGNMENT_GRID).render(256, 256)
    step = 256 // 8
    dot = _pixel(buf, 256, step, step)
    assert dot in ((255, 255, 255, 255), (0, 255, 0, 255))


def test_pixel_grid_alternates_every_pixel() -> None:
    buf = get_pattern(PatternKind.PIXEL_GRID).render(4, 1)
    assert _pixel(buf, 4, 0, 0) == (0, 0, 0, 255)
    assert _pixel(buf, 4, 1, 0) == (255, 255, 255, 255)
    assert _pixel(buf, 4, 2, 0) == (0, 0, 0, 255)


def test_gamma_ramp_sweeps_black_to_white() -> None:
    buf = get_pattern(PatternKind.GAMMA_RAMP).render(256, 16)
    first = _pixel(buf, 256, 0, 0)
    last = _pixel(buf, 256, 255, 0)
    assert first == (0, 0, 0, 255)
    assert last == (255, 255, 255, 255)


def test_safe_border_marks_edges() -> None:
    buf = get_pattern(PatternKind.SAFE_BORDER).render(320, 180)
    corner = _pixel(buf, 320, 0, 0)
    centre = _pixel(buf, 320, 160, 90)
    assert corner == (255, 255, 255, 255)
    assert centre == (0, 0, 0, 255)


# -- Solid patterns --------------------------------------------------------------


def test_solid_patterns_fill_every_pixel() -> None:
    for kind, expected in SOLIDS.items():
        buf = get_pattern(kind).render(64, 48)
        assert len(buf) == 64 * 48 * 4
        sampled = ((x, y) for x in range(0, 64, 7) for y in range(0, 48, 5))
        assert all(_pixel(buf, 64, x, y) == expected for x, y in sampled)


# -- pattern_to_rgba -------------------------------------------------------------


def test_pattern_to_rgba_shape_and_dtype() -> None:
    rgba = pattern_to_rgba(PatternKind.CHECKERBOARD, 320, 180)
    assert rgba.shape == (180, 320, 4)
    assert rgba.dtype == np.uint8
    assert rgba.flags.writeable


def test_pattern_to_rgba_reorders_bgra_to_rgba() -> None:
    # The crosshair centre is red: BGRA (0, 0, 255, 255) -> RGBA (255, 0, 0, 255).
    rgba = pattern_to_rgba(PatternKind.CROSSHAIR, 200, 200)
    assert tuple(rgba[100, 100]) == (255, 0, 0, 255)


def test_pattern_to_rgba_solid_colours() -> None:
    for kind, bgra in SOLIDS.items():
        rgba = pattern_to_rgba(kind, 8, 8)
        b, g, r, a = bgra
        assert tuple(rgba[4, 4]) == (r, g, b, a)


def test_pattern_to_rgba_unknown_kind_raises() -> None:
    with pytest.raises(KeyError):
        pattern_to_rgba("not-a-pattern", 16, 16)  # type: ignore[arg-type]
