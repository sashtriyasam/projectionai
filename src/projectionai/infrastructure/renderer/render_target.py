"""RenderTarget — abstraction over framebuffers and the default screen.

Enables render passes to target either an off-screen framebuffer or the
screen without changing their rendering logic.
"""

from __future__ import annotations

from typing import Any, Protocol

from projectionai.infrastructure.renderer.framebuffer import FrameBuffer


class RenderTarget(Protocol):
    """Protocol for any object that can be used as a render target.

    Both ``FrameBuffer`` and ``ScreenTarget`` implement this protocol.
    """

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def bind(self) -> None: ...

    def unbind(self) -> None: ...

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None: ...


class ScreenTarget:
    """Represents the default framebuffer (screen).

    Wraps the ModernGL screen framebuffer so it can be used wherever
    a ``RenderTarget`` is expected.
    """

    def __init__(self, ctx: Any, width: int, height: int) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._fbo = FrameBuffer.from_existing(ctx.screen, width, height)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def bind(self) -> None:
        self._ctx.screen.use()

    def unbind(self) -> None:
        pass  # screen is always "bound"

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None:
        self._ctx.screen.clear(r, g, b, a, depth)

    @property
    def fbo(self) -> FrameBuffer:
        return self._fbo

    def resize(self, width: int, height: int) -> None:
        """Update screen dimensions."""
        self._width = width
        self._height = height
        self._fbo = FrameBuffer.from_existing(self._ctx.screen, width, height)
