"""Viewport widget — PySide6 QOpenGLWidget with editor interaction layer.

This is the main widget used in the workspace to display and manipulate
3D content. It replaces the basic :class:`Viewport` in the main window
and adds the full editor interaction system.

Architecture
============

::

    ViewportWidget (QOpenGLWidget)
      ├── Renderer (existing infrastructure)
      │     └── RenderPipeline → passes
      └── ViewportController (editor interaction layer)
            ├── CameraController → OrbitCamera
            ├── InputManager → routes events
            ├── SelectionManager
            ├── GizmoManager
            ├── TransformTools
            ├── OverlayRenderer
            │     ├── GridRenderer
            │     └── AxisRenderer
            ├── SnapManager
            └── CoordinateSystem
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, override

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QSurfaceFormat, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from projectionai.editor.events import SelectionChanged
from projectionai.editor.viewport_controller import ViewportController
from projectionai.infrastructure.renderer.camera import (
    MouseButton,
    OrbitCamera,
    PerspectiveCamera,
)
from projectionai.infrastructure.renderer.context import RenderContext
from projectionai.infrastructure.renderer.renderer import Renderer
from projectionai.infrastructure.renderer.settings import RendererSettings

_logger = logging.getLogger(__name__)


class ViewportWidget(QOpenGLWidget):
    """Editor viewport widget with full interaction support.

    Signals:
        initialized: Emitted after the renderer and controller are ready.
        fps_updated: Emitted each frame with the current FPS.
        selection_changed: Emitted when object selection changes.
    """

    initialized = Signal()
    fps_updated = Signal(float)
    selection_changed = Signal(object)

    def __init__(
        self,
        parent: Any = None,
        settings: RendererSettings | None = None,
        scene_manager: Any = None,
        command_manager: Any = None,
        core_event_bus: Any = None,
    ) -> None:
        super().__init__(parent)

        # OpenGL format
        fmt = self.format()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)

        self._settings: RendererSettings = settings or RendererSettings()
        self._renderer: Renderer | None = None
        self._controller: ViewportController | None = None
        self._gl_initialized: bool = False

        # Mouse state (raw Qt-level, before InputManager)
        self._last_mouse_pos: QPoint = QPoint(0, 0)
        self._mouse_buttons: set[MouseButton] = set()

        # Keyboard modifier tracker
        self._modifiers: list[str] = []

        # Timer-based rendering
        self._timer_id: int | None = None

        # Store dependencies for lazy initialization
        self._scene_manager = scene_manager
        self._command_manager = command_manager
        self._core_event_bus = core_event_bus

        # Focus policy for keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- Qt event overrides -------------------------------------------------

    @override
    def initializeGL(self) -> None:
        """Initialize ModernGL context, renderer, and editor controller."""
        ctx = RenderContext.from_standalone()
        self._renderer = Renderer(settings=self._settings)
        self._renderer.set_context(ctx.ctx)

        # Camera
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        cam = PerspectiveCamera(fov_degrees=60.0, aspect_ratio=w / h)
        cam.near = 0.1
        cam.far = 1000.0
        orbit = OrbitCamera(camera=cam)
        orbit.distance = 15.0
        self._renderer.camera = orbit

        # Editor controller
        self._controller = ViewportController(
            orbit_camera=orbit,
            core_event_bus=self._core_event_bus,
            scene_manager=self._scene_manager,
            command_manager=self._command_manager,
        )
        self._controller.setup_default_shortcuts()
        self._controller.set_redraw_callback(self._request_redraw)

        # Wire selection changes to signal
        self._controller._editor_bus.subscribe(
            SelectionChanged,
            self._on_selection_changed,
        )

        self._gl_initialized = True
        self.initialized.emit()
        _logger.info("Editor ViewportWidget initialized (%dx%d)", w, h)

    @override
    def resizeGL(self, w: int, h: int) -> None:
        if self._renderer:
            self._renderer.resize(w, h)

    @override
    def paintGL(self) -> None:
        """Render the current frame."""
        if not self._gl_initialized or self._renderer is None:
            return

        # Update editor animation
        if self._controller is not None:
            self._controller.update(1.0 / 60.0)

        # Render
        self._renderer.begin_frame()
        self._renderer.render(None)  # type: ignore[arg-type]
        self._renderer.end_frame()

        fps = self._renderer.fps
        if fps > 0:
            self.fps_updated.emit(fps)

    # -- Mouse events -------------------------------------------------------

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        self._last_mouse_pos = pos
        btn = self._qt_button(event.button())
        if btn is not None:
            self._mouse_buttons.add(btn)

        if self._controller is not None:
            self._controller.input.on_press(
                x=float(pos.x()),
                y=float(pos.y()),
                button=self._btn_name(btn) if btn is not None else "left",
                modifiers=self._modifiers,
            )

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        btn = self._qt_button(event.button())
        if btn is not None:
            self._mouse_buttons.discard(btn)

        if self._controller is not None:
            self._controller.input.on_release(
                x=float(pos.x()),
                y=float(pos.y()),
                button=self._btn_name(btn) if btn is not None else "left",
                modifiers=self._modifiers,
            )

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        self._last_mouse_pos = pos

        if self._controller is not None:
            self._controller.input.on_move(
                x=float(pos.x()),
                y=float(pos.y()),
                modifiers=self._modifiers,
            )

        self.update()

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if self._controller is not None:
            self._controller.input.on_wheel(
                delta=float(delta),
                modifiers=self._modifiers,
            )
        self.update()

    # -- Keyboard events ----------------------------------------------------

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = self._key_name(event.key())
        mods = self._qt_modifiers(event)

        # Track modifiers
        if key in ("ctrl", "shift", "alt") and key not in self._modifiers:
            self._modifiers.append(key)

        if self._controller is not None:
            self._controller.handle_key(key, mods)
            self.update()

    @override
    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        key = self._key_name(event.key())
        # Untrack modifiers
        if key in self._modifiers:
            self._modifiers.remove(key)

    # -- Rendering lifecycle -------------------------------------------------

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

    @override
    def closeEvent(self, event: Any) -> None:
        self.stop_rendering()
        if self._renderer:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                self._shutdown_task = asyncio.ensure_future(self._renderer.shutdown())
            else:
                try:
                    asyncio.run(self._renderer.shutdown())
                except Exception:
                    _logger.exception("Failed to run renderer shutdown")
        super().closeEvent(event)

    # -- Public API ----------------------------------------------------------

    @property
    def controller(self) -> ViewportController | None:
        """The editor viewport controller (interaction layer)."""
        return self._controller

    @property
    def renderer(self) -> Renderer | None:
        """The underlying Renderer instance."""
        return self._renderer

    def screenshot(self) -> np.ndarray:
        """Capture the current viewport content as an RGBA array."""
        w = self.width() * self.devicePixelRatio()
        h = self.height() * self.devicePixelRatio()
        data = self.grabFramebuffer()
        bits = data.constBits() if hasattr(data, "constBits") else data.bits()
        return np.frombuffer(bits, dtype=np.uint8).reshape(int(h), int(w), 4)

    # -- Internal helpers ---------------------------------------------------

    def _request_redraw(self) -> None:
        """Request a viewport redraw from any thread."""
        self.update()

    def _on_selection_changed(self, event: Any) -> None:
        """Forward selection changes to the Qt signal."""
        self.selection_changed.emit(event)

    def _qt_button(self, btn: Any) -> MouseButton | None:
        mapping = {
            Qt.MouseButton.LeftButton: MouseButton.LEFT,
            Qt.MouseButton.RightButton: MouseButton.RIGHT,
            Qt.MouseButton.MiddleButton: MouseButton.MIDDLE,
        }
        return mapping.get(btn)

    def _btn_name(self, btn: MouseButton | None) -> str:
        if btn is None:
            return "left"
        mapping = {
            MouseButton.LEFT: "left",
            MouseButton.RIGHT: "right",
            MouseButton.MIDDLE: "middle",
        }
        return mapping.get(btn, "left")

    def _key_name(self, qt_key: int) -> str:
        """Convert a Qt key code to a string for InputManager."""
        from PySide6.QtCore import Qt as QtCore

        mapping = {
            QtCore.Key.Key_W: "W",
            QtCore.Key.Key_E: "E",
            QtCore.Key.Key_R: "R",
            QtCore.Key.Key_A: "A",
            QtCore.Key.Key_D: "D",
            QtCore.Key.Key_F: "F",
            QtCore.Key.Key_G: "G",
            QtCore.Key.Key_S: "S",
            QtCore.Key.Key_T: "T",
            QtCore.Key.Key_P: "P",
            QtCore.Key.Key_1: "1",
            QtCore.Key.Key_2: "2",
            QtCore.Key.Key_3: "3",
            QtCore.Key.Key_4: "4",
            QtCore.Key.Key_5: "5",
            QtCore.Key.Key_Delete: "Delete",
            QtCore.Key.Key_Control: "ctrl",
            QtCore.Key.Key_Shift: "shift",
            QtCore.Key.Key_Alt: "alt",
        }
        key = QtCore.Key(qt_key) if isinstance(qt_key, int) else qt_key
        return mapping.get(key, "unknown")

    def _qt_modifiers(self, event: QKeyEvent | QMouseEvent) -> list[str]:
        """Extract modifier key list from a Qt event."""
        mods: list[str] = []
        mod_flag = event.modifiers()
        from PySide6.QtCore import Qt as QtCore

        if mod_flag & QtCore.KeyboardModifier.ControlModifier:
            mods.append("ctrl")
        if mod_flag & QtCore.KeyboardModifier.ShiftModifier:
            mods.append("shift")
        if mod_flag & QtCore.KeyboardModifier.AltModifier:
            mods.append("alt")
        return mods
