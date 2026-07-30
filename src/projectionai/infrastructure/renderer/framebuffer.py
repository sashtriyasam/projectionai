"""FrameBuffer — ModernGL framebuffer wrapper for off-screen rendering.

Supports multiple colour attachments + depth buffer.
Used by render passes for multi-pass rendering (e.g., selection pass
renders to an off-screen buffer that the main pass composites).
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import moderngl

from projectionai.infrastructure.renderer.texture import Texture

_logger = logging.getLogger(__name__)


class FrameBuffer:
    """Off-screen framebuffer with colour and depth attachments.

    Usage::

        fb = FrameBuffer(ctx, width=1920, height=1080)
        fb.bind()
        # ... render scene ...
        fb.unbind()
        fb.color_attachment.bind(0)  # use result as a texture
    """

    def __init__(
        self,
        ctx: Any,
        width: int,
        height: int,
        *,
        color_attachments: int = 1,
        depth: bool = True,
        samples: int = 0,
    ) -> None:
        """Create a framebuffer.

        Args:
            ctx: ModernGL context.
            width: Framebuffer width in pixels.
            height: Framebuffer height in pixels.
            color_attachments: Number of colour render targets (1-4).
            depth: Whether to attach a depth buffer.
            samples: MSAA samples (0 = no MSAA).
        """
        self._ctx = ctx
        self._width = width
        self._height = height
        self._samples = samples
        self._fbo: Any = None
        self._color_textures: list[Texture] = []
        self._depth_texture: Texture | None = None
        self._owns_fbo = True

        color_attachments = max(1, min(color_attachments, 4))

        if samples > 0:
            self._build_msaa(samples, color_attachments, depth)
        else:
            self._build(color_attachments, depth)

    def _build(self, color_attachments: int, depth: bool) -> None:
        """Build a non-MSAA framebuffer."""
        tex_list = []
        for _ in range(color_attachments):
            tex = self._ctx.texture((self._width, self._height), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex_list.append(Texture(self._ctx, tex, self._width, self._height, 4))

        depth_tex = None
        if depth:
            depth_tex = self._ctx.depth_texture((self._width, self._height))

        attachments = [t.native for t in tex_list]
        if depth_tex:
            attachments.append(depth_tex)

        self._fbo = self._ctx.framebuffer(
            color_attachments=attachments[:-1] if depth_tex else attachments,
            depth_attachment=depth_tex,
        )
        self._color_textures = tex_list
        self._depth_texture = depth_tex

    def _build_msaa(self, samples: int, color_attachments: int, depth: bool) -> None:
        """Build an MSAA framebuffer with resolve."""
        # MSAA colour renderbuffers

        color_rt = []
        for _ in range(color_attachments):
            rb = self._ctx.texture((self._width, self._height), 4, samples=samples)
            color_rt.append(rb)

        depth_rt = None
        if depth:
            depth_rt = self._ctx.depth_renderbuffer(
                (self._width, self._height), samples=samples
            )

        self._fbo = self._ctx.framebuffer(
            color_attachments=color_rt, depth_attachment=depth_rt
        )

        # Resolve textures (non-MSAA)
        for _ in range(color_attachments):
            tex = self._ctx.texture((self._width, self._height), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._color_textures.append(
                Texture(self._ctx, tex, self._width, self._height, 4)
            )

    @classmethod
    def from_existing(cls, fbo: Any, width: int, height: int) -> FrameBuffer:
        """Wrap an existing ModernGL framebuffer (e.g., the default framebuffer).

        Args:
            fbo: ModernGL framebuffer object.
            width: Width in pixels.
            height: Height in pixels.
        """
        fb = cls.__new__(cls)
        fb._ctx = None
        fb._fbo = fbo
        fb._width = width
        fb._height = height
        fb._samples = 0
        fb._color_textures = []
        fb._depth_texture = None
        fb._owns_fbo = False
        return fb

    # -- Binding -----------------------------------------------------------

    def bind(self) -> None:
        """Bind this framebuffer as the active render target."""
        self._fbo.use()

    def unbind(self) -> None:
        """Unbind (restore the default framebuffer)."""
        self._ctx.screen.use()

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None:
        """Clear colour and depth buffers."""
        self._fbo.clear(r, g, b, a, depth)

    def resolve(self) -> None:
        """Resolve MSAA into readable textures (no-op for non-MSAA)."""
        if self._samples > 0 and self._color_textures:
            for i, tex in enumerate(self._color_textures):
                self._fbo.read(components=4, attachment=i, write=tex.native)

    # -- Properties --------------------------------------------------------

    @property
    def color_attachments(self) -> list[Texture]:
        """List of colour attachment textures."""
        return list(self._color_textures)

    @property
    def color_attachment(self) -> Texture | None:
        """First colour attachment (convenience)."""
        return self._color_textures[0] if self._color_textures else None

    @property
    def depth_attachment(self) -> Any | None:
        """Depth attachment (ModernGL texture or renderbuffer)."""
        return self._depth_texture

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def fbo(self) -> Any:
        """ModernGL framebuffer object."""
        return self._fbo

    # -- Read pixels -------------------------------------------------------

    def read_pixels(self, components: int = 4) -> bytes:
        """Read pixel data from the first colour attachment."""
        return bytes(self._fbo.read(components=components))

    def read_depth(self) -> bytes:
        """Read depth buffer bytes."""
        return bytes(self._fbo.read(components=1, attachment=-1))

    # -- Lifecycle ---------------------------------------------------------

    def release(self) -> None:
        """Release GPU resources."""
        if not self._owns_fbo:
            return
        if self._fbo:
            self._fbo.release()
            self._fbo = None
        for tex in self._color_textures:
            with contextlib.suppress(Exception):
                tex.release()
        self._color_textures.clear()
        if self._depth_texture:
            with contextlib.suppress(Exception):
                self._depth_texture.release()
            self._depth_texture = None

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()
