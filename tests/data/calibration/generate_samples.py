"""Generate sample chessboard calibration views for the test dataset.

Writes perspective checkerboard images (rendered with known ground-truth
intrinsics) into ``tests/data/calibration/samples/``. Run from the
repository root::

    python tests/data/calibration/generate_samples.py

The samples let calibration tooling be exercised on real image files
without a physical camera.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from tests.unit.calibration._synthetic_board import (  # noqa: E402
    VIEW_POSES,
    render_board_view,
)

_OUTPUT_DIR = Path(__file__).resolve().parent / "samples"


def main() -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (rvec, tvec) in enumerate(VIEW_POSES):
        rgb = render_board_view(rvec, tvec)
        path = _OUTPUT_DIR / f"board_{index:03d}.png"
        cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        print(f"wrote {path}")
    print(f"generated {len(VIEW_POSES)} sample views")


if __name__ == "__main__":
    main()
