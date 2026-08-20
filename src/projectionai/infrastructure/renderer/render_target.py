"""RenderTarget — abstraction over framebuffers and the default screen.

Enables render passes to target either an off-screen framebuffer or the
screen without changing their rendering logic.
"""

from __future__ import annotations

from typing import Any, Protocol

from projectionai.infrastructure.renderer.framebuffer import FrameBuffer

# OpenGL constants PySide6 does not expose (kept local, like the clear
# mask in output_window.py).
_GL_FRAMEBUFFER = 0x8D40
_GL_COLOR_BUFFER_BIT = 0x4000
_GL_DEPTH_BUFFER_BIT = 0x100


def _gl() -> Any:
    """Return a QOpenGLFunctions instance bound to the current context."""
    from PySide6.QtGui import QOpenGLFunctions

    gl = QOpenGLFunctions()
    gl.initializeOpenGLFunctions()
    return gl


def _bind_framebuffer(fbo_id: int) -> None:
    """Bind an external framebuffer object (e.g. the QOpenGLWidget FBO)."""
    _gl().glBindFramebuffer(_GL_FRAMEBUFFER, fbo_id)


def _clear_framebuffer(r: float, g: float, b: float, a: float, depth: float) -> None:
    """Clear the currently bound framebuffer."""
    gl = _gl()
    gl.glClearColor(r, g, b, a)
    gl.glClearDepthf(depth)
    gl.glClear(_GL_COLOR_BUFFER_BIT | _GL_DEPTH_BUFFER_BIT)


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

    ``QOpenGLWidget`` renders into a *private* framebuffer object (see
    ``defaultFramebufferObject()``), not into the default framebuffer
    (FBO 0) that ``moderngl.Context.screen`` refers to. Drawing to FBO 0
    inside a widget therefore never reaches the display — the widget
    presents only its own FBO. When created with an ``fbo_id`` (the
    widget's ``defaultFramebufferObject()``), bind/clear target that FBO
    via raw GL calls; otherwise fall back to the ModernGL screen.
    """

    def __init__(self, ctx: Any, width: int, height: int, fbo_id: int = 0) -> None:
        self._ctx = ctx
        self._width = width
        self._height = height
        self._fbo_id = fbo_id
        self._fbo = FrameBuffer.from_existing(ctx.screen, width, height)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def set_fbo_id(self, fbo_id: int) -> None:
        """Update the external FBO to render into (may change on resize)."""
        self._fbo_id = fbo_id

    def bind(self) -> None:
        if self._fbo_id:
            _bind_framebuffer(self._fbo_id)
        else:
            self._ctx.screen.use()

    def unbind(self) -> None:
        pass  # the widget FBO stays bound for Qt; FBO 0 is always "bound"

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None:
        if self._fbo_id:
            _clear_framebuffer(r, g, b, a, depth)
        else:
            self._ctx.screen.clear(r, g, b, a, depth)

    @property
    def fbo(self) -> FrameBuffer:
        return self._fbo

    def resize(self, width: int, height: int) -> None:
        """Update screen dimensions."""
        self._width = width
        self._height = height
        self._fbo = FrameBuffer.from_existing(self._ctx.screen, width, height)
