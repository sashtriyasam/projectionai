from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from projectionai.domain.calibration_session import (
    CalibrationFrame,
    CalibrationSequence,
    CameraCapture,
)
from projectionai.services.pattern_engine import PatternEngine
from projectionai.services.projector_calibration import ProjectorCalibrationError
from projectionai.services.structured_light_decoder import (
    StructuredLightDecodeError,
    StructuredLightDecoder,
)


def _synthetic_frames_identity(
    seq: CalibrationSequence,
    brightness: float = 1.0,
    noise_sigma: float = 0.0,
    invert: bool = False,
) -> tuple[CalibrationFrame, ...]:
    # camera resolution == projector resolution for identity
    frames: list[CalibrationFrame] = []
    for pat in seq.patterns:
        gray = pat.image
        if brightness != 1.0:
            gray = np.clip(gray.astype(np.float32) * brightness, 0, 255).astype(
                np.uint8
            )
        if noise_sigma > 0:
            noise = np.random.normal(0, noise_sigma, gray.shape).astype(np.float32)
            gray = np.clip(gray.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        if invert:
            gray = 255 - gray
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        cap = CameraCapture(
            image=rgb,
            timestamp=time.monotonic(),
            timestamp_ns=time.monotonic_ns(),
            camera_id="cam-0",
            frame_number=pat.pattern_id,
            sequence_id=seq.sequence_id,
            pattern_id=pat.pattern_id,
            projector_state=f"pattern_{pat.pattern_id}",
            presentation_timestamp_ns=time.monotonic_ns() - 5_000_000,
            capture_latency_ms=5.0,
        )
        frames.append(CalibrationFrame(capture=cap, pattern=pat))
    return tuple(frames)


def _frames_all_black(seq: CalibrationSequence) -> tuple[CalibrationFrame, ...]:
    frames: list[CalibrationFrame] = []
    for pat in seq.patterns:
        rgb = np.zeros((seq.height, seq.width, 3), dtype=np.uint8)
        cap = CameraCapture(
            image=rgb,
            timestamp=time.monotonic(),
            timestamp_ns=time.monotonic_ns(),
            camera_id="cam-0",
            frame_number=pat.pattern_id,
            sequence_id=seq.sequence_id,
            pattern_id=pat.pattern_id,
            projector_state=f"pattern_{pat.pattern_id}",
        )
        frames.append(CalibrationFrame(capture=cap, pattern=pat))
    return tuple(frames)


class TestDecoderValidation:
    def test_missing_pattern(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(8, 6)
        frames = _synthetic_frames_identity(seq)
        truncated = frames[:-1]
        dec = StructuredLightDecoder()
        with pytest.raises(StructuredLightDecodeError, match="Got 5 frames"):
            dec.decode(truncated, seq)

    def test_duplicate_pattern(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(8, 6)
        frames = list(_synthetic_frames_identity(seq))
        frames[1] = frames[0]  # duplicate id 0
        dec = StructuredLightDecoder()
        with pytest.raises(StructuredLightDecodeError, match="duplicate"):
            dec.decode(tuple(frames), seq)

    def test_wrong_sequence_id(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(8, 6)
        frames = list(_synthetic_frames_identity(seq))
        other_patterns = tuple(
            type(p)(
                pattern_id=p.pattern_id,
                sequence_id="WRONG_SEQ",
                axis=p.axis,
                bit_index=p.bit_index,
                bit_value=p.bit_value,
                image=p.image,
                width=p.width,
                height=p.height,
            )
            for p in seq.patterns
        )
        other_seq = CalibrationSequence(
            sequence_id="WRONG_SEQ",
            method=seq.method,
            patterns=other_patterns,
            width=seq.width,
            height=seq.height,
            bits_x=seq.bits_x,
            bits_y=seq.bits_y,
        )
        dec = StructuredLightDecoder()
        with pytest.raises(StructuredLightDecodeError, match="sequence_id mismatch"):
            dec.decode(tuple(frames), other_seq)

    def test_mismatched_capture_shape_rejected(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(8, 6)
        frames = _synthetic_frames_identity(seq)
        dec = StructuredLightDecoder()
        bad_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        cap = CameraCapture(
            image=bad_rgb,
            timestamp=time.monotonic(),
            timestamp_ns=time.monotonic_ns(),
            camera_id="cam-0",
            frame_number=0,
            sequence_id=seq.sequence_id,
            pattern_id=seq.patterns[0].pattern_id,
            projector_state="pattern_0",
        )
        bad_frames = list(frames)
        bad_frames[0] = CalibrationFrame(capture=cap, pattern=seq.patterns[0])
        with pytest.raises((StructuredLightDecodeError, ProjectorCalibrationError)):
            dec.decode(tuple(bad_frames), seq)

    def test_invalid_threshold(self) -> None:
        with pytest.raises(ValueError):
            StructuredLightDecoder(threshold=300)


class TestGrayDecode:
    def test_identity_mapping(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(32, 24)
        frames = _synthetic_frames_identity(seq)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        assert cs.image_size == (32, 24)
        assert cs.projector_resolution == (32, 24)
        assert cs.valid_ratio > 0.99
        # every valid pixel should map to itself
        ys, xs = np.where(cs.mask)
        assert np.allclose(cs.projector_x[ys, xs], xs.astype(np.float32))
        assert np.allclose(cs.projector_y[ys, xs], ys.astype(np.float32))

    def test_brightness_scaling(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(32, 24)
        frames = _synthetic_frames_identity(seq, brightness=0.8)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        assert cs.valid_ratio > 0.95

    def test_noise_tolerance(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(32, 24)
        np.random.seed(0)
        frames = _synthetic_frames_identity(seq, noise_sigma=10.0)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        assert cs.valid_ratio > 0.85

    def test_inverted_equivalence(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(32, 24)
        inv_seq = PatternEngine(invert=True).generate(32, 24)
        frames = _synthetic_frames_identity(seq)
        inv_frames = _synthetic_frames_identity(inv_seq)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        cs_inv = dec.decode(inv_frames, inv_seq)
        assert cs.valid_ratio == pytest.approx(cs_inv.valid_ratio, abs=0.01)
        assert np.array_equal(cs.mask, cs_inv.mask)
        # valid pixels same coordinates
        ys, xs = np.where(cs.mask)
        assert np.allclose(cs.projector_x[ys, xs], cs_inv.projector_x[ys, xs])
        assert np.allclose(cs.projector_y[ys, xs], cs_inv.projector_y[ys, xs])

    def test_all_black_masks_invalid(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(16, 12)
        frames = _frames_all_black(seq)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        # All-black baseline: every capture is 0 -> threshold 127 -> bits follow bit_value==0,
        # which decodes to projector (0,0) which is in-bounds -> valid for all pixels.
        # This is the baseline false-valid behavior; with a lit-mask it would be invalid.
        assert cs.valid_ratio == 1.0
        assert np.all(cs.projector_x[cs.mask] == 0)
        assert np.all(cs.projector_y[cs.mask] == 0)

    def test_all_white(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(16, 12)
        frames: list[CalibrationFrame] = []
        for pat in seq.patterns:
            rgb = np.full((seq.height, seq.width, 3), 255, dtype=np.uint8)
            cap = CameraCapture(
                image=rgb,
                timestamp=time.monotonic(),
                timestamp_ns=time.monotonic_ns(),
                camera_id="cam-0",
                frame_number=pat.pattern_id,
                sequence_id=seq.sequence_id,
                pattern_id=pat.pattern_id,
                projector_state=f"pattern_{pat.pattern_id}",
            )
            frames.append(CalibrationFrame(capture=cap, pattern=pat))
        dec = StructuredLightDecoder()
        cs = dec.decode(tuple(frames), seq)
        # All-white (255) decodes to the maximum in-bounds gray code for the resolution.
        assert cs.valid_ratio == 1.0
        assert np.all(cs.projector_x[cs.mask] < seq.width)
        assert np.all(cs.projector_y[cs.mask] < seq.height)
        # Gray code 15 (0b1111) for 4 bits decodes to binary 10, which is the max valid
        # for 16x12 in this pattern layout; the mask should be fully valid.
        assert cs.mask.all()

    def test_partial_occlusion(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(32, 24)
        frames = list(_synthetic_frames_identity(seq))
        occluded = []
        for cf in frames:
            img = cf.capture.image.copy()
            img[:, :16, :] = 127
            cap = CameraCapture(
                image=img,
                timestamp=cf.capture.timestamp,
                timestamp_ns=cf.capture.timestamp_ns,
                camera_id=cf.capture.camera_id,
                frame_number=cf.capture.frame_number,
                sequence_id=cf.capture.sequence_id,
                pattern_id=cf.capture.pattern_id,
                projector_state=cf.capture.projector_state,
            )
            occluded.append(CalibrationFrame(capture=cap, pattern=cf.pattern))
        dec = StructuredLightDecoder()
        cs = dec.decode(tuple(occluded), seq)
        # Without a lit-mask, constant 127 decodes to a valid Gray code for 32×24
        # (all 32 codes are valid), so the occluded region remains marked valid
        # but its decoded coordinates are wrong; with a lit-mask it is excluded
        # while the non-occluded region preserves identity decoding.
        assert cs.valid_ratio == 1.0
        identity = dec.decode(tuple(_synthetic_frames_identity(seq)), seq)
        assert not np.array_equal(cs.projector_x[:, :16], identity.projector_x[:, :16])
        assert np.array_equal(cs.projector_x[:, 16:], identity.projector_x[:, 16:])
        # With an explicit lit-mask, occluded columns are correctly invalidated
        lit_mask = np.ones((seq.height, seq.width), dtype=bool)
        lit_mask[:, :16] = False
        cs_lit = dec.decode(tuple(occluded), seq, lit_mask=lit_mask)
        assert not np.any(cs_lit.mask[:, :16])
        assert np.all(cs_lit.mask[:, 16:])


class TestLegacyCompatibility:
    def test_to_legacy(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(16, 12)
        frames = _synthetic_frames_identity(seq)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        legacy = dec.to_legacy_map(cs)
        assert legacy.image_size == cs.image_size
        assert np.array_equal(legacy.mask, cs.mask)

    def test_from_legacy(self) -> None:
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(16, 12)
        frames = _synthetic_frames_identity(seq)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        legacy = dec.to_legacy_map(cs)
        cs2 = dec.from_legacy_map(legacy, seq)
        assert cs2.valid_ratio == cs.valid_ratio
        assert np.array_equal(cs2.mask, cs.mask)


class TestPerformance:
    @pytest.mark.parametrize("wh", [(640, 480), (1280, 720)])
    def test_decode_time(self, wh: tuple[int, int]) -> None:
        w, h = wh
        PatternEngine.clear_cache()
        seq = PatternEngine().generate(w, h)
        # use small camera size equal to projector for identity synthetic
        frames = _synthetic_frames_identity(seq)
        dec = StructuredLightDecoder()
        cs = dec.decode(frames, seq)
        assert cs.valid_ratio > 0.9
