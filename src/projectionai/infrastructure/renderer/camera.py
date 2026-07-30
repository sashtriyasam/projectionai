"""Camera system — perspective, orthographic, and orbit cameras.

All cameras produce view and projection matrices compatible with ModernGL.
Orbit camera wraps either a perspective or orthographic camera and adds
interactive controls (orbit, pan, zoom).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum, auto

import numpy as np
from numpy.typing import NDArray


class MouseButton(IntEnum):
    """Mouse button identifiers used by OrbitCamera controls."""

    LEFT = auto()
    RIGHT = auto()
    MIDDLE = auto()


# ---------------------------------------------------------------------------
# Base camera
# ---------------------------------------------------------------------------


class Camera(ABC):
    """Abstract base for all cameras.

    Subclasses must implement ``view_matrix`` and ``projection_matrix``.
    """

    def __init__(self) -> None:
        self._position: NDArray[np.float64] = np.array(
            [0.0, 0.0, 5.0], dtype=np.float64
        )
        self._target: NDArray[np.float64] = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        self._up: NDArray[np.float64] = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        self._near: float = 0.01
        self._far: float = 1000.0
        self._dirty = True
        self._view_matrix: NDArray[np.float32] = np.eye(4, dtype=np.float32)
        self._projection_matrix: NDArray[np.float32] = np.eye(4, dtype=np.float32)

    # -- Abstract interface -------------------------------------------------

    @abstractmethod
    def _compute_projection(self) -> NDArray[np.float32]:
        """Recalculate the projection matrix (subclass responsibility)."""

    # -- Properties ---------------------------------------------------------

    @property
    def position(self) -> NDArray[np.float64]:
        """Camera world-space position."""
        return self._position.copy()

    @position.setter
    def position(self, value: tuple[float, float, float] | NDArray[np.float64]) -> None:
        self._position = np.asarray(value, dtype=np.float64)
        self._dirty = True

    @property
    def target(self) -> NDArray[np.float64]:
        """Look-at target."""
        return self._target.copy()

    @target.setter
    def target(self, value: tuple[float, float, float] | NDArray[np.float64]) -> None:
        self._target = np.asarray(value, dtype=np.float64)
        self._dirty = True

    @property
    def up(self) -> NDArray[np.float64]:
        """Up vector."""
        return self._up.copy()

    @up.setter
    def up(self, value: tuple[float, float, float] | NDArray[np.float64]) -> None:
        self._up = np.asarray(value, dtype=np.float64)
        self._dirty = True

    @property
    def near(self) -> float:
        """Near clipping plane distance."""
        return self._near

    @near.setter
    def near(self, value: float) -> None:
        self._near = max(value, 1e-6)
        self._dirty = True

    @property
    def far(self) -> float:
        """Far clipping plane distance."""
        return self._far

    @far.setter
    def far(self, value: float) -> None:
        self._far = max(value, self._near + 1e-6)
        self._dirty = True

    # -- Matrix access -----------------------------------------------------

    @property
    def view_matrix(self) -> NDArray[np.float32]:
        """4x4 view matrix (column-major for ModernGL)."""
        if self._dirty:
            self._view_matrix = self._compute_view()
            self._projection_matrix = self._compute_projection()
            self._dirty = False
        return self._view_matrix

    @property
    def projection_matrix(self) -> NDArray[np.float32]:
        """4x4 projection matrix (column-major for ModernGL)."""
        if self._dirty:
            self._view_matrix = self._compute_view()
            self._projection_matrix = self._compute_projection()
            self._dirty = False
        return self._projection_matrix

    @property
    def view_projection_matrix(self) -> NDArray[np.float32]:
        """Combined view-projection matrix."""
        return self.projection_matrix @ self.view_matrix

    # -- Internal -----------------------------------------------------------

    def _compute_view(self) -> NDArray[np.float32]:
        """Build a look-at view matrix."""
        forward = self._target - self._position
        fwd_norm = forward / (np.linalg.norm(forward) + 1e-30)
        right = np.cross(fwd_norm, self._up)
        right_norm = right / (np.linalg.norm(right) + 1e-30)
        real_up = np.cross(right_norm, fwd_norm)

        mat = np.eye(4, dtype=np.float32)
        mat[0, :3] = right_norm
        mat[1, :3] = real_up
        mat[2, :3] = -fwd_norm
        mat[:3, 3] = (
            -right_norm @ self._position,
            -real_up @ self._position,
            fwd_norm @ self._position,
        )
        return mat

    @property
    def is_dirty(self) -> bool:
        """Whether cached matrices need recalculation."""
        return self._dirty

    def mark_dirty(self) -> None:
        """Force matrix recalculation on next access."""
        self._dirty = True

    def look_at(
        self,
        eye: tuple[float, float, float],
        target: tuple[float, float, float],
        up: tuple[float, float, float] | None = None,
    ) -> None:
        """Position the camera with a look-at transformation."""
        self._position = np.array(eye, dtype=np.float64)
        self._target = np.array(target, dtype=np.float64)
        if up is not None:
            self._up = np.array(up, dtype=np.float64)
        self._dirty = True

    def forward(self) -> NDArray[np.float64]:
        """Camera forward direction in world space."""
        return self._target - self._position

    def __repr__(self) -> str:
        return f"{type(self).__name__}(pos={self._position}, target={self._target})"


# ---------------------------------------------------------------------------
# Perspective camera
# ---------------------------------------------------------------------------


class PerspectiveCamera(Camera):
    """Standard perspective (pinhole) camera."""

    def __init__(
        self, fov_degrees: float = 60.0, aspect_ratio: float = 16.0 / 9.0
    ) -> None:
        super().__init__()
        self._fov: float = math.radians(fov_degrees)
        self._aspect: float = aspect_ratio

    @property
    def fov(self) -> float:
        """Field of view in radians."""
        return self._fov

    @fov.setter
    def fov(self, value_radians: float) -> None:
        self._fov = max(0.01, min(value_radians, math.pi - 0.01))
        self._dirty = True

    @property
    def fov_degrees(self) -> float:
        """Field of view in degrees."""
        return math.degrees(self._fov)

    @fov_degrees.setter
    def fov_degrees(self, value: float) -> None:
        self.fov = math.radians(max(1.0, min(value, 179.0)))

    @property
    def aspect_ratio(self) -> float:
        """Width / height ratio."""
        return self._aspect

    @aspect_ratio.setter
    def aspect_ratio(self, value: float) -> None:
        self._aspect = max(0.01, value)
        self._dirty = True

    def _compute_projection(self) -> NDArray[np.float32]:
        """Build perspective projection matrix."""
        f = 1.0 / math.tan(self._fov * 0.5)
        mat = np.zeros((4, 4), dtype=np.float32)
        mat[0, 0] = f / self._aspect
        mat[1, 1] = f
        mat[2, 2] = (self._far + self._near) / (self._near - self._far)
        mat[2, 3] = (2.0 * self._far * self._near) / (self._near - self._far)
        mat[3, 2] = -1.0
        return mat


# ---------------------------------------------------------------------------
# Orthographic camera
# ---------------------------------------------------------------------------


class OrthographicCamera(Camera):
    """Orthographic (parallel-projection) camera."""

    def __init__(
        self,
        left: float = -10.0,
        right: float = 10.0,
        bottom: float = -10.0,
        top: float = 10.0,
    ) -> None:
        super().__init__()
        self._left: float = left
        self._right: float = right
        self._bottom: float = bottom
        self._top: float = top

    @property
    def left(self) -> float:
        return self._left

    @left.setter
    def left(self, v: float) -> None:
        self._left = v
        self._dirty = True

    @property
    def right(self) -> float:
        return self._right

    @right.setter
    def right(self, v: float) -> None:
        self._right = v
        self._dirty = True

    @property
    def bottom(self) -> float:
        return self._bottom

    @bottom.setter
    def bottom(self, v: float) -> None:
        self._bottom = v
        self._dirty = True

    @property
    def top(self) -> float:
        return self._top

    @top.setter
    def top(self, v: float) -> None:
        self._top = v
        self._dirty = True

    def _compute_projection(self) -> NDArray[np.float32]:
        """Build orthographic projection matrix."""
        rml = self._right - self._left
        tmb = self._top - self._bottom
        fmn = self._far - self._near
        mat = np.eye(4, dtype=np.float32)
        mat[0, 0] = 2.0 / rml
        mat[1, 1] = 2.0 / tmb
        mat[2, 2] = -2.0 / fmn
        mat[0, 3] = -(self._right + self._left) / rml
        mat[1, 3] = -(self._top + self._bottom) / tmb
        mat[2, 3] = -(self._far + self._near) / fmn
        return mat


# ---------------------------------------------------------------------------
# Orbit camera
# ---------------------------------------------------------------------------


@dataclass
class OrbitConstraints:
    """Limits for orbit camera movement."""

    min_distance: float = 0.1
    max_distance: float = 500.0
    min_polar_angle: float = 0.01  # radians (almost top-down)
    max_polar_angle: float = math.pi - 0.01  # radians (almost bottom-up)
    zoom_speed: float = 1.0
    orbit_speed: float = 0.005
    pan_speed: float = 0.01


class OrbitCamera(Camera):
    """Orbit camera that rotates around a target point.

    Supports:
    - Orbiting (rotate around target)
    - Panning (move target and camera together)
    - Zooming (move camera closer/farther from target)
    - Damping (smooth interpolation)
    """

    def __init__(self, camera: Camera | None = None) -> None:
        super().__init__()
        self._inner: Camera = camera or PerspectiveCamera()
        self._constraints: OrbitConstraints = OrbitConstraints()

        # Spherical coordinates relative to target
        self._distance: float = 10.0
        self._theta: float = math.pi * 0.25  # azimuth
        self._phi: float = math.pi * 0.35  # polar (0 = top-down)

        # Smooth damping
        self._target_theta: float = self._theta
        self._target_phi: float = self._phi
        self._target_distance: float = self._distance
        self._damping: float = 0.85
        self._enabled: bool = True

        self._sync_position()

    # -- Properties ---------------------------------------------------------

    @property
    def inner(self) -> Camera:
        """Return the wrapped camera (useful for matrix access)."""
        return self._inner

    @inner.setter
    def inner(self, camera: Camera) -> None:
        """Swap the wrapped camera."""
        self._inner = camera
        self._sync_position()

    @property
    def constraints(self) -> OrbitConstraints:
        return self._constraints

    @property
    def distance(self) -> float:
        return self._distance

    @distance.setter
    def distance(self, value: float) -> None:
        self._target_distance = max(
            self._constraints.min_distance, min(value, self._constraints.max_distance)
        )

    @property
    def azimuth(self) -> float:
        """Horizontal orbit angle in radians."""
        return self._theta

    @azimuth.setter
    def azimuth(self, value: float) -> None:
        self._target_theta = value

    @property
    def polar(self) -> float:
        """Vertical orbit angle in radians (0 = top-down)."""
        return self._phi

    @polar.setter
    def polar(self, value: float) -> None:
        self._target_phi = max(
            self._constraints.min_polar_angle,
            min(value, self._constraints.max_polar_angle),
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    # -- Control helpers ----------------------------------------------------

    def orbit(self, delta_x: float, delta_y: float) -> None:
        """Rotate around the target by screen-space delta."""
        if not self._enabled:
            return
        self._target_theta += delta_x * self._constraints.orbit_speed
        self._target_phi = max(
            self._constraints.min_polar_angle,
            min(
                self._constraints.max_polar_angle,
                self._target_phi + delta_y * self._constraints.orbit_speed,
            ),
        )

    def pan(self, delta_x: float, delta_y: float) -> None:
        """Translate the camera target in screen space."""
        if not self._enabled:
            return
        fwd = self.forward()
        fwd_norm = fwd / (np.linalg.norm(fwd) + 1e-30)
        right = np.cross(fwd_norm, self._up)
        right_norm = right / (np.linalg.norm(right) + 1e-30)
        up = np.cross(right_norm, fwd_norm)

        speed = self._distance * self._constraints.pan_speed
        offset = (-right_norm * delta_x + up * delta_y) * speed
        self._target += offset

    def zoom(self, delta: float) -> None:
        """Zoom in/out. Positive = zoom out, negative = zoom in."""
        if not self._enabled:
            return
        self._target_distance = max(
            self._constraints.min_distance,
            min(
                self._constraints.max_distance,
                self._target_distance
                * (1.0 + delta * self._constraints.zoom_speed * 0.01),
            ),
        )

    def zoom_absolute(self, distance: float) -> None:
        """Set absolute zoom distance."""
        self.distance = distance

    def look_at(
        self,
        eye: tuple[float, float, float],
        target: tuple[float, float, float],
        up: tuple[float, float, float] | None = None,
    ) -> None:
        """Position the camera with look-at and recompute orbit state."""
        super().look_at(eye, target, up)
        offset = (self._position - self._target).astype(np.float64)
        self._distance = float(np.linalg.norm(offset))
        self._target_distance = self._distance

        # Derive spherical angles from the eye-target offset so that
        # _sync_position reproduces the requested eye position.
        if self._distance > 1e-10:
            self._theta = math.atan2(offset[2], offset[0])
            self._phi = math.acos(max(-1.0, min(1.0, offset[1] / self._distance)))
        else:
            self._theta = 0.0
            self._phi = math.pi * 0.5

        self._target_theta = self._theta
        self._target_phi = self._phi
        self._sync_position()

    def frame_scene(self, center: tuple[float, float, float], radius: float) -> None:
        """Position the camera to frame a scene sphere."""
        self._target = np.array(center, dtype=np.float64)
        self._target_distance = radius * 2.5
        self._distance = self._target_distance

    def reset_view(self) -> None:
        """Reset to default orbit position."""
        self._target = np.zeros(3, dtype=np.float64)
        self._target_theta = math.pi * 0.25
        self._target_phi = math.pi * 0.35
        self._target_distance = 10.0

    # -- Update -------------------------------------------------------------

    def update(self, dt: float = 0.0) -> None:
        """Smoothly interpolate camera towards target values. Call once per frame."""
        damping = self._damping if dt > 0 else 0.0
        factor = 1.0 - (1.0 - damping) ** (dt * 60.0) if damping > 0 else 1.0

        self._theta += (self._target_theta - self._theta) * factor
        self._phi += (self._target_phi - self._phi) * factor
        self._distance += (self._target_distance - self._distance) * factor
        self._sync_position()

    def _sync_position(self) -> None:
        """Recalculate camera position from spherical coordinates."""
        x = self._distance * math.sin(self._phi) * math.cos(self._theta)
        y = self._distance * math.cos(self._phi)
        z = self._distance * math.sin(self._phi) * math.sin(self._theta)
        self._position = self._target + np.array([x, y, z], dtype=np.float64)
        self._inner.position = tuple(self._position.tolist())
        self._inner.target = tuple(self._target.tolist())
        self._dirty = True

    def sync_position(self) -> None:
        """Synonym for _sync_position — public API for CameraController."""
        self._sync_position()

    # -- Matrix pass-through ------------------------------------------------

    @property
    def view_matrix(self) -> NDArray[np.float32]:
        return self._inner.view_matrix

    @property
    def projection_matrix(self) -> NDArray[np.float32]:
        return self._inner.projection_matrix

    def _compute_projection(self) -> NDArray[np.float32]:
        return self._inner.projection_matrix  # pragma: no cover

    def _compute_view(self) -> NDArray[np.float32]:
        return self._inner.view_matrix  # pragma: no cover
