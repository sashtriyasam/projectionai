"""Editor interaction layer — viewport controller, widgets, and tools.

This package provides the professional editor viewport and interaction
system for ProjectionAI. It is completely separated from the rendering
pipeline: rendering draws, editor tools manipulate.

Architecture
============

::

    ViewportWidget (QOpenGLWidget)
      ├── Renderer (existing infrastructure)
      └── ViewportController
            ├── CameraController    → viewport navigation
            ├── InputManager        → mouse/keyboard routing
            ├── SelectionManager    → object selection
            ├── GizmoManager        → transform gizmos
            ├── TransformTools      → translate/rotate/scale
            ├── OverlayRenderer     → grid, axes, overlays
            │     ├── GridRenderer
            │     └── AxisRenderer
            ├── SnapManager         → snapping
            └── CoordinateSystem    → world/local space

Interaction layer = controllers + managers + tools.
Rendering layer = composition + draw calls (existing infrastructure).

Key design decisions:

- **Separation**: The controller owns all interaction state and never
  calls OpenGL directly. The widget owns the GL context and delegates
  to the renderer for drawing.
- **Testability**: All editor components except the widget itself are
  graphics-independent and fully unit-testable.
- **Extensibility**: Calibration tools, projector manipulation, and
  future features plug in as new tools / gizmos / overlay renderers
  without modifying existing code.
- **Undo/redo**: Every transform operation creates a ``Command`` that
  integrates with the existing ``CommandManager``.
"""

from __future__ import annotations

from projectionai.editor.axis_renderer import AxisRenderer
from projectionai.editor.calibration_overlay import CalibrationOverlay
from projectionai.editor.camera_controller import CameraController
from projectionai.editor.coordinate_system import CoordinateSystem
from projectionai.editor.editor_preferences import EditorPreferences
from projectionai.editor.events import EditorEventBus
from projectionai.editor.gizmo_manager import GizmoManager
from projectionai.editor.grid_renderer import GridRenderer
from projectionai.editor.input_manager import InputManager
from projectionai.editor.overlay_renderer import OverlayRenderer
from projectionai.editor.selection_manager import SelectionManager
from projectionai.editor.snap_manager import SnapManager
from projectionai.editor.transform_tools import TransformTools
from projectionai.editor.types import (
    CameraPreset,
    CameraProjection,
    EditorViewState,
    GizmoDomain,
    PivotMode,
    SelectionMode,
    SnapMode,
    TransformMode,
    TransformSpace,
)
from projectionai.editor.viewport_controller import ViewportController
from projectionai.editor.viewport_widget import ViewportWidget

__all__ = [
    # Subsystems
    "AxisRenderer",
    "CameraController",
    # Types
    "CameraPreset",
    "CameraProjection",
    "CoordinateSystem",
    "EditorEventBus",
    "EditorPreferences",
    "EditorViewState",
    "GizmoDomain",
    "GizmoManager",
    "GridRenderer",
    "InputManager",
    "OverlayRenderer",
    "PivotMode",
    "SelectionManager",
    "SelectionMode",
    "SnapManager",
    "SnapMode",
    "TransformMode",
    "TransformSpace",
    "TransformTools",
    # Widget and controller
    "ViewportController",
    "ViewportWidget",
]
