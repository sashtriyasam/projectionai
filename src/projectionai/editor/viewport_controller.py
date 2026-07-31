"""Viewport controller — orchestrates all editor subsystems for the viewport."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.core.events import EventBus
from projectionai.editor.camera_controller import CameraController
from projectionai.editor.coordinate_system import CoordinateSystem
from projectionai.editor.editor_preferences import EditorPreferences
from projectionai.editor.events import (
    EditorEventBus,
    ViewportDirty,
)
from projectionai.editor.events import (
    SelectionChanged as _SelectionChanged,
)
from projectionai.editor.events import (
    SnapToggled as _SnapToggled,
)
from projectionai.editor.events import (
    TransformModeChanged as _TransformModeChanged,
)
from projectionai.editor.gizmo_manager import GizmoManager
from projectionai.editor.input_manager import InputManager, MouseState
from projectionai.editor.overlay_renderer import OverlayRenderer
from projectionai.editor.selection_manager import SelectionManager
from projectionai.editor.snap_manager import SnapManager
from projectionai.editor.transform_tools import TransformTools
from projectionai.editor.types import (
    CameraPreset,
    EditorViewState,
    TransformMode,
)
from projectionai.infrastructure.renderer.camera import OrbitCamera

_logger = logging.getLogger(__name__)


class ViewportController:
    """Central controller for the editor viewport.

    Owns and coordinates all editor subsystems:

    * :class:`CameraController` — camera manipulation and presets.
    * :class:`InputManager` — mouse and keyboard event routing.
    * :class:`SelectionManager` — object selection and history.
    * :class:`GizmoManager` — gizmo lifecycle and hit-testing.
    * :class:`TransformTools` — translate / rotate / scale with undo.
    * :class:`OverlayRenderer` — grid, axes, and overlay drawing.
    * :class:`SnapManager` — snapping configuration.
    * :class:`CoordinateSystem` — world / local space.
    * :class:`EditorPreferences` — persistable editor settings.

    The controller separates *interaction* logic from *rendering*.
    It processes input events, updates state, and provides the data
    the renderer needs to draw the viewport. It never calls OpenGL
    directly.
    """

    def __init__(
        self,
        orbit_camera: OrbitCamera,
        core_event_bus: EventBus | None = None,
        scene_manager: Any | None = None,
        command_manager: Any | None = None,
    ) -> None:
        self._editor_bus = EditorEventBus()
        self._core_bus = core_event_bus
        self._scene = scene_manager
        self._commands = command_manager

        # -- Subsystems (created in dependency order) --
        self._snap = SnapManager(event_bus=self._editor_bus)
        self._coords = CoordinateSystem(event_bus=self._editor_bus)
        self._preferences = EditorPreferences(event_bus=self._editor_bus)
        self._input = InputManager()
        self._camera = CameraController(orbit_camera, event_bus=self._editor_bus)
        self._selection = SelectionManager(event_bus=self._editor_bus)
        self._overlays = OverlayRenderer()
        self._gizmos = GizmoManager(event_bus=self._editor_bus)
        self._transform = TransformTools(
            scene_manager=scene_manager,
            command_manager=command_manager,
            snap_manager=self._snap,
            coordinate_system=self._coords,
            event_bus=self._editor_bus,
            core_event_bus=core_event_bus,
        )

        # Active tool state
        self._transform_mode: TransformMode = TransformMode.NONE
        self._active_tool: str | None = None  # e.g. "select", "translate", etc.

        # Drag offset accumulator (cumulative from drag start)
        self._drag_offset: NDArray[np.float64] = np.zeros(3, dtype=np.float64)

        # Wire input to subsystems
        self._wire_input()

        # Wire editor events to viewport redraw requests
        self._editor_bus.subscribe(_SelectionChanged, self._on_editor_event)
        self._editor_bus.subscribe(_TransformModeChanged, self._on_editor_event)
        self._editor_bus.subscribe(_SnapToggled, self._on_editor_event)

    # -- Properties: subsystem access ---------------------------------------

    @property
    def editor_bus(self) -> EditorEventBus:
        """Editor-local event bus."""
        return self._editor_bus

    @property
    def camera(self) -> CameraController:
        """Camera manipulation controller."""
        return self._camera

    @property
    def input(self) -> InputManager:
        """Input event router."""
        return self._input

    @property
    def selection(self) -> SelectionManager:
        """Object selection manager."""
        return self._selection

    @property
    def gizmos(self) -> GizmoManager:
        """Gizmo lifecycle manager."""
        return self._gizmos

    @property
    def overlays(self) -> OverlayRenderer:
        """Overlay (grid, axes, etc.) renderer."""
        return self._overlays

    # -- Calibration overlay --------------------------------------------------

    def set_calibration_status(self, progress: float, status_text: str) -> None:
        """Update the calibration overlay status and request a redraw.

        Args:
            progress: Calibration progress in the range ``0.0`` — ``1.0``.
            status_text: Human-readable status message.
        """
        self._overlays.calibration.set_status(progress, status_text)
        self._editor_bus.emit(ViewportDirty())

    def set_calibration_detection(
        self,
        corners: NDArray[np.float32] | None,
        image_size: tuple[int, int],
    ) -> None:
        """Display the latest board detection in the calibration overlay.

        Args:
            corners: Detected corner positions ``(N, 2)`` in pixel space,
                or ``None`` to clear the detection.
            image_size: ``(width, height)`` of the source frame.
        """
        self._overlays.calibration.set_detection(corners, image_size)
        self._editor_bus.emit(ViewportDirty())

    def clear_calibration(self) -> None:
        """Clear the calibration overlay and request a redraw."""
        self._overlays.calibration.clear()
        self._editor_bus.emit(ViewportDirty())

    @property
    def snap(self) -> SnapManager:
        """Snapping configuration."""
        return self._snap

    @property
    def coordinates(self) -> CoordinateSystem:
        """World / local coordinate space."""
        return self._coords

    @property
    def preferences(self) -> EditorPreferences:
        """Persistable editor settings."""
        return self._preferences

    @property
    def transform(self) -> TransformTools:
        """Translate / rotate / scale tool."""
        return self._transform

    # -- Properties: tool state ---------------------------------------------

    @property
    def transform_mode(self) -> TransformMode:
        """Active transform mode (none / translate / rotate / scale)."""
        return self._transform_mode

    @transform_mode.setter
    def transform_mode(self, value: TransformMode) -> None:
        self._transform_mode = value
        self._gizmos.mode = value
        self._editor_bus.emit(_TransformModeChanged(mode=value))

    @property
    def active_tool(self) -> str | None:
        """Currently active tool name (``"select"``, ``"translate"``, etc.)."""
        return self._active_tool

    @active_tool.setter
    def active_tool(self, value: str | None) -> None:
        self._active_tool = value

    # -- Per-frame update ---------------------------------------------------

    def update(self, dt: float) -> None:
        """Called once per frame to update animated state.

        Args:
            dt: Delta time in seconds since the last frame.
        """
        self._camera.update(dt)

    def redraw_requested(self) -> bool:
        """Check if any subsystem needs a redraw.

        Returns:
            ``True`` if the viewport should redraw.
        """
        return self._camera.orbit.is_dirty  # simple heuristic

    # -- View state serialisation -------------------------------------------

    def save_view_state(self) -> EditorViewState:
        """Capture the current camera and editor state.

        Returns:
            An ``EditorViewState`` that can be serialised and restored.
        """
        orbit = self._camera.orbit
        return EditorViewState(
            camera_distance=orbit.distance,
            camera_azimuth=orbit.azimuth,
            camera_polar=orbit.polar,
            camera_target_x=float(orbit.target[0]),
            camera_target_y=float(orbit.target[1]),
            camera_target_z=float(orbit.target[2]),
            projection=self._camera.projection,
            transform_space=self._coords.space,
            pivot_mode=self._transform.pivot,
            show_grid=self._overlays.grid.enabled,
            show_axes=self._overlays.axes.enabled,
            show_bounding_boxes=self._overlays.show_bounding_boxes,
            show_selection_outlines=self._overlays.show_selection_outlines,
            show_statistics=self._overlays.show_statistics,
            snap_enabled=self._snap.enabled,
            snap_translation=self._snap.translation,
            snap_rotation=self._snap.rotation,
            snap_scale=self._snap.scale,
        )

    def restore_view_state(self, state: EditorViewState) -> None:
        """Restore camera and editor state from a previous capture.

        Args:
            state: Previously captured view state.
        """
        orbit = self._camera.orbit
        orbit.distance = state.camera_distance
        orbit.azimuth = state.camera_azimuth
        orbit.polar = state.camera_polar
        orbit.target = (
            state.camera_target_x,
            state.camera_target_y,
            state.camera_target_z,
        )
        orbit.mark_dirty()
        self._camera.projection = state.projection
        self._coords.space = state.transform_space
        self._transform.pivot = state.pivot_mode
        self._overlays.apply_view_state(state)
        self._snap.enabled = state.snap_enabled
        self._snap.translation = state.snap_translation
        self._snap.rotation = state.snap_rotation
        self._snap.scale = state.snap_scale

    # -- Keyboard shortcuts -------------------------------------------------

    def setup_default_shortcuts(self) -> None:
        """Register the default keyboard shortcuts on the input manager."""
        inp = self._input
        # Transform modes
        inp.register_shortcut("translate", "W", description="Translate tool")
        inp.register_shortcut("rotate", "E", description="Rotate tool")
        inp.register_shortcut("scale", "R", description="Scale tool")
        # Selection
        inp.register_shortcut("select_all", "A", ("ctrl",), description="Select all")
        inp.register_shortcut(
            "deselect_all", "D", ("ctrl",), description="Deselect all"
        )
        inp.register_shortcut("delete", "Delete", description="Delete selected")
        inp.register_shortcut(
            "duplicate", "D", ("ctrl", "shift"), description="Duplicate"
        )
        # Camera
        inp.register_shortcut("frame_all", "F", description="Frame all objects")
        inp.register_shortcut("focus", "F", ("ctrl",), description="Focus selected")
        inp.register_shortcut(
            "toggle_projection", "P", ("ctrl",), description="Toggle projection"
        )
        inp.register_shortcut("view_front", "1", ("ctrl",), description="Front view")
        inp.register_shortcut("view_top", "3", ("ctrl",), description="Top view")
        inp.register_shortcut("view_left", "5", ("ctrl",), description="Left view")
        # Snapping
        inp.register_shortcut(
            "toggle_snap", "S", ("ctrl",), description="Toggle snapping"
        )
        # Space
        inp.register_shortcut(
            "toggle_space", "T", ("ctrl",), description="Toggle world/local"
        )

    def handle_key(self, key: str, modifiers: list[str]) -> None:
        """Process a key press and route to the appropriate action.

        Args:
            key: Normalised key identifier.
            modifiers: Active modifier keys.
        """
        action = self._input.on_key(key, modifiers)
        if action is None:
            return
        self._handle_action(action)

    def _handle_action(self, action: str) -> None:
        """Handle a resolved shortcut action."""
        mapping = {
            "translate": lambda: self._set_tool_mode(TransformMode.TRANSLATE),
            "rotate": lambda: self._set_tool_mode(TransformMode.ROTATE),
            "scale": lambda: self._set_tool_mode(TransformMode.SCALE),
            "toggle_projection": self._camera.toggle_projection,
            "view_front": lambda: self._camera.apply_preset(CameraPreset.FRONT),
            "view_top": lambda: self._camera.apply_preset(CameraPreset.TOP),
            "view_left": lambda: self._camera.apply_preset(CameraPreset.LEFT),
            "toggle_snap": self._snap.toggle,
            "toggle_space": self._coords.toggle,
            "select_all": lambda: self._select_all(),
            "deselect_all": self._selection.clear,
            "delete": lambda: self._delete_selected(),
            "duplicate": lambda: self._duplicate_selected(),
            "frame_all": lambda: self._frame_all(),
            "focus": lambda: self._focus_selected(),
        }
        handler: Callable[[], None] | None = mapping.get(action)
        if handler is not None:
            handler()

    def _set_tool_mode(self, mode: TransformMode) -> None:
        """Set the active tool, cycling off if already active."""
        if self._transform_mode == mode:
            self.transform_mode = TransformMode.NONE
        else:
            self.transform_mode = mode

    def _select_all(self) -> None:
        """Select all objects in the current scene (stub)."""
        if self._scene is not None:
            ids = (
                self._scene.get_all_node_ids()
                if hasattr(self._scene, "get_all_node_ids")
                else []
            )
            self._selection.select_multiple(ids)

    def _delete_selected(self) -> None:
        """Remove all selected nodes from the active scene."""
        if self._scene is None:
            return
        for oid in list(self._selection.selected):
            try:
                self._scene.remove_node(oid)
            except ValueError:
                pass  # node not found in scene
            else:
                self._selection.deselect(oid)

    def _duplicate_selected(self) -> None:
        """Clone each selected node in the active scene."""
        if self._scene is None:
            return
        scene = getattr(self._scene, "active_scene", None)
        if scene is None:
            return
        for oid in list(self._selection.selected):
            node = scene.get_node(oid)
            if node is not None:
                scene.add_node(
                    name=f"{node.name} (copy)",
                    parent_id=node.parent_id,
                    transform=node.transform,
                )

    def _frame_all(self) -> None:
        """Frame all scene nodes in the viewport."""
        if self._scene is None:
            return
        scene = getattr(self._scene, "active_scene", None)
        if scene is None:
            return
        positions: list[tuple[float, float, float]] = []
        for nid, node in scene.nodes.items():
            if nid == scene.root_node_id:
                continue
            positions.append(node.transform.position)
        self._camera.frame_selected(positions)

    def _focus_selected(self) -> None:
        """Center the camera on the active (primary) selection."""
        if self._scene is None:
            return
        scene = getattr(self._scene, "active_scene", None)
        if scene is None:
            return
        active = self._selection.active
        if active is not None:
            node = scene.get_node(active)
            if node is not None:
                self._camera.focus_on_point(node.transform.position)

    # -- Internal wiring ----------------------------------------------------

    def _wire_input(self) -> None:
        """Connect input handlers to editor subsystems."""
        inp = self._input

        # Mouse move: orbit if no tool active, otherwise gizmo drag
        inp.add_move_handler(self._on_mouse_move)

        # Mouse press: start orbit, select, or drag
        inp.add_press_handler(self._on_mouse_press)

        # Mouse release: end drag
        inp.add_release_handler(self._on_mouse_release)

        # Wheel: always zoom
        inp.add_wheel_handler(self._on_wheel)

    def _on_mouse_press(self, state: MouseState) -> None:
        """Handle mouse press events."""
        if state.left:
            if self._transform_mode != TransformMode.NONE:
                # Start gizmo transform drag
                self._drag_offset[:] = 0.0
                ray_origin = np.zeros(3, dtype=np.float64)
                ray_dir = np.zeros(3, dtype=np.float64)
                self._gizmos.interaction_start(ray_origin, ray_dir)
                self._transform.begin_drag(
                    list(self._selection.selected),
                    ray_origin,
                )
            # Left-click selection is handled by the viewport widget
            # after performing a hit-test (it calls selection_manager.select)
        elif state.middle:
            pass  # Pan is handled in mouse_move

    def _on_mouse_move(self, state: MouseState) -> None:
        """Handle mouse move events — route to camera or gizmo."""
        if not state.any_button:
            return

        if state.middle or (state.right and state.alt):
            # Pan
            self._camera.pan_delta(state.dx, state.dy)
        elif state.left and self._transform_mode == TransformMode.NONE:
            # Orbit
            self._camera.orbit_delta(state.dx, state.dy)
        elif state.left and self._transform_mode != TransformMode.NONE:
            # Gizmo drag — accumulate offset from drag start
            self._drag_offset[0] += state.dx * 0.01
            self._drag_offset[1] -= state.dy * 0.01
            self._transform.update_drag(self._drag_offset)

    def _on_mouse_release(self, state: MouseState, button: str) -> None:
        """Handle mouse release events."""
        if button != "left":
            return
        if self._transform_mode != TransformMode.NONE:
            self._transform.end_drag()
            self._gizmos.interaction_end()

    def _on_wheel(self, delta: float) -> None:
        """Handle mouse wheel — forward to camera zoom."""
        self._camera.zoom_delta(delta)

    # -- Editor event listeners ---------------------------------------------

    def _on_editor_event(self, event: Any) -> None:
        """React to editor events that need a redraw."""
        # Propagate to viewport widget via a callback
        if hasattr(self, "_redraw_callback") and self._redraw_callback is not None:
            self._redraw_callback()

    def set_redraw_callback(self, callback: Callable[[], object]) -> None:
        """Set a callback that requests a viewport redraw.

        Called internally when editor state changes require a visual update.
        """
        self._redraw_callback = callback

        # Subscribe to events that require redraws
        self._editor_bus.subscribe(ViewportDirty, self._on_editor_event)
