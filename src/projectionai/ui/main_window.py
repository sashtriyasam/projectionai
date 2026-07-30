"""Main application window — updated with editor viewport integration."""

from __future__ import annotations

import logging
from typing import Any, override

import numpy as np
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QWidget

from projectionai.domain.project import Project
from projectionai.editor.viewport_widget import ViewportWidget

_logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level application window.

    Owns the menu bar, toolbars, dock widgets, and the editor viewport
    as its central widget.
    """

    def __init__(self, app: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app: Any = app
        self._project: Project | None = None
        self._viewport: ViewportWidget | None = None
        self._pending_undo_task = None
        self._pending_redo_task = None

        self._setup_ui()
        self._create_menus()

    def _setup_ui(self) -> None:
        self.setWindowTitle("ProjectionAI")
        self.resize(1600, 1000)

        # Central editor viewport
        self._viewport = ViewportWidget(
            parent=self,
            scene_manager=self._app.scenes if hasattr(self._app, "scenes") else None,
            command_manager=self._app.commands
            if hasattr(self._app, "commands")
            else None,
            core_event_bus=self._app.event_bus
            if hasattr(self._app, "event_bus")
            else None,
        )
        self.setCentralWidget(self._viewport)
        self._viewport.start_rendering()

    def _create_menus(self) -> None:
        """Create the application menu bar."""
        menubar = self.menuBar()

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction("Frame All", self._frame_all)
        view_menu.addAction("Focus Selected", self._focus_selected)
        view_menu.addSeparator()

        cam_menu = view_menu.addMenu("Camera")
        cam_menu.addAction("Front", lambda: self._apply_camera("front"))
        cam_menu.addAction("Back", lambda: self._apply_camera("back"))
        cam_menu.addAction("Left", lambda: self._apply_camera("left"))
        cam_menu.addAction("Right", lambda: self._apply_camera("right"))
        cam_menu.addAction("Top", lambda: self._apply_camera("top"))
        cam_menu.addAction("Bottom", lambda: self._apply_camera("bottom"))

        view_menu.addSeparator()
        view_menu.addAction("Toggle Projection", self._toggle_projection)
        view_menu.addAction("Toggle Grid", self._toggle_grid)
        view_menu.addAction("Toggle Axes", self._toggle_axes)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction("Undo", self._undo)
        edit_menu.addAction("Redo", self._redo)
        edit_menu.addSeparator()
        edit_menu.addAction("Delete Selected", self._delete_selected)

        # Transform menu
        xform_menu = menubar.addMenu("&Transform")
        xform_menu.addAction("Translate (W)", lambda: self._set_tool("translate"))
        xform_menu.addAction("Rotate (E)", lambda: self._set_tool("rotate"))
        xform_menu.addAction("Scale (R)", lambda: self._set_tool("scale"))
        xform_menu.addSeparator()
        xform_menu.addAction("Toggle Space", self._toggle_space)
        xform_menu.addAction("Toggle Snap", self._toggle_snap)

    # -- Menu actions -------------------------------------------------------

    def _frame_all(self) -> None:
        if self._viewport and self._viewport.controller:
            ctrl = self._viewport.controller
            scene = getattr(ctrl, "_scene", None)
            active = getattr(scene, "active_scene", None)
            positions = (
                [node.transform.position for node in active.nodes.values()]
                if active
                else []
            )
            if positions:
                arr = np.array(positions, dtype=np.float64)
                center = tuple(arr.mean(axis=0).tolist())
                radius = float(np.max(np.linalg.norm(arr - arr.mean(axis=0), axis=1)))
            else:
                center, radius = (0.0, 0.0, 0.0), 10.0
            ctrl.camera.focus_on_bounds(center, radius)

    def _focus_selected(self) -> None:
        if self._viewport and self._viewport.controller:
            ctrl = self._viewport.controller
            sel = ctrl.selection
            if not sel.is_empty:
                scene = getattr(ctrl, "_scene", None)
                active = getattr(scene, "active_scene", None)
                positions = (
                    [
                        active.nodes[oid].transform.position
                        for oid in sel.selected
                        if oid in active.nodes
                    ]
                    if active
                    else []
                )
                if positions:
                    arr = np.array(positions, dtype=np.float64)
                    center = tuple(arr.mean(axis=0).tolist())
                    radius = float(
                        np.max(np.linalg.norm(arr - arr.mean(axis=0), axis=1))
                    )
                else:
                    center, radius = (0.0, 0.0, 0.0), 10.0
                ctrl.camera.focus_on_bounds(center, radius)

    def _toggle_projection(self) -> None:
        if self._viewport and self._viewport.controller:
            self._viewport.controller.camera.toggle_projection()

    def _toggle_grid(self) -> None:
        if self._viewport and self._viewport.controller:
            ctrl = self._viewport.controller
            ctrl.overlays.grid.enabled = not ctrl.overlays.grid.enabled

    def _toggle_axes(self) -> None:
        if self._viewport and self._viewport.controller:
            ctrl = self._viewport.controller
            ctrl.overlays.axes.enabled = not ctrl.overlays.axes.enabled

    def _undo(self) -> None:
        if hasattr(self._app, "commands") and self._app.commands:
            import asyncio

            self._pending_undo_task = asyncio.ensure_future(self._app.commands.undo())

    def _redo(self) -> None:
        if hasattr(self._app, "commands") and self._app.commands:
            import asyncio

            self._pending_redo_task = asyncio.ensure_future(self._app.commands.redo())

    def _delete_selected(self) -> None:
        if self._viewport and self._viewport.controller:
            self._viewport.controller._delete_selected()

    def _set_tool(self, tool: str) -> None:
        if self._viewport and self._viewport.controller:
            from projectionai.editor.types import TransformMode

            mapping = {
                "translate": TransformMode.TRANSLATE,
                "rotate": TransformMode.ROTATE,
                "scale": TransformMode.SCALE,
            }
            mode = mapping.get(tool, TransformMode.NONE)
            ctrl = self._viewport.controller
            ctrl.transform_mode = (
                TransformMode.NONE if ctrl.transform_mode == mode else mode
            )

    def _toggle_space(self) -> None:
        if self._viewport and self._viewport.controller:
            self._viewport.controller.coordinates.toggle()

    def _toggle_snap(self) -> None:
        if self._viewport and self._viewport.controller:
            self._viewport.controller.snap.toggle()

    def _apply_camera(self, preset: str) -> None:
        if self._viewport and self._viewport.controller:
            from projectionai.editor.types import CameraPreset

            mapping = {
                "front": CameraPreset.FRONT,
                "back": CameraPreset.BACK,
                "left": CameraPreset.LEFT,
                "right": CameraPreset.RIGHT,
                "top": CameraPreset.TOP,
                "bottom": CameraPreset.BOTTOM,
            }
            if preset in mapping:
                self._viewport.controller.camera.apply_preset(mapping[preset])

    # -- Project loading ----------------------------------------------------

    def load_project(self, project: Project) -> None:
        """Load a project into the UI."""
        self._project = project
        self.setWindowTitle(f"ProjectionAI — {project.name}")
        _logger.info("Loaded project: %s", project.name)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._viewport:
            self._viewport.stop_rendering()
        _logger.debug("Main window closing")
        super().closeEvent(event)
