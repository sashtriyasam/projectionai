"""Deterministic replay tests — Phase 6.11."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import pytest

from projectionai.calibration.replay import (
    CalibrationReplay,
    ReplayError,
    export_replay_artifact,
    import_replay_artifact,
)
from tests.unit.calibration._synthetic_scene import (
    SYNTHETIC_CAMERA,
    SYNTHETIC_IMAGE_SIZE,
    synthetic_captures,
    synthetic_sequence,
)


@pytest.fixture
def _artifact(tmp_path: Path):
    seq = synthetic_sequence()
    caps = tuple(cv2.cvtColor(c, cv2.COLOR_RGB2GRAY) for c in synthetic_captures(seq))
    return export_replay_artifact(
        seq,
        caps,
        SYNTHETIC_CAMERA.camera_matrix,
        SYNTHETIC_CAMERA.distortion_coeffs,
        SYNTHETIC_IMAGE_SIZE,
        0.5,
        0.3,
        path=tmp_path / "art",
    )


def test_artifact_round_trip(_artifact: Path) -> None:
    art = import_replay_artifact(_artifact)
    assert art.sequence.width == 1280
    assert len(art.frames) == 21
    assert art.frames[0].shape == (720, 1280)


def test_checksum_validation(_artifact: Path) -> None:
    (_artifact / "frames" / "000.npy").write_bytes(b"corrupt")
    with pytest.raises(ReplayError, match="checksum"):
        import_replay_artifact(_artifact)


def test_replay_equality(_artifact: Path) -> None:
    art = import_replay_artifact(_artifact)
    # Single-plane artifact: replay must reject rather than fabricate a synthetic second plane
    # (fallback removed). Verify the error is the solver's orientation-diversity gate,
    # not the old hardcoded fallback (intrinsics 2000/640/360, RMS 0.5).
    with pytest.raises(ReplayError) as exc:
        CalibrationReplay().replay(art)
    assert (
        "orientation diversity" in str(exc.value).lower()
        or "at least 2" in str(exc.value).lower()
    )
    assert "0.5" not in str(exc.value)  # not the old fallback RMS


def test_corruption_truncated(_artifact: Path) -> None:
    (_artifact / "manifest.json").write_text('{"truncated":')
    with pytest.raises(ReplayError):
        import_replay_artifact(_artifact)


def test_corruption_missing_frame(_artifact: Path) -> None:
    (_artifact / "frames" / "001.npy").unlink()
    with pytest.raises(ReplayError, match="Missing frame"):
        import_replay_artifact(_artifact)


def test_corruption_reordered(_artifact: Path) -> None:
    m = json.loads((_artifact / "manifest.json").read_text())
    m["frame_checksums"][0], m["frame_checksums"][1] = (
        m["frame_checksums"][1],
        m["frame_checksums"][0],
    )
    m2 = dict(m)
    del m2["manifest_checksum"]
    m["manifest_checksum"] = hashlib.sha256(
        json.dumps(m2, sort_keys=True).encode()
    ).hexdigest()
    (_artifact / "manifest.json").write_text(json.dumps(m, sort_keys=True, indent=2))
    with pytest.raises(ReplayError, match="checksum"):
        import_replay_artifact(_artifact)


def test_multiple_resolutions(tmp_path: Path) -> None:
    for w, h in [(640, 480), (1280, 720), (1920, 1080)]:
        seq = synthetic_sequence(resolution=(w, h))
        caps = tuple(
            cv2.cvtColor(c, cv2.COLOR_RGB2GRAY) for c in synthetic_captures(seq)
        )
        p = export_replay_artifact(
            seq,
            caps,
            SYNTHETIC_CAMERA.camera_matrix,
            SYNTHETIC_CAMERA.distortion_coeffs,
            SYNTHETIC_IMAGE_SIZE,
            0.5,
            0.3,
            path=tmp_path / f"a{w}",
        )
        art = import_replay_artifact(p)
        assert art.image_size == SYNTHETIC_IMAGE_SIZE
        assert art.sequence.width == w
        assert art.sequence.height == h
