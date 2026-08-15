"""Build the application icon programmatically.

No binary assets live in the repository (workspace rule); this
script draws a simple projector-lens mark with Pillow and writes
``build/icon.ico`` (git-ignored) for PyInstaller and the installer.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

_SIZE = 256


def _draw(size: int) -> Image.Image:
    """Draw the ProjectionAI mark at *size* pixels."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Dark rounded body
    margin = size // 16
    d.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=size // 8,
        fill=(18, 22, 34, 255),
    )

    # Lens: outer ring + inner pupil
    cx, cy = size // 2, size // 2
    r_outer = size // 3
    r_inner = r_outer // 2
    d.ellipse(
        (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
        outline=(88, 166, 255, 255),
        width=max(2, size // 48),
    )
    d.ellipse(
        (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
        fill=(88, 166, 255, 255),
    )

    # Projection beam: three fading bars bottom-right
    bar_w = max(2, size // 40)
    for i, (bx, by, bw, bh) in enumerate(
        (
            (size // 2, size // 2, size // 3, bar_w * 2),
            (size // 2 + size // 8, size // 2 + size // 10, size // 4, bar_w),
            (size // 2 + size // 4, size // 2 + size // 5, size // 6, bar_w),
        )
    ):
        alpha = 255 - i * 60
        d.rectangle((bx, by, bx + bw, by + bh), fill=(88, 166, 255, alpha))
    return img


def main() -> int:
    build_dir = Path(__file__).resolve().parents[1] / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    icon = _draw(_SIZE)
    icon.save(build_dir / "icon.ico", format="ICO")
    print(f"icon written to {build_dir / 'icon.ico'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
