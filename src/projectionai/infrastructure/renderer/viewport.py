"""Viewport — PySide6 QOpenGLWidget for real-time 3D rendering.

Integrates the ModernGL renderer with Qt's widget framework.
Handles context creation, resize, paint, and mouse interaction
(orbit, pan, zoom).
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, override

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent, QSurfaceFormat, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from projectionai.infrastructure.renderer.camera import (
    MouseButton,
    OrbitCamera,
    PerspectiveCamera,
)
from projectionai.infrastructure.renderer.context import RenderContext
from projectionai.infrastructure.renderer.renderer import Renderer
from projectionai.infrastructure.renderer.settings import RendererSettings

_logger = logging.getLogger(__name__)


class Viewport(QOpenGLWidget):
    """PySide6 widget that renders 3D content via ModernGL.

    Signals:
        initialized: Emitted after the renderer is fully initialized.
        fps_updated: Emitted each frame with current FPS.
    """

    initialized = Signal()
    fps_updated = Signal(float)

    def __init__(
        self,
        parent: Any = None,
        settings: RendererSettings | None = None,
    ) -> None:
        super().__init__(parent)

        # Format
        fmt = self.format()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        fmt.setSwapInterval(1)  # VSync on
        self.setFormat(fmt)

        self._settings: RendererSettings = settings or RendererSettings()
        self._renderer: Renderer | None = None
        self._initialized: bool = False

        # Mouse interaction state
        self._last_mouse_pos: QPoint = QPoint(0, 0)
        self._mouse_buttons: set[MouseButton] = set()

        # Timer-based update
        self._timer_id: int | None = None

    # -- Qt event overrides -----------------------------------------------

    @override
    def initializeGL(self) -> None:
        """Initialise ModernGL context and renderer."""
        ctx = RenderContext.from_standalone()
        self._renderer = Renderer(settings=self._settings)
        self._renderer.set_context(ctx.ctx)

        # Set up the camera for the viewport size
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        cam = PerspectiveCamera(
            fov_degrees=60.0,
            aspect_ratio=w / h,
        )
        cam.near = 0.1
        cam.far = 1000.0
        orbit = OrbitCamera(camera=cam)
        orbit.distance = 15.0
        self._renderer.camera = orbit

        self._initialized = True
        self.initialized.emit()
        _logger.info("Viewport initialized (%dx%d)", w, h)

    @override
    def resizeGL(self, w: int, h: int) -> None:
        """Handle widget resize."""
        if self._renderer:
            self._renderer.resize(w, h)

    @override
    def paintGL(self) -> None:
        """Render the current frame."""
        if not self._initialized or self._renderer is None:
            return

        self._renderer.begin_frame()
        self._renderer.render(None)  # type: ignore[arg-type]
        self._renderer.end_frame()

        fps = self._renderer.fps
        if fps > 0:
            self.fps_updated.emit(fps)

    # -- Mouse interaction -------------------------------------------------

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_pos = event.position().toPoint()
        btn = self._qt_button_to_enum(event.button())
        if btn is not None:
            self._mouse_buttons.add(btn)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        btn = self._qt_button_to_enum(event.button())
        if btn is not None:
            self._mouse_buttons.discard(btn)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._renderer or not self._initialized:
            return

        pos = event.position().toPoint()
        dx = pos.x() - self._last_mouse_pos.x()
        dy = pos.y() - self._last_mouse_pos.y()
        self._last_mouse_pos = pos

        camera = self._renderer.camera
        if camera is None:
            return

        # Orbit: left button
        if MouseButton.LEFT in self._mouse_buttons:
            camera.orbit(dx, -dy)

        # Pan: middle button
        if MouseButton.MIDDLE in self._mouse_buttons:
            pan_speed = 0.02 * camera.distance
            camera.pan(-dx * pan_speed, dy * pan_speed)

        # No zoom on mouse move — handled by wheel
        self.update()

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._renderer or not self._initialized:
            return
        camera = self._renderer.camera
        if camera is None:
            return

        delta = event.angleDelta().y()
        zoom_factor = 1.0 - (delta / 1200.0)
        camera.zoom(zoom_factor)
        self.update()

    # -- Helpers -----------------------------------------------------------

    def _qt_button_to_enum(self, btn: Any) -> MouseButton | None:
        mapping: dict[Any, MouseButton] = {
            Qt.MouseButton.LeftButton: MouseButton.LEFT,
            Qt.MouseButton.RightButton: MouseButton.RIGHT,
            Qt.MouseButton.MiddleButton: MouseButton.MIDDLE,
        }
        return mapping.get(btn)

    def _get_painter(self) -> Any:
        """Return a QPainter for the current context (fallback)."""
        from PySide6.QtGui import QPainter

        return QPainter(self)

    # -- Public API --------------------------------------------------------

    @property
    def renderer(self) -> Renderer | None:
        """The underlying Renderer instance."""
        return self._renderer

    @property
    def viewport_settings(self) -> RendererSettings:
        """Mutable settings for the viewport."""
        return self._settings

    def start_rendering(self) -> None:
        """Begin continuous rendering via timer."""
        if self._timer_id is None:
            self._timer_id = self.startTimer(16)  # ~60 FPS

    def stop_rendering(self) -> None:
        """Stop continuous rendering."""
        if self._timer_id is not None:
            self.killTimer(self._timer_id)
            self._timer_id = None

    @override
    def timerEvent(self, event: Any) -> None:
        self.update()

    def screenshot(self) -> np.ndarray:
        """Capture the current viewport content as a numpy array.

        Returns:
            RGBA uint8 array (height x width x 4).
        """
        w = self.width() * self.devicePixelRatio()
        h = self.height() * self.devicePixelRatio()
        data = self.grabFramebuffer()
        bits = data.constBits() if hasattr(data, "constBits") else data.bits()
        arr = np.frombuffer(bits, dtype=np.uint8).reshape(int(h), int(w), 4)
        return arr

    @override
    def closeEvent(self, event: Any) -> None:
        self.stop_rendering()
        if self._renderer:
            import asyncio

            with contextlib.suppress(RuntimeError):
                asyncio.run(self._renderer.shutdown())
        super().closeEvent(event)
