from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.calibration_session import (
    CalibrationFrame,
    CalibrationSequence,
    CorrespondenceSet,
)
from projectionai.infrastructure.projector_calibration.correspondence import (
    CorrespondenceMatcher,
)
from projectionai.services.pattern_engine import canonical_to_legacy
from projectionai.services.projector_calibration import (
    CorrespondenceMap,
    ProjectorCalibrationError,
)


class StructuredLightDecodeError(ProjectorCalibrationError):
    pass


class StructuredLightDecoder:
    def __init__(self, threshold: int = 127) -> None:
        if not 0 <= threshold <= 255:
            raise ValueError(f"threshold must be in [0,255], got {threshold}")
        self._threshold = threshold
        self._matcher = CorrespondenceMatcher(threshold=threshold)

    @property
    def threshold(self) -> int:
        return self._threshold

    def decode(
        self,
        frames: tuple[CalibrationFrame, ...],
        sequence: CalibrationSequence,
        lit_mask: NDArray[np.bool_] | None = None,
    ) -> CorrespondenceSet:
        if not frames:
            raise StructuredLightDecodeError("No frames to decode")
        if len(frames) != len(sequence.patterns):
            raise StructuredLightDecodeError(
                f"Got {len(frames)} frames for {len(sequence.patterns)} patterns"
            )
        # Validate sequence_id and pattern_ids
        for f in frames:
            if f.capture.sequence_id != sequence.sequence_id:
                raise StructuredLightDecodeError(
                    f"sequence_id mismatch: frame {f.capture.sequence_id!r} != sequence {sequence.sequence_id!r}"
                )
            if f.pattern.sequence_id != sequence.sequence_id:
                raise StructuredLightDecodeError("pattern sequence_id mismatch")
        pattern_ids = [f.pattern.pattern_id for f in frames]
        if len(set(pattern_ids)) != len(pattern_ids):
            raise StructuredLightDecodeError(
                f"duplicate pattern_id in frames: {pattern_ids}"
            )
        expected_ids = {p.pattern_id for p in sequence.patterns}
        if set(pattern_ids) != expected_ids:
            raise StructuredLightDecodeError(
                f"pattern_ids {sorted(pattern_ids)} != expected {sorted(expected_ids)}"
            )
        frame_by_id = {f.pattern.pattern_id: f for f in frames}
        ordered = [frame_by_id[p.pattern_id] for p in sequence.patterns]
        # Validate projector resolution
        if sequence.width <= 0 or sequence.height <= 0:
            raise StructuredLightDecodeError(
                f"invalid projector resolution {sequence.width}x{sequence.height}"
            )

        # Prepare captures: convert RGB -> gray exactly once per frame
        captures = [cf.capture.image for cf in ordered]

        legacy_seq = canonical_to_legacy(sequence)
        # Reuse matcher but with our threshold
        matcher = self._matcher
        # Use matcher.decode which will not re-convert if we already gave 2D
        cmap: CorrespondenceMap = matcher.decode(
            captures, legacy_seq, lit_mask=lit_mask
        )

        # Build CorrespondenceSet
        h, w = cmap.image_size[1], cmap.image_size[0]
        valid = int(np.count_nonzero(cmap.mask))
        total = h * w
        valid_ratio = valid / total if total else 0.0

        # Enforce finite on valid
        vx = cmap.projector_x[cmap.mask]
        vy = cmap.projector_y[cmap.mask]
        if vx.size and not np.all(np.isfinite(vx)):
            raise StructuredLightDecodeError("non-finite projector_x in valid mask")
        if vy.size and not np.all(np.isfinite(vy)):
            raise StructuredLightDecodeError("non-finite projector_y in valid mask")

        if vx.size and (np.any(vx < -0.5) or np.any(vx >= sequence.width + 0.5)):
            raise StructuredLightDecodeError(
                "projector_x out of bounds on valid pixels"
            )
        if vy.size and (np.any(vy < -0.5) or np.any(vy >= sequence.height + 0.5)):
            raise StructuredLightDecodeError(
                "projector_y out of bounds on valid pixels"
            )

        return CorrespondenceSet(
            projector_x=cmap.projector_x,
            projector_y=cmap.projector_y,
            mask=cmap.mask,
            image_size=cmap.image_size,
            projector_resolution=(sequence.width, sequence.height),
            sequence_id=sequence.sequence_id,
            threshold=self._threshold,
            valid_ratio=float(valid_ratio),
        )

    def to_legacy_map(self, cs: CorrespondenceSet) -> CorrespondenceMap:
        return CorrespondenceMap(
            projector_x=cs.projector_x,
            projector_y=cs.projector_y,
            mask=cs.mask,
            image_size=cs.image_size,
        )

    def from_legacy_map(
        self,
        cmap: CorrespondenceMap,
        sequence: CalibrationSequence,
        threshold: int | None = None,
    ) -> CorrespondenceSet:
        th = threshold if threshold is not None else self._threshold
        h, w = cmap.image_size[1], cmap.image_size[0]
        valid_ratio = (
            float(np.count_nonzero(cmap.mask)) / float(h * w) if h * w else 0.0
        )
        return CorrespondenceSet(
            projector_x=cmap.projector_x,
            projector_y=cmap.projector_y,
            mask=cmap.mask,
            image_size=cmap.image_size,
            projector_resolution=(sequence.width, sequence.height),
            sequence_id=sequence.sequence_id,
            threshold=th,
            valid_ratio=valid_ratio,
        )
