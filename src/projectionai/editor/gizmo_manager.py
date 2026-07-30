"""Gizmo manager — manages the active gizmo and delegates rendering."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from projectionai.editor.events import (
    EditorEvent,
    EditorEventBus,
    GizmoDomainChanged,
    SelectionChanged,
)
from projectionai.editor.types import GizmoDomain, TransformMode

# ---------------------------------------------------------------------------
# Gizmo interface (what every gizmo must implement)
# ---------------------------------------------------------------------------


class Gizmo(Protocol):
    """Protocol for all gizmos.

    Gizmos are rendered as part of the editor overlay and handle
    their own hit-testing and interaction logic.
    """

    domain: GizmoDomain

    def render(
        self,
        model_matrix: NDArray[np.float32],
        view_matrix: NDArray[np.float32],
        projection_matrix: NDArray[np.float32],
        viewport_size: tuple[int, int],
    ) -> None:
        """Draw the gizmo for the current frame."""
        ...

    def hit_test(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> tuple[bool, float]:
        """Test if a ray intersects this gizmo.

        Returns:
            Tuple of (hit, distance).
        """
        ...

    def interaction_start(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> None:
        """Begin an interaction with this gizmo."""
        ...

    def interaction_update(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> NDArray[np.float64] | None:
        """Update ongoing interaction.

        Returns:
            A delta vector if the interaction changed the transform, or ``None``.
        """
        ...

    def interaction_end(self) -> None:
        """End the current interaction."""
        ...


# ---------------------------------------------------------------------------
# Concrete gizmo stubs
# ---------------------------------------------------------------------------


class TranslateGizmo:
    """Move gizmo — three-axis arrow handles."""

    domain: GizmoDomain = GizmoDomain.TRANSFORM

    def __init__(self) -> None:
        self._active_axis: int | None = None  # 0=x, 1=y, 2=z
        self._drag_start: NDArray[np.float64] | None = None

    def render(
        self,
        model_matrix: NDArray[np.float32],
        view_matrix: NDArray[np.float32],
        projection_matrix: NDArray[np.float32],
        viewport_size: tuple[int, int],
    ) -> None:
        # Rendering is handled by the render pipeline via gizmo pass
        pass

    def hit_test(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> tuple[bool, float]:
        # Future: ray-cylinder / ray-cone intersection for each axis
        return False, 0.0

    def interaction_start(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> None:
        self._drag_start = ray_origin.copy()

    def interaction_update(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> NDArray[np.float64] | None:
        # Future: compute delta along active axis
        return None

    def interaction_end(self) -> None:
        self._active_axis = None
        self._drag_start = None


class RotateGizmo:
    """Rotate gizmo — three-axis arc-ball handles."""

    domain: GizmoDomain = GizmoDomain.TRANSFORM

    def __init__(self) -> None:
        self._active_axis: int | None = None

    def render(
        self,
        model_matrix: NDArray[np.float32],
        view_matrix: NDArray[np.float32],
        projection_matrix: NDArray[np.float32],
        viewport_size: tuple[int, int],
    ) -> None:
        pass

    def hit_test(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> tuple[bool, float]:
        return False, 0.0

    def interaction_start(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> None:
        pass

    def interaction_update(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> NDArray[np.float64] | None:
        return None

    def interaction_end(self) -> None:
        self._active_axis = None


class ScaleGizmo:
    """Scale gizmo — three-axis scale handles + uniform center."""

    domain: GizmoDomain = GizmoDomain.TRANSFORM

    def __init__(self) -> None:
        self._uniform: bool = False

    def render(
        self,
        model_matrix: NDArray[np.float32],
        view_matrix: NDArray[np.float32],
        projection_matrix: NDArray[np.float32],
        viewport_size: tuple[int, int],
    ) -> None:
        pass

    def hit_test(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> tuple[bool, float]:
        return False, 0.0

    def interaction_start(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> None:
        pass

    def interaction_update(
        self, ray_origin: NDArray[np.float64], ray_direction: NDArray[np.float64]
    ) -> NDArray[np.float64] | None:
        return None

    def interaction_end(self) -> None:
        pass


# Mapping from TransformMode to gizmo instance
_GIZMO_MAP: dict[TransformMode, type] = {
    TransformMode.TRANSLATE: TranslateGizmo,
    TransformMode.ROTATE: RotateGizmo,
    TransformMode.SCALE: ScaleGizmo,
}


# ---------------------------------------------------------------------------
# Gizmo manager
# ---------------------------------------------------------------------------


class GizmoManager:
    """Manages gizmo lifecycle and domain switching.

    The manager owns the gizmo instances and delegates to the active
    gizmo for hit-testing and interaction.

    Gizmos are reusable across domains: the same translation gizmo
    works for scene objects, projectors, cameras, and calibration
    points. The domain parameter determines the colour / styling.
    """

    def __init__(self, event_bus: EditorEventBus | None = None) -> None:
        self._event_bus = event_bus
        self._domain: GizmoDomain = GizmoDomain.TRANSFORM
        self._mode: TransformMode = TransformMode.NONE

        # Lazy-initialized gizmo instances
        self._gizmos: dict[TransformMode, Any] = {}
        self._custom_gizmos: dict[str, Any] = {}
        self._selected_ids: set[str] = set()

        if self._event_bus is not None:
            self._event_bus.subscribe(SelectionChanged, self._on_selection_changed)

    # -- Properties ---------------------------------------------------------

    @property
    def domain(self) -> GizmoDomain:
        """Active gizmo domain."""
        return self._domain

    @domain.setter
    def domain(self, value: GizmoDomain) -> None:
        if value != self._domain:
            self._domain = value
            if self._event_bus:
                self._event_bus.emit(GizmoDomainChanged(domain=value))

    @property
    def mode(self) -> TransformMode:
        """Active transform mode (which gizmo is shown)."""
        return self._mode

    @mode.setter
    def mode(self, value: TransformMode) -> None:
        self._mode = value

    @property
    def active_gizmo(self) -> Any | None:
        """The currently active gizmo instance, or ``None``."""
        if self._mode == TransformMode.NONE:
            return None
        gizmo = self._gizmos.get(self._mode)
        if gizmo is None:
            cls = _GIZMO_MAP.get(self._mode)
            if cls is not None:
                gizmo = cls()
                self._gizmos[self._mode] = gizmo
        return gizmo

    @property
    def is_active(self) -> bool:
        """``True`` if a gizmo is currently visible."""
        return self._mode != TransformMode.NONE and len(self._selected_ids) > 0

    # -- Selection context --------------------------------------------------

    def update_selection(self, object_ids: frozenset[str]) -> None:
        """Update which objects are selected (affects gizmo position)."""
        self._selected_ids = set(object_ids)

    def _on_selection_changed(self, event: EditorEvent) -> None:
        """Keep ``_selected_ids`` in sync with the viewport selection."""
        if isinstance(event, SelectionChanged):
            self.update_selection(frozenset(event.object_ids))

    # -- Custom gizmo registration ------------------------------------------

    def register_gizmo(self, name: str, gizmo: Any) -> None:
        """Register a custom gizmo for a specific domain.

        Args:
            name: Unique gizmo name (e.g. ``"projector_frustum"``).
            gizmo: An object implementing the ``Gizmo`` protocol.
        """
        self._custom_gizmos[name] = gizmo

    def unregister_gizmo(self, name: str) -> None:
        """Remove a previously registered custom gizmo."""
        self._custom_gizmos.pop(name, None)

    def get_custom_gizmo(self, name: str) -> Any | None:
        """Look up a custom gizmo by name."""
        return self._custom_gizmos.get(name)

    @property
    def custom_gizmos(self) -> frozenset[str]:
        """Names of registered custom gizmos."""
        return frozenset(self._custom_gizmos)

    # -- Interaction delegation ---------------------------------------------

    def hit_test_active(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> tuple[bool, float]:
        """Forward a hit-test to the active gizmo.

        Returns:
            Tuple of (hit, distance).
        """
        gizmo = self.active_gizmo
        if gizmo is None:
            return False, 0.0
        result: tuple[bool, float] = gizmo.hit_test(ray_origin, ray_direction)
        return result

    def interaction_start(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> None:
        """Begin gizmo interaction."""
        gizmo = self.active_gizmo
        if gizmo is not None:
            gizmo.interaction_start(ray_origin, ray_direction)

    def interaction_update(
        self,
        ray_origin: NDArray[np.float64],
        ray_direction: NDArray[np.float64],
    ) -> NDArray[np.float64] | None:
        """Update gizmo interaction.

        Returns:
            Transform delta or ``None``.
        """
        gizmo = self.active_gizmo
        if gizmo is None:
            return None
        delta: NDArray[np.float64] | None = gizmo.interaction_update(
            ray_origin, ray_direction
        )
        return delta

    def interaction_end(self) -> None:
        """End gizmo interaction."""
        gizmo = self.active_gizmo
        if gizmo is not None:
            gizmo.interaction_end()

    # -- Rendering ----------------------------------------------------------

    def render_gizmos(
        self,
        model_matrix: NDArray[np.float32],
        view_matrix: NDArray[np.float32],
        projection_matrix: NDArray[np.float32],
        viewport_size: tuple[int, int],
    ) -> None:
        """Render all visible gizmos for the current frame.

        Called by the editor viewport's render pipeline.
        """
        gizmo = self.active_gizmo
        if gizmo is not None:
            gizmo.render(model_matrix, view_matrix, projection_matrix, viewport_size)
