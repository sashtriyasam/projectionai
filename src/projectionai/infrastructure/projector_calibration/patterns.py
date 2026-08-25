"""Structured light pattern generation for projector calibration.

Implements the gray-code pattern family used by the MVP projector
calibration pipeline. Each bit of the projector column and row
coordinates is encoded as a full-screen stripe pattern; adjacent stripes
always differ in exactly one bit (Hamming distance 1), which makes
decoding robust at stripe boundaries.

Pattern layout per bit ``b`` of coordinate ``c`` (gray-encoded):

- Column patterns (vertical stripes) encode the projector ``x`` axis.
- Row patterns (horizontal stripes) encode the projector ``y`` axis.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

import numpy as np
from numpy.typing import NDArray

from projectionai.services.projector_calibration import (
    PatternAxis,
    PatternSequence,
    PatternSpec,
    ProjectorCalibrationError,
    StructuredLightPattern,
)

_WHITE = 255
_BLACK = 0


def gray_encode(values: NDArray[np.uint32]) -> NDArray[np.uint32]:
    """Gray-code encode integer coordinates (``x XOR (x >> 1)``)."""
    return values ^ (values >> np.uint32(1))


def build_white_sentinel(width: int, height: int) -> NDArray[np.uint8]:
    """All-white frame: lights every pixel that receives projector output.

    Used as an occlusion detector — a camera pixel that stays dark in the
    white sentinel is shadowed/occluded, even when its gray code decodes to
    a valid coordinate.
    """
    return np.full((height, width), 255, dtype=np.uint8)


def build_black_sentinel(width: int, height: int) -> NDArray[np.uint8]:
    """All-black frame; the complement of the white sentinel."""
    return np.zeros((height, width), dtype=np.uint8)


class StructuredLightPatternGenerator(ABC):
    """Strategy interface for structured light pattern families.

    Each family generates the full ordered :class:`PatternSequence` for a
    projector resolution: one pattern per bit of the column coordinate
    (vertical stripes) plus one pattern per bit of the row coordinate
    (horizontal stripes).

    Implementations: gray code (MVP), phase shift, binary code, ...
    """

    @abstractmethod
    def build_sequence(self, width: int, height: int) -> PatternSequence:
        """Build the full pattern sequence for ``width`` x ``height``."""


class GrayCodePatternGenerator(StructuredLightPatternGenerator):
    """Generates binary gray-code stripe patterns.

    For bit ``b`` of an axis, the pattern is a square wave of period
    ``2 ** (b + 1)`` pixels: the displayed value is the ``b``-th bit of
    the *gray-encoded* coordinate.

    Args:
        invert: When ``True``, patterns display the inverse bit value
            (white where the bit is ``0``). The decoder compares captures
            against each pattern's declared ``bit_value``, so inverted
            sequences decode identically — useful in bright environments.
    """

    def __init__(self, invert: bool = False) -> None:
        self._invert = invert

    @property
    def invert(self) -> bool:
        """Whether patterns display inverted bit values."""
        return self._invert

    @staticmethod
    def bits_for(size: int) -> int:
        """Number of bits required to encode coordinates in ``[0, size)``."""
        if size < 2:
            raise ProjectorCalibrationError(f"size must be >= 2, got {size}")
        return math.ceil(math.log2(size))

    def build_sequence(self, width: int, height: int) -> PatternSequence:
        if width < 2 or height < 2:
            raise ProjectorCalibrationError(
                f"resolution must be >= 2 per axis, got {width}x{height}"
            )
        bits_x = self.bits_for(width)
        bits_y = self.bits_for(height)
        bit_value = 0 if self._invert else 1

        patterns: list[StructuredLightPattern] = []
        pattern_id = 0
        for axis, bits, size in (
            (PatternAxis.COLUMN, bits_x, width),
            (PatternAxis.ROW, bits_y, height),
        ):
            for bit_index in range(bits):
                values = self._bit_values(size, bit_index, bit_value)
                if axis is PatternAxis.COLUMN:
                    image = np.repeat(values[None, :], height, axis=0)
                else:
                    image = np.repeat(values[:, None], width, axis=1)
                patterns.append(
                    StructuredLightPattern(
                        spec=PatternSpec(
                            pattern_id=pattern_id,
                            axis=axis,
                            bit_index=bit_index,
                            bit_value=bit_value,
                        ),
                        image=image,
                    )
                )
                pattern_id += 1

        return PatternSequence(
            patterns=tuple(patterns),
            width=width,
            height=height,
            bits_x=bits_x,
            bits_y=bits_y,
        )

    # -- Internal -----------------------------------------------------------

    def _bit_values(
        self, size: int, bit_index: int, bit_value: int
    ) -> NDArray[np.uint8]:
        """Per-coordinate displayed pixel values for one bit pattern."""
        coords = np.arange(size, dtype=np.uint32)
        bits = (gray_encode(coords) >> np.uint32(bit_index)) & np.uint32(1)
        return np.where(bits == np.uint32(bit_value), _WHITE, _BLACK).astype(np.uint8)
