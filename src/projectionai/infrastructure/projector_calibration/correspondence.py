"""Correspondence decoding for structured light captures.

Converts a set of captured gray-code frames into a dense
camera-to-projector correspondence map: for every camera pixel, the
projector pixel that illuminated it.

The decoder compares each capture against the pattern's declared
``bit_value``, so inverted pattern sequences decode identically. Pixels
whose decoded coordinates fall outside the projector resolution are
marked invalid.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    PatternAxis,
    PatternSequence,
    ProjectorCalibrationError,
)

_logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 127


def gray_decode(code: NDArray[np.uint32], bits: int) -> NDArray[np.uint32]:
    """Convert gray-coded integers back to binary.

    Binary is the prefix XOR of the gray code::

        binary = gray XOR (gray >> 1) XOR (gray >> 2) XOR ...
    """
    result = code.copy()
    for shift in range(1, bits):
        result ^= code >> np.uint32(shift)
    return result


class CorrespondenceMatcher:
    """Decodes gray-code captures into a dense :class:`CorrespondenceMap`.

    Args:
        threshold: Grayscale level separating pattern black from white
            (default 127).
    """

    def __init__(self, threshold: int = _DEFAULT_THRESHOLD) -> None:
        self._threshold = threshold

    def decode(
        self,
        captures: Sequence[NDArray[np.uint8]],
        sequence: PatternSequence,
    ) -> CorrespondenceMap:
        """Decode captured frames into a dense correspondence map.

        Args:
            captures: One captured frame per pattern, in the sequence's
                projection order. Frames may be grayscale (2D) or RGB
                (3D, converted internally).
            sequence: The pattern sequence that was projected.

        Returns:
            The dense camera-to-projector correspondence map.

        Raises:
            ProjectorCalibrationError: If the capture count or shapes
                do not match the sequence.
        """
        if not captures:
            raise ProjectorCalibrationError("No captures to decode")
        if len(captures) != len(sequence.patterns):
            raise ProjectorCalibrationError(
                f"Got {len(captures)} captures for {len(sequence.patterns)} patterns"
            )

        height, width = captures[0].shape[:2]
        for capture in captures:
            if capture.ndim not in (2, 3):
                raise ProjectorCalibrationError(
                    f"captures must be grayscale (2D) or RGB (3D), got {capture.ndim}D"
                )
            if capture.shape[:2] != (height, width):
                raise ProjectorCalibrationError(
                    f"capture shape {capture.shape} does not match "
                    f"first capture {(height, width)}"
                )

        gray = [self._to_gray(capture) for capture in captures]

        code_x = np.zeros((height, width), dtype=np.uint32)
        code_y = np.zeros((height, width), dtype=np.uint32)

        for index, pattern in enumerate(sequence.patterns):
            capture = gray[index]
            binary = capture >= self._threshold
            bit = binary == (pattern.spec.bit_value == 1)
            bit_index = np.uint32(pattern.spec.bit_index)
            if pattern.spec.axis is PatternAxis.COLUMN:
                code_x |= bit.astype(np.uint32) << bit_index
            else:
                code_y |= bit.astype(np.uint32) << bit_index

        code_x = gray_decode(code_x, sequence.bits_x)
        code_y = gray_decode(code_y, sequence.bits_y)

        mask = (code_x < np.uint32(width)) & (code_y < np.uint32(height))

        projector_x = np.full((height, width), np.nan, dtype=np.float32)
        projector_y = np.full((height, width), np.nan, dtype=np.float32)
        projector_x[mask] = code_x[mask].astype(np.float32)
        projector_y[mask] = code_y[mask].astype(np.float32)

        _logger.debug(
            "Decoded %d/%d pixels (%.1f%%)",
            int(np.count_nonzero(mask)),
            height * width,
            100.0 * float(np.count_nonzero(mask)) / float(height * width),
        )
        return CorrespondenceMap(
            projector_x=projector_x,
            projector_y=projector_y,
            mask=mask,
            image_size=(width, height),
        )

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _to_gray(capture: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Convert an RGB capture to grayscale (2D frames pass through)."""
        if capture.ndim == 2:
            return capture
        return np.asarray(cv2.cvtColor(capture, cv2.COLOR_RGB2GRAY), dtype=np.uint8)
