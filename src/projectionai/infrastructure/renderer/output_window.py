"""GLOutputWindow — dedicated borderless fullscreen output window.

Renders projector output (test patterns, solid colours, blackout, frozen
frame) on a dedicated display via ModernGL. This is deliberately NOT the
main application window: it is a separate borderless surface with a blank
cursor that the application moves to and fullscreens on a selected display
(see :class:`hardware.output_manager.OutputManager`).

Rendering is on-demand (``update()``), so static content costs no CPU.
If the GL context cannot be created the window stays black instead of
crashing the application.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, override

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QOpenGLFunctions, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from projectionai.infrastructure.renderer.output_content import (
    OutputContent,
    OutputContentKind,
)
from projectionai.infrastructure.renderer.passes.pattern import PatternPass
from projectionai.infrastructure.renderer.render_target import ScreenTarget
from projectionai.infrastructure.renderer.texture import Texture

if TYPE_CHECKING:
    from projectionai.hardware.patterns import PatternKind

_logger = logging.getLogger(__name__)

_ESC_KEY = Qt.Key.Key_Escape

# OpenGL clear mask (glClear(GL_COLOR_BUFFER_BIT)) — PySide6 does not
# expose the constant, so keep the standard value locally.
_GL_COLOR_BUFFER_BIT = 0x4000


class GLOutputWindow(QOpenGLWidget):
    """Borderless fullscreen surface for the projector output.

    Signals:
        output_escape_requested: ESC was pressed (development exit hook).
    """

    output_escape_requested = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)

        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        # Strong focus so key events (the ESC exit hook) reach the
        # window once it is fullscreen and activated.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._content: OutputContent = OutputContent.black()
        self._gl_ready: bool = False
        self._ctx: Any = None
        self._pass: PatternPass | None = None
        self._target: ScreenTarget | None = None
        self._texture: Texture | None = None
        self._texture_key: tuple[Any, ...] | None = None
        self._black_texture: Texture | None = None

    # -- Properties --------------------------------------------------------

    @property
    def gl_ready(self) -> bool:
        """Whether the GL context and renderer are fully initialized."""
        return self._gl_ready

    # -- Content -----------------------------------------------------------

    @property
    def content(self) -> OutputContent:
        """The content currently configured for display."""
        return self._content

    def set_content(self, content: OutputContent) -> None:
        """Set the content to display; repaints on demand."""
        if content == self._content:
            return
        self._content = content
        self.update()

    def set_pattern(self, pattern: PatternKind) -> None:
        """Display a test pattern / solid colour fullscreen."""
        self.set_content(OutputContent.pattern(pattern))

    def set_blackout(self) -> None:
        """Display pure black (blackout)."""
        self.set_content(OutputContent.black())

    def set_freeze(self) -> None:
        """Hold the last displayed frame (freeze)."""
        self.set_content(OutputContent.freeze())

    # -- Qt / OpenGL lifecycle ---------------------------------------------

    @override
    def initializeGL(self) -> None:
        """Create the ModernGL context and the pattern pass.

        Any failure degrades to a black window rather than crashing the
        application.
        """
        try:
            from projectionai.infrastructure.renderer.context import (
                RenderContext,
            )

            render_ctx = RenderContext.from_widget(self)
            self._ctx = render_ctx.ctx
            width = max(self.width(), 1)
            height = max(self.height(), 1)
            # QOpenGLWidget presents its private FBO, not FBO 0 — bind it
            # so rendered patterns actually reach the display.
            self._target = ScreenTarget(
                self._ctx, width, height, fbo_id=self.defaultFramebufferObject()
            )
            self._pass = PatternPass()
            self._pass.target = self._target
            self._pass.setup(self._ctx, width, height)
            self._gl_ready = True
        except Exception:
            _logger.exception("GL output window init failed; staying black")
            self._gl_ready = False

    @override
    def resizeGL(self, width: int, height: int) -> None:
        if self._target is not None:
            self._target.resize(width, height)

    @override
    def paintGL(self) -> None:
        if not self._gl_ready or self._pass is None or self._ctx is None:
            self._clear_black()  # never show stale/undefined content
            return
        # Qt may have recreated its FBO (resize / screen change) since the
        # last frame — always target the *current* widget FBO.
        if self._target is not None:
            self._target.set_fbo_id(self.defaultFramebufferObject())
        self._ensure_texture()
        self._pass.render(self._ctx, None, None)

    def _clear_black(self) -> None:
        """Fill the framebuffer with opaque black.

        The window paints no system background (WA_NoSystemBackground),
        so while GL is not ready the framebuffer could otherwise display
        stale/undefined content; clear it explicitly instead.
        """
        context = self.context()
        if context is None:
            return
        try:
            gl = QOpenGLFunctions(context)
            gl.glClearColor(0.0, 0.0, 0.0, 1.0)
            gl.glClear(_GL_COLOR_BUFFER_BIT)
        except Exception:
            _logger.exception("GL clear failed; window stays black")

    @override
    def showFullScreen(self) -> None:
        """Fullscreen and activate so keyboard input reaches the window.

        Qt does not guarantee focus lands on this borderless window when
        it fullscreens; without focus the ESC exit hook never fires.
        """
        super().showFullScreen()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == _ESC_KEY:
            self.output_escape_requested.emit()
            return
        super().keyPressEvent(event)

    # -- Internal ----------------------------------------------------------

    def _ensure_texture(self) -> None:
        """(Re)build the texture matching the current content, if needed."""
        assert self._pass is not None
        assert self._ctx is not None
        content = self._content
        if content.kind is OutputContentKind.FREEZE:
            return  # hold the last shown frame (black if none yet)
        if content.kind is OutputContentKind.BLACK:
            if self._texture_key != ("black",):
                if self._black_texture is None:
                    self._black_texture = Texture.from_bytes(
                        self._ctx, b"\x00\x00\x00\x00", 1, 1, 4
                    )
                self._replace_texture(("black",), self._black_texture)
            return
        # PATTERN: lazily generate pixels so the renderer layer never
        # depends on the hardware package at import time.
        from projectionai.hardware.patterns import pattern_to_rgba

        assert content.pattern_kind is not None
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        key = (content.pattern_kind, width, height)
        if key != self._texture_key:
            rgba = pattern_to_rgba(content.pattern_kind, width, height)
            # Image row 0 is the *top* of the pattern, but texture v=0
            # maps to the bottom of the quad; flip rows at upload so the
            # projector shows the pattern upright (not vertically
            # inverted for asymmetric patterns).
            rgba = rgba[::-1].copy()
            self._replace_texture(
                key,
                Texture.from_array(self._ctx, rgba, components=4, filter="nearest"),
            )

    def _replace_texture(self, key: tuple[Any, ...], texture: Texture) -> None:
        """Swap in a new texture; callers only invoke on key change."""
        if self._texture is not None and self._texture is not self._black_texture:
            # The cached black texture is owned by _black_texture and
            # reused across blackouts; releasing it here would leave a
            # stale (freed) texture in the cache.
            self._texture.release()
        self._texture = texture
        self._texture_key = key
        assert self._pass is not None
        self._pass.set_texture(self._texture)
