"""Scene manager — active scene graph management.

Owns the current scene and handles CRUD operations on the scene graph.
Integrates with the event bus to notify listeners of scene changes.
"""

from __future__ import annotations

import logging
from typing import override

from projectionai.core.events import (
    EventBus,
    NodeSelected,
    NodeTransformChanged,
    SceneActivated,
    SceneChanged,
    SceneCreated,
    SceneDeleted,
)
from projectionai.domain.scene import Scene, SceneNode, Transform
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class SceneManager(Manager):
    """Manages the active scene and scene graph operations.

    Supports multiple scenes (stored in memory) with one active scene
    at a time. All scene mutations emit events on the event bus.
    """

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self._scenes: dict[str, Scene] = {}
        self._active_scene_id: str | None = None
        self._selection: set[str] = set()  # node IDs selected in active scene

    # -- Scene lifecycle ----------------------------------------------------

    def create_scene(self, name: str = "Untitled Scene") -> Scene:
        """Create a new scene and optionally activate it.

        Args:
            name: Display name for the new scene.

        Returns:
            The newly created Scene.
        """
        self._require_initialized()
        scene = Scene(name=name)
        self._scenes[scene.id] = scene
        _logger.debug("Created scene: %s (%s)", scene.name, scene.id)
        # Emit as fire-and-forget since this is called from sync code too
        self._emit_nowait(SceneCreated(scene_id=scene.id, name=scene.name))
        return scene

    def delete_scene(self, scene_id: str) -> None:
        """Delete a scene by ID.

        If the deleted scene was active, the active scene is set to ``None``.
        """
        self._require_initialized()
        if scene_id not in self._scenes:
            return
        del self._scenes[scene_id]
        if self._active_scene_id == scene_id:
            self._active_scene_id = None
            self._selection.clear()
        self._emit_nowait(SceneDeleted(scene_id=scene_id))
        _logger.debug("Deleted scene: %s", scene_id)

    def get_scene(self, scene_id: str) -> Scene | None:
        """Return a scene by ID, or ``None``."""
        return self._scenes.get(scene_id)

    def get_all_scenes(self) -> list[Scene]:
        """Return all registered scenes."""
        return list(self._scenes.values())

    @property
    def scene_count(self) -> int:
        """Return the number of registered scenes."""
        return len(self._scenes)

    # -- Active scene -------------------------------------------------------

    @property
    def active_scene(self) -> Scene | None:
        """Return the active scene, or ``None``."""
        if self._active_scene_id is None:
            return None
        return self._scenes.get(self._active_scene_id)

    @property
    def active_scene_id(self) -> str | None:
        """Return the active scene ID."""
        return self._active_scene_id

    def activate_scene(self, scene_id: str) -> None:
        """Set the active scene by ID."""
        self._require_initialized()
        if scene_id not in self._scenes:
            raise ValueError(f"Scene {scene_id!r} not found")
        self._active_scene_id = scene_id
        self._selection.clear()
        self._emit_nowait(SceneActivated(scene_id=scene_id))
        _logger.debug("Activated scene: %s", scene_id)

    # -- Node operations (delegate to active scene) -------------------------

    def add_node(
        self,
        name: str,
        parent_id: str | None = None,
        transform: Transform | None = None,
    ) -> SceneNode:
        """Add a node to the active scene.

        Raises ``ValueError`` if there is no active scene.
        """
        self._require_initialized()
        scene = self.active_scene
        if scene is None:
            raise ValueError("No active scene")
        node = scene.add_node(name=name, parent_id=parent_id, transform=transform)
        self._emit_scene_changed()
        return node

    def remove_node(self, node_id: str) -> None:
        """Remove a node from the active scene.

        Raises ``ValueError`` if there is no active scene.
        """
        self._require_initialized()
        scene = self.active_scene
        if scene is None:
            raise ValueError("No active scene")
        self._selection.discard(node_id)
        scene.remove_node(node_id)
        self._emit_scene_changed()

    def reparent_node(self, node_id: str, new_parent_id: str) -> None:
        """Reparent a node in the active scene.

        Raises ``ValueError`` if no active scene or cycle detected.
        """
        self._require_initialized()
        scene = self.active_scene
        if scene is None:
            raise ValueError("No active scene")
        scene.reparent_node(node_id, new_parent_id)
        self._emit_scene_changed()

    def get_node(self, node_id: str) -> SceneNode | None:
        """Get a node from the active scene."""
        scene = self.active_scene
        if scene is None:
            return None
        return scene.get_node(node_id)

    def get_root_node(self) -> SceneNode | None:
        """Return the root node of the active scene."""
        scene = self.active_scene
        if scene is None:
            return None
        return scene.get_root_node()

    def find_node_by_name(self, name: str) -> SceneNode | None:
        """Find a node by name in the active scene."""
        scene = self.active_scene
        if scene is None:
            return None
        return scene.find_node_by_name(name)

    def find_nodes_by_tag(self, tag: str) -> list[SceneNode]:
        """Find nodes by tag in the active scene."""
        scene = self.active_scene
        if scene is None:
            return []
        return scene.find_nodes_by_tag(tag)

    def set_node_transform(self, node_id: str, transform: Transform) -> None:
        """Update a node's transform in the active scene."""
        self._require_initialized()
        scene = self.active_scene
        if scene is None:
            raise ValueError("No active scene")
        _ = scene.set_node_transform(node_id, transform)
        self._emit_nowait(NodeTransformChanged(scene_id=scene.id, node_id=node_id))
        self._emit_scene_changed()

    # -- Selection ----------------------------------------------------------

    @property
    def selection(self) -> set[str]:
        """Return the set of selected node IDs in the active scene."""
        return set(self._selection)

    def select_node(self, node_id: str) -> None:
        """Add a node to the selection."""
        scene = self.active_scene
        if scene is None:
            return
        node = scene.get_node(node_id)
        if node is None:
            return
        node.selected = True
        self._selection.add(node_id)
        self._emit_nowait(
            NodeSelected(scene_id=scene.id, node_id=node_id, selected=True)
        )

    def deselect_node(self, node_id: str) -> None:
        """Remove a node from the selection."""
        scene = self.active_scene
        if scene is None:
            return
        node = scene.get_node(node_id)
        if node is not None:
            node.selected = False
        self._selection.discard(node_id)
        self._emit_nowait(
            NodeSelected(scene_id=scene.id, node_id=node_id, selected=False)
        )

    def clear_selection(self) -> None:
        """Clear the entire selection."""
        scene = self.active_scene
        if scene is not None:
            for nid in list(self._selection):
                node = scene.get_node(nid)
                if node is not None:
                    node.selected = False
                self._emit_nowait(
                    NodeSelected(scene_id=scene.id, node_id=nid, selected=False)
                )
        self._selection.clear()

    # -- Internal -----------------------------------------------------------

    def _emit_scene_changed(self) -> None:
        """Emit a generic scene-changed event for the active scene."""
        scene = self.active_scene
        if scene is not None:
            self._emit_nowait(SceneChanged(scene_id=scene.id))

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        # Create a default scene on first launch.
        # ``Manager.initialize`` sets ``_initialized`` before calling this
        # hook, so ``create_scene()`` (which calls ``_require_initialized``)
        # is safe to use here.
        if not self._scenes:
            scene = self.create_scene("Default Scene")
            self.activate_scene(scene.id)

    @override
    async def _on_shutdown(self) -> None:
        self._scenes.clear()
        self._active_scene_id = None
        self._selection.clear()
