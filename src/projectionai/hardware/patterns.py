"""Test pattern generation for display validation.

Pure generation only — no calibration, no warping. Each pattern is a
``PatternSpec`` (metadata) plus a generator callback producing a
Qt-free pixel buffer represented as ``bytes`` in BGRA8 format, matching
the byte layout Qt expects for ``QImage.Format_RGB32`` on little-endian
platforms.

Patterns: Checkerboard, Grid, Crosshair, Colour Bars, Alignment Grid,
Pixel Grid, Gamma Ramp, Safe Border.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class PatternKind(StrEnum):
    """Identifiers for the built-in test patterns."""

    CHECKERBOARD = "checkerboard"
    GRID = "grid"
    CROSSHAIR = "crosshair"
    COLOUR_BARS = "colour_bars"
    ALIGNMENT_GRID = "alignment_grid"
    PIXEL_GRID = "pixel_grid"
    GAMMA_RAMP = "gamma_ramp"
    SAFE_BORDER = "safe_border"


@dataclass(frozen=True)
class PatternSpec:
    """Metadata + generator for one test pattern."""

    kind: PatternKind
    name: str
    description: str
    generate: Callable[[int, int], bytes]

    def render(self, width: int, height: int) -> bytes:
        if width <= 0 or height <= 0:
            raise ValueError(
                f"Pattern dimensions must be positive, got {width}x{height}"
            )
        return self.generate(width, height)


def _bgra(r: int, g: int, b: int, a: int = 255) -> tuple[int, int, int, int]:
    """Pack a colour into BGRA byte order."""
    return (b, g, r, a)


def _fill(width: int, height: int, colour: tuple[int, int, int, int]) -> bytes:
    return bytes(colour) * (width * height)


def _checkerboard(width: int, height: int) -> bytes:
    cell = 64
    light = bytes(_bgra(224, 224, 224))
    dark = bytes(_bgra(32, 32, 32))

    def _row(start_light: bool) -> bytes:
        row = bytearray(width * 4)
        for x in range(width):
            on = (x // cell) % 2 == 0 if start_light else (x // cell) % 2 == 1
            row[x * 4 : x * 4 + 4] = light if on else dark
        return bytes(row)

    even_row = _row(True)
    odd_row = _row(False)
    out = bytearray()
    for y in range(height):
        out.extend(even_row if (y // cell) % 2 == 0 else odd_row)
    return bytes(out)


def _grid(width: int, height: int) -> bytes:
    step = 32
    out = bytearray(_fill(width, height, _bgra(16, 16, 16)))
    white = bytes(_bgra(255, 255, 255))
    # Horizontal lines.
    for y in range(0, height, step):
        start = y * width * 4
        for x in range(width):
            out[start + x * 4 : start + x * 4 + 4] = white
    # Vertical lines.
    for x in range(0, width, step):
        for y in range(height):
            idx = (y * width + x) * 4
            out[idx : idx + 4] = white
    return bytes(out)


def _crosshair(width: int, height: int) -> bytes:
    out = bytearray(_fill(width, height, _bgra(0, 0, 0)))
    red = bytes(_bgra(255, 0, 0))
    white = bytes(_bgra(255, 255, 255))
    cx, cy = width // 2, height // 2
    # Axis lines.
    for x in range(width):
        idx = (cy * width + x) * 4
        out[idx : idx + 4] = white
    for y in range(height):
        idx = (y * width + cx) * 4
        out[idx : idx + 4] = white
    # Red centre cross.
    r = min(width, height) // 20
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if (abs(dx) <= 2 or abs(dy) <= 2) and (
                0 <= cx + dx < width and 0 <= cy + dy < height
            ):
                idx = ((cy + dy) * width + (cx + dx)) * 4
                out[idx : idx + 4] = red
    return bytes(out)


def _colour_bars(width: int, height: int) -> bytes:
    bars = [
        _bgra(255, 255, 255),  # white
        _bgra(255, 255, 0),  # yellow
        _bgra(0, 255, 255),  # cyan
        _bgra(0, 255, 0),  # green
        _bgra(255, 0, 255),  # magenta
        _bgra(255, 0, 0),  # red
        _bgra(0, 0, 255),  # blue
        _bgra(16, 16, 16),  # black
    ]
    # Cap bars at the row width so narrow rows cannot overrun the buffer.
    bars = bars[:width]
    bar_w = max(1, width // len(bars))
    out = bytearray()
    for _ in range(height):
        for _i, colour in enumerate(bars):
            out.extend(bytes(colour) * bar_w)
        out.extend(bytes(bars[-1]) * (width - bar_w * len(bars)))
    return bytes(out)


def _alignment_grid(width: int, height: int) -> bytes:
    out = bytearray(_fill(width, height, _bgra(8, 8, 8)))
    white = bytes(_bgra(255, 255, 255))
    accent = bytes(_bgra(0, 255, 0))
    step = max(1, min(width, height) // 8)
    for i, (x, y) in enumerate([(s, s) for s in range(0, min(width, height), step)]):
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if 0 <= x + dx < width and 0 <= y + dy < height:
                    idx = ((y + dy) * width + (x + dx)) * 4
                    out[idx : idx + 4] = accent if i % 2 else white
    for x in range(0, width, step):
        for y in range(height):
            idx = (y * width + x) * 4
            out[idx : idx + 4] = accent
    for y in range(0, height, step):
        for x in range(width):
            idx = (y * width + x) * 4
            out[idx : idx + 4] = accent
    return bytes(out)


def _pixel_grid(width: int, height: int) -> bytes:
    white = bytes(_bgra(255, 255, 255))
    black = bytes(_bgra(0, 0, 0))
    even_row = bytearray()
    odd_row = bytearray()
    for x in range(width):
        even_row.extend(black if x % 2 == 0 else white)
        odd_row.extend(black if x % 2 == 1 else white)
    out = bytearray()
    for y in range(height):
        out.extend(even_row if y % 2 == 0 else odd_row)
    return bytes(out)


def _gamma_ramp(width: int, height: int) -> bytes:
    row = bytearray()
    for x in range(width):
        v = int((x / max(1, width - 1)) * 255)
        row.extend(bytes(_bgra(v, v, v)))
    return bytes(row) * height


def _safe_border(width: int, height: int) -> bytes:
    out = bytearray(_fill(width, height, _bgra(0, 0, 0)))
    white = bytes(_bgra(255, 255, 255))
    border = max(1, min(width, height) // 40)
    for x in range(width):
        for y in list(range(border)) + list(range(height - border, height)):
            idx = (y * width + x) * 4
            out[idx : idx + 4] = white
    for y in range(border, height - border):
        for x in list(range(border)) + list(range(width - border, width)):
            idx = (y * width + x) * 4
            out[idx : idx + 4] = white
    return bytes(out)


PATTERNS: tuple[PatternSpec, ...] = (
    PatternSpec(
        PatternKind.CHECKERBOARD,
        "Checkerboard",
        "Alternating 64px squares — focus and geometry check.",
        _checkerboard,
    ),
    PatternSpec(
        PatternKind.GRID,
        "Grid",
        "32px white-on-dark grid — keystone and alignment.",
        _grid,
    ),
    PatternSpec(
        PatternKind.CROSSHAIR,
        "Crosshair",
        "Centred crosshair with red centre mark.",
        _crosshair,
    ),
    PatternSpec(
        PatternKind.COLOUR_BARS,
        "Colour Bars",
        "SMPTE-style 8-bar colour ramp — colour accuracy.",
        _colour_bars,
    ),
    PatternSpec(
        PatternKind.ALIGNMENT_GRID,
        "Alignment Grid",
        "Dots + lines at 1/8 divisions — edge alignment.",
        _alignment_grid,
    ),
    PatternSpec(
        PatternKind.PIXEL_GRID,
        "Pixel Grid",
        "1:1 checkerboard — native-resolution sharpness.",
        _pixel_grid,
    ),
    PatternSpec(
        PatternKind.GAMMA_RAMP,
        "Gamma Ramp",
        "Horizontal 0-255 luminance sweep — gamma/black level.",
        _gamma_ramp,
    ),
    PatternSpec(
        PatternKind.SAFE_BORDER,
        "Safe Border",
        "White frame at the image edge — overscan detection.",
        _safe_border,
    ),
)


def get_pattern(kind: PatternKind) -> PatternSpec:
    """Return the spec for *kind*; raises KeyError when unknown."""
    for spec in PATTERNS:
        if spec.kind is kind:
            return spec
    raise KeyError(f"Unknown test pattern: {kind!r}")
