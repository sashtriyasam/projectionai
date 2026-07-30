"""Camera controller — orbit, pan, zoom, focus, and presets.

Wraps the existing :class:`OrbitCamera` and adds editor-level camera
management: smooth transitions, named presets, and projection toggling.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from projectionai.editor.events import (
    CameraChanged,
    CameraPresetApplied,
    CameraProjectionChanged,
    EditorEventBus,
)
from projectionai.editor.types import CameraPreset, CameraProjection
from projectionai.infrastructure.renderer.camera import (
    OrbitCamera,
    OrthographicCamera,
    PerspectiveCamera,
)


class CameraController:
    """Controls the viewport camera.

    Wraps an :class:`OrbitCamera` and adds:

    - Orbit / pan / zoom with configurable speed.
    - Focus on a specific object or world position.
    - Frame all objects to fit the viewport.
    - Perspective / orthographic toggle.
    - Named camera presets (front, back, left, right, top, bottom).
    - Smooth transitions via ``lerp`` target animation.
    """

    def __init__(
        self,
        orbit_camera: OrbitCamera,
        event_bus: EditorEventBus | None = None,
    ) -> None:
        self._orbit: OrbitCamera = orbit_camera
        self._event_bus = event_bus

        # Projection state
        self._projection: CameraProjection = CameraProjection.PERSPECTIVE

        # Smooth target animation
        self._target_look_at: tuple[float, float, float] | None = None
        self._target_distance: float | None = None
        self._animation_duration: float = 0.5  # seconds
        self._animation_elapsed: float = 0.0
        self._animating: bool = False
        self._start_pos: NDArray[np.float64] | None = None
        self._start_target: NDArray[np.float64] | None = None
        self._end_pos: NDArray[np.float64] | None = None
        self._end_target: NDArray[np.float64] | None = None

    # -- Properties ---------------------------------------------------------

    @property
    def orbit(self) -> OrbitCamera:
        """The underlying orbit camera."""
        return self._orbit

    @property
    def projection(self) -> CameraProjection:
        """Current projection mode."""
        return self._projection

    @projection.setter
    def projection(self, value: CameraProjection) -> None:
        if value != self._projection:
            self._set_projection(value)
            self._projection = value
            if self._event_bus:
                self._event_bus.emit(CameraProjectionChanged(projection=value))

    def toggle_projection(self) -> None:
        """Toggle between perspective and orthographic."""
        new = (
            CameraProjection.ORTHOGRAPHIC
            if self._projection == CameraProjection.PERSPECTIVE
            else CameraProjection.PERSPECTIVE
        )
        self.projection = new

    # -- Camera manipulation -------------------------------------------------

    def orbit_delta(self, dx: float, dy: float) -> None:
        """Orbit the camera by a screen-space delta.

        Args:
            dx: Horizontal delta in pixels.
            dy: Vertical delta in pixels.
        """
        self._orbit.orbit(dx, -dy)
        self._notify()

    def pan_delta(self, dx: float, dy: float) -> None:
        """Pan the camera target.

        Args:
            dx: Horizontal delta in pixels.
            dy: Vertical delta in pixels.
        """
        speed = 0.02 * self._orbit.distance
        self._orbit.pan(-dx * speed, dy * speed)
        self._notify()

    def zoom_delta(self, delta: float) -> None:
        """Zoom the camera.

        Args:
            delta: Scroll wheel delta value.
        """
        zoom_factor = 1.0 - (delta / 1200.0)
        self._orbit.zoom(zoom_factor)
        self._notify()

    def zoom_absolute(self, distance: float) -> None:
        """Set the camera distance from target."""
        self._orbit.zoom_absolute(distance)
        self._notify()

    # -- Focus --------------------------------------------------------------

    def focus_on_point(
        self,
        world_point: tuple[float, float, float],
        distance: float | None = None,
    ) -> None:
        """Focus the camera on a world-space point.

        Args:
            world_point: The (x, y, z) position to center on.
            distance: Optional new camera distance.
        """
        self._orbit.target = world_point
        if distance is not None:
            self._orbit.distance = distance
        self._orbit.sync_position()
        self._notify()

    def focus_on_bounds(
        self,
        center: tuple[float, float, float],
        radius: float,
        padding: float = 1.5,
    ) -> None:
        """Frame an object defined by a bounding sphere.

        Args:
            center: Bounding sphere center.
            radius: Bounding sphere radius.
            padding: Multiplier for camera distance.
        """
        self._orbit.frame_scene(center, radius * padding)
        self._notify()

    def frame_selected(self, positions: list[tuple[float, float, float]]) -> None:
        """Frame a set of selected object positions.

        Args:
            positions: List of (x, y, z) world-space positions.
        """
        if not positions:
            return
        arr = np.array(positions, dtype=np.float64)
        center = tuple(arr.mean(axis=0).tolist())
        max_dist = float(np.max(np.linalg.norm(arr - arr.mean(axis=0), axis=1)))
        self.focus_on_bounds(center, max_dist)

    # -- Camera presets -----------------------------------------------------

    def apply_preset(self, preset: CameraPreset) -> None:
        """Apply a named camera preset view.

        Args:
            preset: The preset to apply.
        """
        target = (0.0, 0.0, 0.0)
        distance = 15.0
        up: tuple[float, float, float] = (0.0, 1.0, 0.0)
        eye: tuple[float, float, float]

        if preset == CameraPreset.PERSPECTIVE:
            self.projection = CameraProjection.PERSPECTIVE
            self._orbit.reset_view()
            self._notify()
        elif preset in (
            CameraPreset.FRONT,
            CameraPreset.BACK,
            CameraPreset.LEFT,
            CameraPreset.RIGHT,
            CameraPreset.TOP,
            CameraPreset.BOTTOM,
        ):
            if preset == CameraPreset.FRONT:
                eye = (0.0, 0.0, distance)
            elif preset == CameraPreset.BACK:
                eye = (0.0, 0.0, -distance)
            elif preset == CameraPreset.LEFT:
                eye = (-distance, 0.0, 0.0)
            elif preset == CameraPreset.RIGHT:
                eye = (distance, 0.0, 0.0)
            elif preset == CameraPreset.TOP:
                eye = (0.0, distance, 0.0)
                up = (0.0, 0.0, -1.0)
            elif preset == CameraPreset.BOTTOM:
                eye = (0.0, -distance, 0.0)
                up = (0.0, 0.0, 1.0)

            self._orbit.look_at(eye, target, up)
            self._notify()
        else:
            return  # unsupported preset — no event

        if self._event_bus:
            self._event_bus.emit(CameraPresetApplied(preset=preset))

    # -- Smooth animation ---------------------------------------------------

    def animate_to(
        self,
        target: tuple[float, float, float],
        distance: float | None = None,
        duration: float = 0.5,
    ) -> None:
        """Smoothly animate the camera to a new target position.

        Args:
            target: The (x, y, z) world-space target.
            distance: Optional new camera distance.
            duration: Animation duration in seconds.
        """
        self._target_look_at = target
        self._target_distance = distance
        self._animation_duration = max(duration, 0.1)
        self._animation_elapsed = 0.0
        self._animating = True

        self._start_target = self._orbit.target.copy()
        self._start_pos = self._orbit.position.copy()

        end_target = np.array(target, dtype=np.float64)
        self._end_target = end_target
        if distance is not None:
            direction = self._orbit.position - self._orbit.target
            direction_norm = direction / (np.linalg.norm(direction) + 1e-30)
            self._end_pos = end_target + direction_norm * distance
        else:
            self._end_pos = self._orbit.position.copy()

    def update(self, dt: float) -> None:
        """Update smooth animation. Call once per frame.

        Args:
            dt: Delta time in seconds.
        """
        self._orbit.update(dt)

        if not self._animating:
            return

        self._animation_elapsed += dt
        t = min(self._animation_elapsed / self._animation_duration, 1.0)
        # Smooth step
        t_smooth = t * t * (3.0 - 2.0 * t)

        if self._start_pos is not None and self._end_pos is not None:
            pos = (1.0 - t_smooth) * self._start_pos + t_smooth * self._end_pos
            self._orbit.position = tuple(pos.tolist())

        if self._start_target is not None and self._end_target is not None:
            tgt = (1.0 - t_smooth) * self._start_target + t_smooth * self._end_target
            self._orbit.target = tuple(tgt.tolist())

        if t >= 1.0:
            self._animating = False
            self._target_look_at = None

    # -- Internal -----------------------------------------------------------

    def _set_projection(self, projection: CameraProjection) -> None:
        """Swap the inner camera type."""
        inner = self._orbit.inner
        w, h = 16.0, 9.0
        if isinstance(inner, PerspectiveCamera):
            w, h = inner.aspect_ratio * 10, 10.0
            if projection == CameraProjection.ORTHOGRAPHIC:
                ortho = OrthographicCamera(-w, w, -h, h)
                ortho.position = tuple(inner.position.tolist())
                ortho.target = tuple(inner.target.tolist())
                ortho.near = inner.near
                ortho.far = inner.far
                self._orbit.inner = ortho
        elif isinstance(inner, OrthographicCamera):
            if projection == CameraProjection.PERSPECTIVE:
                persp = PerspectiveCamera(
                    fov_degrees=60.0,
                    aspect_ratio=inner.right / max(inner.top, 0.01),
                )
                persp.position = tuple(inner.position.tolist())
                persp.target = tuple(inner.target.tolist())
                persp.near = inner.near
                persp.far = inner.far
                self._orbit.inner = persp

    def _notify(self) -> None:
        """Emit a camera-changed event if listeners are registered."""
        if self._event_bus:
            self._event_bus.emit(CameraChanged())
