"""ScenesViewModel — scenes list + scene-graph tree for the left panel.

Qt-free. Wraps :class:`SceneManager` and exposes snapshot methods the
Scenes & Graph panel renders; mutations go through the manager so
events stay on the event bus.
"""

from __future__ import annotations

from projectionai.domain.scene import Scene, SceneNode
from projectionai.managers.scene_manager import SceneManager
from projectionai.ui.viewmodels.observable import Observable


class ScenesViewModel(Observable):
    """Observable scene-management facade."""

    def __init__(self, scene_manager: SceneManager) -> None:
        super().__init__()
        self._scenes = scene_manager

    # -- Scenes ---------------------------------------------------------------

    def scenes(self) -> list[Scene]:
        """All registered scenes."""
        return self._scenes.get_all_scenes()

    @property
    def scene_count(self) -> int:
        """Number of registered scenes."""
        return self._scenes.scene_count

    def active_scene(self) -> Scene | None:
        """The active scene, or ``None``."""
        return self._scenes.active_scene

    def create_scene(self, name: str = "Untitled Scene") -> Scene:
        """Create and activate a new scene."""
        scene = self._scenes.create_scene(name)
        self._notify()
        return scene

    def delete_scene(self, scene_id: str) -> bool:
        """Delete a scene by id; returns ``True`` on success."""
        if self._scenes.get_scene(scene_id) is None:
            return False
        self._scenes.delete_scene(scene_id)
        self._notify()
        return True

    def activate_scene(self, scene_id: str) -> bool:
        """Switch the active scene by id; returns ``True`` on success."""
        try:
            self._scenes.activate_scene(scene_id)
        except ValueError:
            return False
        self._notify()
        return True

    # -- Scene graph ----------------------------------------------------------

    def node(self, node_id: str) -> SceneNode | None:
        """Return a node from the active scene, or ``None``."""
        return self._scenes.get_node(node_id)

    def root_id(self) -> str | None:
        """Id of the active scene's root node, or ``None``."""
        root = self._scenes.get_root_node()
        return root.id if root is not None else None

    def children_of(self, node_id: str) -> list[SceneNode]:
        """Direct children of *node_id* in the active scene."""
        scene = self._scenes.active_scene
        if scene is None:
            return []
        return scene.get_children(node_id)

    def add_node(self, name: str, parent_id: str | None = None) -> SceneNode | None:
        """Add a node to the active scene; returns it, or ``None``."""
        try:
            node = self._scenes.add_node(name, parent_id=parent_id)
        except ValueError:
            return None
        self._notify()
        return node

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the active scene; returns ``True`` on success."""
        scene = self._scenes.active_scene
        if scene is None or scene.get_node(node_id) is None:
            return False
        try:
            self._scenes.remove_node(node_id)
        except ValueError:
            return False
        self._notify()
        return True

    def reparent_node(self, node_id: str, new_parent_id: str) -> None:
        """Move a node under *new_parent_id* in the active scene."""
        try:
            self._scenes.reparent_node(node_id, new_parent_id)
        except ValueError:
            return
        self._notify()

    # -- Selection ------------------------------------------------------------

    def selection(self) -> set[str]:
        """Ids of the selected nodes in the active scene."""
        return self._scenes.selection

    def select(self, node_id: str) -> None:
        """Add a node to the selection."""
        self._scenes.select_node(node_id)
        self._notify()

    def deselect(self, node_id: str) -> None:
        """Remove a node from the selection."""
        self._scenes.deselect_node(node_id)
        self._notify()

    def clear_selection(self) -> None:
        """Clear the entire selection."""
        self._scenes.clear_selection()
        self._notify()
