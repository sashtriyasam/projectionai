"""RenderContext — ModernGL context lifecycle management.

Creates and manages the ModernGL context from a PySide6 QOpenGLWidget
or an off-screen surface. Separates OpenGL boilerplate from engine code.
"""

from __future__ import annotations

import logging
from typing import Any

import moderngl

_logger = logging.getLogger(__name__)


class RenderContextError(RuntimeError):
    """Raised when the render context cannot be created."""


class RenderContext:
    """Wraps a ModernGL context and provides access to common state.

    Usage::

        ctx = RenderContext.from_widget(qopengl_widget)
        # or
        ctx = RenderContext(ctx_object)
    """

    def __init__(self, ctx: Any) -> None:
        """Wrap an existing ModernGL context.

        Args:
            ctx: ModernGL context object.
        """
        self._ctx: Any = ctx
        self._info: dict[str, str] = {}

        # Gather GPU info
        try:
            self._info = {
                "vendor": ctx.info.get("GL_VENDOR", "unknown"),
                "renderer": ctx.info.get("GL_RENDERER", "unknown"),
                "version": ctx.info.get("GL_VERSION", "unknown"),
                "glsl_version": ctx.info.get("GL_SHADING_LANGUAGE_VERSION", "unknown"),
            }
        except Exception:
            self._info = {
                "vendor": "unknown",
                "renderer": "unknown",
                "version": "unknown",
                "glsl_version": "unknown",
            }

        _logger.info(
            "RenderContext: %s - %s - %s",
            self._info["vendor"],
            self._info["renderer"],
            self._info["version"],
        )

    @classmethod
    def from_widget(cls, widget: Any) -> RenderContext:
        """Create a context from a PySide6 QOpenGLWidget.

        Args:
            widget: A ``QOpenGLWidget`` instance (must have a current context).

        Returns:
            A new ``RenderContext``.
        """
        widget.makeCurrent()
        try:
            ctx = moderngl.create_context(require=330)
        except moderngl.Error as exc:
            raise RenderContextError(
                f"Failed to create ModernGL context: {exc}"
            ) from exc
        return cls(ctx)

    @classmethod
    def from_headless(cls, width: int = 1280, height: int = 720) -> RenderContext:
        """Create a headless (offscreen) context for testing.

        Requires ``glfw`` or EGL support.

        Args:
            width: Virtual framebuffer width.
            height: Virtual framebuffer height.
        """
        import glfw

        if not glfw.init():
            raise RenderContextError("Failed to initialize GLFW")

        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

        window = glfw.create_window(width, height, "headless", None, None)
        if not window:
            glfw.terminate()
            raise RenderContextError("Failed to create headless GLFW window")

        glfw.make_context_current(window)
        try:
            ctx = moderngl.create_context(require=330)
        except moderngl.Error as exc:
            glfw.terminate()
            raise RenderContextError(
                f"Failed to create ModernGL context: {exc}"
            ) from exc

        return cls(ctx)

    @classmethod
    def from_standalone(cls) -> RenderContext:
        """Create a standalone context using the default OpenGL loader.

        Only works when a GL context is already current (e.g., inside
        a QOpenGLWidget's ``initializeGL``).
        """
        try:
            ctx = moderngl.create_context(require=330)
        except moderngl.Error as exc:
            raise RenderContextError(
                f"Failed to create ModernGL context: {exc}"
            ) from exc
        return cls(ctx)

    # -- Properties --------------------------------------------------------

    @property
    def ctx(self) -> Any:
        """ModernGL context object."""
        return self._ctx

    @property
    def info(self) -> dict[str, str]:
        """GPU information dict."""
        return dict(self._info)

    @property
    def vendor(self) -> str:
        return self._info.get("vendor", "unknown")

    @property
    def gpu_name(self) -> str:
        return self._info.get("renderer", "unknown")

    @property
    def gl_version(self) -> str:
        return self._info.get("version", "unknown")

    # -- State management --------------------------------------------------

    def enable_depth_test(self) -> None:
        """Enable depth testing."""
        self._ctx.enable(moderngl.DEPTH_TEST)

    def disable_depth_test(self) -> None:
        """Disable depth testing."""
        self._ctx.disable(moderngl.DEPTH_TEST)

    def enable_blending(self) -> None:
        """Enable alpha blending."""
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

    def disable_blending(self) -> None:
        """Disable alpha blending."""
        self._ctx.disable(moderngl.BLEND)

    def enable_cull_face(self) -> None:
        """Enable back-face culling."""
        self._ctx.enable(moderngl.CULL_FACE)

    def disable_cull_face(self) -> None:
        """Disable back-face culling."""
        self._ctx.disable(moderngl.CULL_FACE)

    def set_wireframe(self, enabled: bool) -> None:
        """Toggle wireframe rendering mode."""
        self._ctx.wireframe = enabled

    def set_viewport(self, x: int, y: int, width: int, height: int) -> None:
        """Set the viewport rectangle."""
        self._ctx.viewport = (x, y, width, height)

    def clear(
        self, r: float = 0.0, g: float = 0.0, b: float = 0.0, a: float = 1.0
    ) -> None:
        """Clear the default framebuffer."""
        self._ctx.clear(r, g, b, a)

    def finish(self) -> None:
        """Wait for all pending GPU commands to complete."""
        self._ctx.finish()

    # -- Screen / default framebuffer --------------------------------------

    @property
    def screen(self) -> Any:
        """Default framebuffer (screen)."""
        return self._ctx.screen

    @property
    def framebuffer(self) -> Any:
        """Currently bound framebuffer."""
        return self._ctx.fbo

    # -- Lifecycle ---------------------------------------------------------

    def release(self) -> None:
        """Release the context (no-op, ModernGL handles context cleanup)."""
        self._ctx = None
        _logger.debug("RenderContext released")
