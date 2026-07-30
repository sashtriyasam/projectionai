"""Texture — ModernGL texture creation and management.

Supports loading from numpy arrays, files, and raw bytes.
Handles mipmaps, filtering modes, and wrapping.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

_logger = logging.getLogger(__name__)

TextureFilter = Literal["nearest", "linear", "mipmap"]
TextureWrap = Literal["repeat", "clamp", "mirrored_repeat"]


class Texture:
    """A GPU texture object.

    Usage::

        tex = Texture.from_array(ctx, rgba_array)
        tex.bind(0)
        shader["u_texture"] = 0
    """

    def __init__(
        self, ctx: Any, texture: Any, width: int, height: int, components: int = 4
    ) -> None:
        """Wraps an existing ModernGL texture.

        Args:
            ctx: ModernGL context.
            texture: ModernGL texture object.
            width: Texture width in pixels.
            height: Texture height in pixels.
            components: Number of channels (1-4).
        """
        self._ctx = ctx
        self._texture = texture
        self._width = width
        self._height = height
        self._components = components
        self._bound_unit: int | None = None

    # -- Factory methods ---------------------------------------------------

    @classmethod
    def from_array(
        cls,
        ctx: Any,
        data: NDArray[np.uint8],
        components: int = 4,
        *,
        filter: TextureFilter = "linear",
        wrap: TextureWrap = "repeat",
    ) -> Texture:
        """Create a texture from a numpy array.

        Args:
            ctx: ModernGL context.
            data: (H, W, C) uint8 array. C must match *components*.
            components: 1-4 (R, RG, RGB, RGBA).
            filter: Texture filtering mode.
            wrap: Texture wrapping mode.
        """
        h, w = data.shape[:2]
        tex = ctx.texture((w, h), components, data.tobytes())
        tex.filter = _to_moderngl_filter(filter)
        tex.wrap = _to_moderngl_wrap(wrap)
        tex.build_mipmaps()
        return cls(ctx, tex, w, h, components)

    @classmethod
    def from_file(cls, ctx: Any, path: str | Path) -> Texture:
        """Load a texture from an image file (via Pillow).

        Args:
            ctx: ModernGL context.
            path: Path to the image file.
        """
        from PIL import Image  # pyright: ignore[reportMissingImports]

        img = Image.open(str(path)).convert("RGBA")
        arr = np.array(img, dtype=np.uint8)
        return cls.from_array(ctx, arr, components=4)

    @classmethod
    def from_bytes(
        cls, ctx: Any, data: bytes, width: int, height: int, components: int = 4
    ) -> Texture:
        """Create a texture from raw bytes.

        Args:
            ctx: ModernGL context.
            data: Raw pixel bytes.
            width: Texture width.
            height: Texture height.
            components: Number of channels.
        """
        tex = ctx.texture((width, height), components, data)
        tex.filter = _to_moderngl_filter("linear")
        tex.build_mipmaps()
        return cls(ctx, tex, width, height, components)

    @classmethod
    def white(cls, ctx: Any) -> Texture:
        """Return a 1x1 white texture (useful as a default)."""
        return cls.from_array(
            ctx, np.array([[[255, 255, 255, 255]]], dtype=np.uint8), components=4
        )

    @classmethod
    def checkerboard(cls, ctx: Any, size: int = 16, grid: int = 8) -> Texture:
        """Create a checkerboard pattern texture for debugging."""
        arr = np.ones((size, size, 4), dtype=np.uint8) * 255
        cells = size // grid
        for y in range(size):
            for x in range(size):
                if (x // cells + y // cells) % 2 == 1:
                    arr[y, x, :3] = 64
        return cls.from_array(ctx, arr, components=4)

    # -- Properties --------------------------------------------------------

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def components(self) -> int:
        return self._components

    @property
    def native(self) -> Any:
        """ModernGL texture object."""
        return self._texture

    # -- Binding -----------------------------------------------------------

    def bind(self, unit: int = 0) -> None:
        """Bind to the given texture unit."""
        if self._texture is not None:
            self._texture.use(unit)
            self._bound_unit = unit

    def unbind(self) -> None:
        """Unbind (clear this texture's sampler unit)."""
        if self._texture is not None and self._bound_unit is not None:
            self._ctx.clear_samplers(self._bound_unit, self._bound_unit + 1)
            self._bound_unit = None

    # -- Lifecycle ---------------------------------------------------------

    def release(self) -> None:
        """Release GPU resources."""
        if self._texture:
            self._texture.release()
            self._texture = None

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()


# -- Internal helpers ---------------------------------------------------------

_INTERNAL_MODERNG_FILTERS: dict[str, tuple[int, int]] = {
    "nearest": (0x2600, 0x2600),  # GL_NEAREST
    "linear": (0x2601, 0x2601),  # GL_LINEAR
    "mipmap": (0x2703, 0x2701),  # GL_LINEAR_MIPMAP_LINEAR, GL_LINEAR
}

_INTERNAL_MODERNG_WRAPS: dict[str, int] = {
    "repeat": 0x2901,  # GL_REPEAT
    "clamp": 0x812F,  # GL_CLAMP_TO_EDGE
    "mirrored_repeat": 0x8370,  # GL_MIRRORED_REPEAT
}


def _to_moderngl_filter(filter: str) -> tuple[int, int]:
    return _INTERNAL_MODERNG_FILTERS.get(filter, _INTERNAL_MODERNG_FILTERS["linear"])


def _to_moderngl_wrap(wrap: str) -> int:
    return _INTERNAL_MODERNG_WRAPS.get(wrap, _INTERNAL_MODERNG_WRAPS["repeat"])
