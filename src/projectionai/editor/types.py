"""Shared types, enums, and data classes for the editor package."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TransformMode(Enum):
    """Active transform tool type."""

    NONE = auto()
    TRANSLATE = auto()
    ROTATE = auto()
    SCALE = auto()


class TransformSpace(Enum):
    """Coordinate space for transforms."""

    WORLD = auto()
    LOCAL = auto()


class PivotMode(Enum):
    """Pivot point for transforms."""

    CENTER = auto()
    MEDIAN = auto()
    INDIVIDUAL = auto()
    CURSOR = auto()


class CameraProjection(Enum):
    """Camera projection mode."""

    PERSPECTIVE = auto()
    ORTHOGRAPHIC = auto()


class CameraPreset(Enum):
    """Named camera view presets."""

    PERSPECTIVE = auto()
    FRONT = auto()
    BACK = auto()
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()


class SnapMode(Enum):
    """Snap mode for grid / angle / scale."""

    TRANSLATION = auto()
    ROTATION = auto()
    SCALE = auto()


class SelectionMode(Enum):
    """Selection interaction mode."""

    REPLACE = auto()
    ADD = auto()
    TOGGLE = auto()


class BoxSelectionMode(Enum):
    """Box selection type."""

    ENCLOSE = auto()  # fully inside
    TOUCH = auto()  # partially inside (future)


class GizmoDomain(Enum):
    """Domains that can own gizmos — tools plug into these."""

    TRANSFORM = auto()
    PROJECTOR = auto()
    CALIBRATION = auto()
    CAMERA = auto()
    CUSTOM = auto()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SelectionState:
    """Current selection state."""

    object_ids: set[str] = field(default_factory=set)
    active_id: str | None = None


@dataclass(frozen=True, eq=False)
class Ray:
    """A 3D ray used for picking / hit-testing."""

    origin: NDArray[np.float64]
    direction: NDArray[np.float64]


@dataclass
class EditorViewState:
    """Serialisable editor viewport state."""

    camera_distance: float = 15.0
    camera_azimuth: float = 0.785  # pi/4
    camera_polar: float = 1.099  # pi*0.35
    camera_target_x: float = 0.0
    camera_target_y: float = 0.0
    camera_target_z: float = 0.0
    projection: CameraProjection = CameraProjection.PERSPECTIVE
    transform_space: TransformSpace = TransformSpace.WORLD
    pivot_mode: PivotMode = PivotMode.CENTER
    show_grid: bool = True
    show_axes: bool = True
    show_bounding_boxes: bool = False
    show_selection_outlines: bool = True
    show_statistics: bool = False
    snap_enabled: bool = False
    snap_translation: float = 0.25
    snap_rotation: float = 15.0  # degrees
    snap_scale: float = 0.1
