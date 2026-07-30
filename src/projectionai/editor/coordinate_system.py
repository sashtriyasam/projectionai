"""Coordinate system — manages world-space vs local-space transforms."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.geometry import Pose
from projectionai.editor.events import EditorEventBus, SpaceChanged
from projectionai.editor.types import TransformSpace


class CoordinateSystem:
    """Tracks the active transform space and provides orientation helpers.

    The coordinate system can be either *world* (axes are fixed in world
    space) or *local* (axes follow the selected object's orientation).
    This affects how gizmos are drawn and how transform deltas are
    applied.
    """

    def __init__(self, event_bus: EditorEventBus | None = None) -> None:
        self._event_bus = event_bus
        self._space: TransformSpace = TransformSpace.WORLD

    # -- Properties ---------------------------------------------------------

    @property
    def space(self) -> TransformSpace:
        """Current transform space."""
        return self._space

    @space.setter
    def space(self, value: TransformSpace) -> None:
        if value != self._space:
            self._space = value
            if self._event_bus:
                self._event_bus.emit(SpaceChanged(space=value))

    @property
    def is_world(self) -> bool:
        """``True`` if in world space."""
        return self._space == TransformSpace.WORLD

    @property
    def is_local(self) -> bool:
        """``True`` if in local space."""
        return self._space == TransformSpace.LOCAL

    # -- Orientation --------------------------------------------------------

    def get_orientation(self, pose: Pose | None = None) -> NDArray[np.float32]:
        """Return the 3x3 rotation matrix for the current space.

        Args:
            pose: The object's pose. Required for local space; ignored in
                  world space.

        Returns:
            3x3 rotation matrix (float32).
        """
        if self._space == TransformSpace.LOCAL and pose is not None:
            return pose.as_matrix()[:3, :3].astype(np.float32)
        return np.eye(3, dtype=np.float32)

    def world_to_local(
        self, world_delta: NDArray[np.float64], pose: Pose
    ) -> NDArray[np.float64]:
        """Transform a world-space delta into local space.

        Args:
            world_delta: 3-element vector in world space.
            pose: Object pose defining the local frame.

        Returns:
            3-element vector in local space.
        """
        rot = pose.as_matrix()[:3, :3]
        return rot.T @ world_delta  # inverse rotation

    def local_to_world(
        self, local_delta: NDArray[np.float64], pose: Pose
    ) -> NDArray[np.float64]:
        """Transform a local-space delta into world space.

        Args:
            local_delta: 3-element vector in local space.
            pose: Object pose defining the local frame.

        Returns:
            3-element vector in world space.
        """
        rot = pose.as_matrix()[:3, :3]
        return rot @ local_delta

    def toggle(self) -> None:
        """Toggle between world and local space."""
        self.space = TransformSpace.LOCAL if self.is_world else TransformSpace.WORLD

    def __repr__(self) -> str:
        return f"CoordinateSystem({self._space.name})"
