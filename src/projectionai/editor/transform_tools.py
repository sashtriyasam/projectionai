"""Transform tools — translate, rotate, and scale operations.

Creates undoable commands for transform operations and applies them
through the scene manager. Supports world/local space and snapping.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

from projectionai.core.events import EventBus
from projectionai.domain.command import Command
from projectionai.domain.geometry import Pose, Vec3
from projectionai.editor.coordinate_system import CoordinateSystem
from projectionai.editor.events import EditorEventBus, TransformPerformed
from projectionai.editor.snap_manager import SnapManager
from projectionai.editor.types import PivotMode, SnapMode, TransformMode

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Undoable transform commands
# ---------------------------------------------------------------------------


class TranslateCommand(Command):
    """Undoable translation of one or more objects."""

    def __init__(
        self,
        object_ids: list[str],
        old_positions: list[Vec3],
        new_positions: list[Vec3],
        scene: Any,
    ) -> None:
        super().__init__(name="Translate")
        self._object_ids = object_ids
        self._old_positions = old_positions
        self._new_positions = new_positions
        self._scene = scene

    async def execute(self) -> None:
        if self._scene is None:
            return
        for oid, pos in zip(self._object_ids, self._new_positions, strict=True):
            self._scene.set_node_transform(oid, position=pos)

    async def undo(self) -> None:
        if self._scene is None:
            return
        for oid, pos in zip(self._object_ids, self._old_positions, strict=True):
            self._scene.set_node_transform(oid, position=pos)


class RotateCommand(Command):
    """Undoable rotation of one or more objects."""

    def __init__(
        self,
        object_ids: list[str],
        old_rotations: list[tuple[float, float, float, float]],
        new_rotations: list[tuple[float, float, float, float]],
    ) -> None:
        super().__init__(name="Rotate")
        self._object_ids = object_ids
        self._old_rotations = old_rotations
        self._new_rotations = new_rotations
        self._scene: Any = None

    async def execute(self) -> None:
        if self._scene is None:
            return
        for oid, rot in zip(self._object_ids, self._new_rotations, strict=True):
            self._scene.set_node_transform(oid, rotation=rot)

    async def undo(self) -> None:
        if self._scene is None:
            return
        for oid, rot in zip(self._object_ids, self._old_rotations, strict=True):
            self._scene.set_node_transform(oid, rotation=rot)


class ScaleCommand(Command):
    """Undoable scaling of one or more objects."""

    def __init__(
        self,
        object_ids: list[str],
        old_scales: list[Vec3],
        new_scales: list[Vec3],
    ) -> None:
        super().__init__(name="Scale")
        self._object_ids = object_ids
        self._old_scales = old_scales
        self._new_scales = new_scales
        self._scene: Any = None

    async def execute(self) -> None:
        if self._scene is None:
            return
        for oid, s in zip(self._object_ids, self._new_scales, strict=True):
            self._scene.set_node_transform(oid, scale=s)

    async def undo(self) -> None:
        if self._scene is None:
            return
        for oid, s in zip(self._object_ids, self._old_scales, strict=True):
            self._scene.set_node_transform(oid, scale=s)


# ---------------------------------------------------------------------------
# Transform tools orchestrator
# ---------------------------------------------------------------------------


class TransformTools:
    """Orchestrates translate / rotate / scale operations.

    Works with the scene manager to apply transforms, the snap manager
    for constrained values, and the command manager for undo/redo.

    All transform deltas are applied in the active coordinate space
    (world or local).
    """

    def __init__(
        self,
        scene_manager: Any | None = None,
        command_manager: Any | None = None,
        snap_manager: SnapManager | None = None,
        coordinate_system: CoordinateSystem | None = None,
        event_bus: EditorEventBus | None = None,
        core_event_bus: EventBus | None = None,
    ) -> None:
        self._scene = scene_manager
        self._commands = command_manager
        self._snap = snap_manager or SnapManager()
        self._coords = coordinate_system or CoordinateSystem()
        self._event_bus = event_bus
        self._core_bus = core_event_bus
        self._mode: TransformMode = TransformMode.TRANSLATE
        self._pivot: PivotMode = PivotMode.CENTER

        # Drag state
        self._drag_origin: NDArray[np.float64] | None = None
        self._drag_object_ids: list[str] = []
        self._drag_start_poses: dict[str, Pose] = {}

    # -- Properties ---------------------------------------------------------

    @property
    def mode(self) -> TransformMode:
        return self._mode

    @mode.setter
    def mode(self, value: TransformMode) -> None:
        self._mode = value

    @property
    def pivot(self) -> PivotMode:
        return self._pivot

    @pivot.setter
    def pivot(self, value: PivotMode) -> None:
        self._pivot = value

    # -- Drag lifecycle -----------------------------------------------------

    def begin_drag(
        self,
        object_ids: list[str],
        world_origin: NDArray[np.float64],
    ) -> None:
        """Start a transform drag operation.

        Records the initial poses of all affected objects.

        Args:
            object_ids: Objects to transform.
            world_origin: Initial world-space ray intersection point.
        """
        self._drag_origin = world_origin.copy()
        self._drag_object_ids = list(object_ids)
        self._drag_start_poses = {}

        if self._scene is not None:
            for oid in object_ids:
                node = self._scene.get_node(oid)
                if node is not None:
                    pose = (
                        node.world_pose
                        if hasattr(node, "world_pose")
                        else node.transform.to_pose()
                    )
                    self._drag_start_poses[oid] = pose

    def update_drag(
        self,
        world_offset: NDArray[np.float64],
    ) -> None:
        """Apply a delta during an active drag.

        Args:
            world_offset: The cumulative world-space offset since drag start.
        """
        if self._scene is None:
            return

        # Snap the offset per-axis
        if self._snap.enabled:
            snapped_offset = self._snap.snap_vector(
                world_offset.tolist(), SnapMode.TRANSLATION
            )
            world_offset = np.array(snapped_offset, dtype=np.float64)

        for oid in self._drag_object_ids:
            start_pose = self._drag_start_poses.get(oid)
            if start_pose is None:
                continue

            # Convert offset to local space if needed
            if self._coords.is_local:
                offset = self._coords.world_to_local(world_offset, start_pose)
            else:
                offset = world_offset

            new_pos = Vec3(
                start_pose.position.x + offset[0],
                start_pose.position.y + offset[1],
                start_pose.position.z + offset[2],
            )
            self._scene.set_node_transform(oid, position=new_pos)

    def end_drag(self) -> None:
        """Complete a transform drag and create an undoable command.

        Pushes a ``TranslateCommand`` onto the command manager's stack
        for undo/redo support.
        """
        if self._scene is None or self._commands is None:
            self._reset_drag()
            return

        old_positions: list[Vec3] = []
        new_positions: list[Vec3] = []

        for oid in self._drag_object_ids:
            start_pose = self._drag_start_poses.get(oid)
            if start_pose is None:
                continue
            node = self._scene.get_node(oid)
            if node is None:
                continue
            current_pose = (
                node.world_pose
                if hasattr(node, "world_pose")
                else node.transform.to_pose()
            )
            old_positions.append(start_pose.position)
            new_positions.append(current_pose.position)

        if old_positions != new_positions:
            cmd = TranslateCommand(
                self._drag_object_ids,
                old_positions,
                new_positions,
                scene=self._scene,
            )

            try:
                task = asyncio.ensure_future(self._commands.execute(cmd))
                task.add_done_callback(
                    lambda t: (
                        _logger.exception("Command failed", exc_info=t.exception())
                        if t.exception()
                        else None
                    )
                )
            except Exception:
                _logger.exception("Failed to schedule TranslateCommand")

            if self._event_bus:
                self._event_bus.emit(
                    TransformPerformed(
                        object_ids=tuple(self._drag_object_ids),
                        mode=TransformMode.TRANSLATE,
                    )
                )

        self._reset_drag()

    def cancel_drag(self) -> None:
        """Cancel an active drag and revert to start poses."""
        if self._scene is not None:
            for oid, start_pose in self._drag_start_poses.items():
                self._scene.set_node_transform(
                    oid,
                    position=start_pose.position,
                )
        self._reset_drag()

    def _reset_drag(self) -> None:
        self._drag_origin = None
        self._drag_object_ids.clear()
        self._drag_start_poses.clear()

    # -- Quick operations ---------------------------------------------------

    def snap_rotate(self, object_id: str, axis: str, degrees: float) -> None:
        """Snap-rotate an object by a fixed angle.

        Args:
            object_id: Target object.
            axis: ``"x"``, ``"y"``, or ``"z"``.
            degrees: Rotation angle in degrees.
        """
        axis_map = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
        uv = axis_map.get(axis)
        if uv is None:
            return
        if self._scene is None:
            return
        node = self._scene.get_node(object_id)
        if node is not None and hasattr(node.transform, "rotation"):
            # axis-angle -> quaternion (w, x, y, z)
            half = np.radians(degrees) / 2.0
            s = np.sin(half)
            dq = (np.cos(half), uv[0] * s, uv[1] * s, uv[2] * s)

            # compose: result = current * delta
            cw, cx, cy, cz = node.transform.rotation
            nw = cw * dq[0] - cx * dq[1] - cy * dq[2] - cz * dq[3]
            nx = cw * dq[1] + cx * dq[0] + cy * dq[3] - cz * dq[2]
            ny = cw * dq[2] - cx * dq[3] + cy * dq[0] + cz * dq[1]
            nz = cw * dq[3] + cx * dq[2] - cy * dq[1] + cz * dq[0]
            self._scene.set_node_transform(object_id, rotation=(nw, nx, ny, nz))

    def reset_transform(self, object_id: str) -> None:
        """Reset an object's transform to identity.

        Args:
            object_id: Target object.
        """
        if self._scene is None:
            return
        self._scene.set_node_transform(
            object_id,
            position=Vec3(),
            rotation=(1.0, 0.0, 0.0, 0.0),
            scale=Vec3(1.0, 1.0, 1.0),
        )
