"""Scene graph model — hierarchical scene representation.

The scene graph is a tree of ``SceneNode`` objects. Each node has a
transform, a list of components, tags, and custom properties. The root
node represents the world origin. Every renderable entity is a child
of the root or another node.

Design decisions:
- Components are stored as a dict keyed by a ``ComponentType`` string,
  so new component types can be added without changing the scene graph.
- The tree structure uses parent/child ID references (not object references)
  to simplify serialization and avoid circular references.
- Transforms are local to the parent; world transforms are computed
  on traversal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast, override
from uuid import uuid4

from projectionai.domain.geometry import BoundingBox, Pose, Vec3

# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------


@dataclass
class Transform:
    """Local transform relative to the parent node.

    Stored as position (translation), rotation (quaternion), and scale.
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)  # w, x, y, z
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @staticmethod
    def identity() -> Transform:
        """Return an identity transform."""
        return Transform()

    def to_pose(self) -> Pose:
        """Convert to a Pose object (for compatibility with geometry module)."""
        return Pose(
            position=Vec3(*self.position),
            rotation=self.rotation,
        )


# ---------------------------------------------------------------------------
# Component type enumeration
# ---------------------------------------------------------------------------


class ComponentType(StrEnum):
    """Well-known component types.

    Components attach behaviour to scene nodes. A node can have at most
    one component of each type.
    """

    MESH = "mesh"
    MATERIAL = "material"
    CAMERA = "camera"
    LIGHT = "light"
    SURFACE = "surface"
    CALIBRATION = "calibration"
    AUDIO = "audio"
    ANIMATION = "animation"
    METADATA = "metadata"


# ---------------------------------------------------------------------------
# Component base
# ---------------------------------------------------------------------------


class Component(ABC):
    """Base class for all scene graph components.

    Subclass this and register with a unique ``type`` value to extend
    node behaviour. Components are value objects — they are replaced,
    not mutated.
    """

    @property
    @abstractmethod
    def component_type(self) -> ComponentType:
        """Return the component type identifier."""


# ---------------------------------------------------------------------------
# Pre-defined components
# ---------------------------------------------------------------------------


@dataclass
class MeshComponent(Component):
    """Reference to a mesh asset attached to this node."""

    asset_id: str = ""

    @property
    @override
    def component_type(self) -> ComponentType:
        return ComponentType.MESH


@dataclass
class MaterialComponent(Component):
    """Reference to a material asset attached to this node."""

    asset_id: str = ""

    @property
    @override
    def component_type(self) -> ComponentType:
        return ComponentType.MATERIAL


@dataclass
class CameraComponent(Component):
    """Camera component for viewport and projection rendering."""

    fov_degrees: float = 60.0
    near_plane: float = 0.01
    far_plane: float = 100.0
    is_active: bool = False

    @property
    @override
    def component_type(self) -> ComponentType:
        return ComponentType.CAMERA


@dataclass
class LightComponent(Component):
    """Light source attached to a node."""

    light_type: str = "point"  # point, directional, spot
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    range: float = 10.0

    @property
    @override
    def component_type(self) -> ComponentType:
        return ComponentType.LIGHT


# ---------------------------------------------------------------------------
# Scene node
# ---------------------------------------------------------------------------


@dataclass
class SceneNode:
    """A single node in the scene graph.

    Each node has a local transform, a list of child IDs (ordered),
    components, tags, and custom properties.

    Nodes form a tree through ``parent_id`` and ``children`` references.
    The root node has ``parent_id=None``.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Node"
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)

    transform: Transform = field(default_factory=Transform)
    components: dict[ComponentType, Component] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)
    custom_properties: dict[str, object] = field(default_factory=dict)

    visible: bool = True
    locked: bool = False
    selected: bool = False


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


@dataclass
class Scene:
    """A scene holds a tree of SceneNode objects.

    The root node is an invisible world-origin node created automatically.
    All user-created nodes are children of the root (or deeper in the tree).
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Untitled Scene"
    description: str = ""

    root_node_id: str = field(default_factory=lambda: uuid4().hex)
    nodes: dict[str, SceneNode] = field(default_factory=dict)

    bounding_box: BoundingBox | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Ensure the root node exists."""
        if self.root_node_id not in self.nodes:
            root = SceneNode(
                id=self.root_node_id,
                name="Scene Root",
                parent_id=None,
                visible=True,
                locked=True,
            )
            self.nodes[self.root_node_id] = root

    # -- Node operations ----------------------------------------------------

    def add_node(
        self,
        name: str,
        parent_id: str | None = None,
        transform: Transform | None = None,
    ) -> SceneNode:
        """Create and add a new node to the scene.

        Args:
            name: Display name for the node.
            parent_id: Parent node ID. ``None`` = attach to root.
            transform: Local transform. Defaults to identity.

        Returns:
            The newly created node.
        """
        parent_id = parent_id or self.root_node_id
        if parent_id not in self.nodes:
            parent_id = self.root_node_id

        node = SceneNode(
            name=name,
            parent_id=parent_id,
            transform=transform or Transform.identity(),
        )
        self.nodes[node.id] = node
        self.nodes[parent_id].children.append(node.id)
        self.touch()
        return node

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its descendants from the scene."""
        if node_id == self.root_node_id:
            raise ValueError("Cannot remove the root node")

        node = self.nodes.get(node_id)
        if node is None:
            return

        # Collect all descendant IDs
        to_remove = self._collect_descendants(node_id)

        # Remove from parent's children list
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            parent.children = [c for c in parent.children if c != node_id]

        # Delete all nodes in the subtree
        for nid in to_remove:
            _ = self.nodes.pop(nid, None)

        self.touch()

    def reparent_node(self, node_id: str, new_parent_id: str) -> None:
        """Move a node to a new parent.

        Raises ``ValueError`` if *new_parent_id* is a descendant of
        *node_id* (would create a cycle).
        """
        if node_id == self.root_node_id:
            raise ValueError("Cannot reparent the root node")
        if node_id == new_parent_id:
            return
        if new_parent_id in self._collect_descendants(node_id):
            raise ValueError("Cannot reparent a node to its own descendant")

        node = self.nodes.get(node_id)
        if node is None:
            return
        new_parent = self.nodes.get(new_parent_id)
        if new_parent is None:
            return

        # Remove from old parent
        if node.parent_id and node.parent_id in self.nodes:
            old_parent = self.nodes[node.parent_id]
            old_parent.children = [c for c in old_parent.children if c != node_id]

        # Add to new parent
        node.parent_id = new_parent_id
        new_parent.children.append(node_id)
        self.touch()

    def set_node_transform(self, node_id: str, transform: Transform) -> SceneNode:
        """Update a node's transform and bump the scene timestamp.

        Raises ``ValueError`` if *node_id* is not found.
        """
        node = self.get_node(node_id)
        if node is None:
            raise ValueError(f"Node {node_id!r} not found")
        node.transform = transform
        self.touch()
        return node

    def get_node(self, node_id: str) -> SceneNode | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_root_node(self) -> SceneNode:
        """Return the root node."""
        return self.nodes[self.root_node_id]

    def find_node_by_name(self, name: str) -> SceneNode | None:
        """Find the first node with the given name (breadth-first)."""
        from collections import deque

        queue = deque([self.root_node_id])
        while queue:
            nid = queue.popleft()
            node = self.nodes.get(nid)
            if node is None:
                continue
            if node.name == name:
                return node
            queue.extend(node.children)
        return None

    def find_nodes_by_tag(self, tag: str) -> list[SceneNode]:
        """Return all nodes with the given tag."""
        return [n for n in self.nodes.values() if tag in n.tags]

    # -- Hierarchy queries --------------------------------------------------

    def get_children(self, node_id: str) -> list[SceneNode]:
        """Return the direct children of *node_id*."""
        node = self.nodes.get(node_id)
        if node is None:
            return []
        return [self.nodes[cid] for cid in node.children if cid in self.nodes]

    def get_parent(self, node_id: str) -> SceneNode | None:
        """Return the parent of *node_id*, or ``None`` for root."""
        node = self.nodes.get(node_id)
        if node is None or node.parent_id is None:
            return None
        return self.nodes.get(node.parent_id)

    def get_ancestors(self, node_id: str) -> list[SceneNode]:
        """Return the ancestor chain from root to parent of *node_id*."""
        ancestors: list[SceneNode] = []
        node = self.nodes.get(node_id)
        if node is None:
            return ancestors
        current_id = node.parent_id
        while current_id is not None and current_id in self.nodes:
            current = self.nodes[current_id]
            ancestors.insert(0, current)
            current_id = current.parent_id
        return ancestors

    def get_node_path(self, node_id: str) -> list[str]:
        """Return node IDs from root to the given node (inclusive)."""
        path: list[str] = []
        node = self.nodes.get(node_id)
        if node is None:
            return path
        current_id: str | None = node_id
        while current_id is not None and current_id in self.nodes:
            path.insert(0, current_id)
            current_id = self.nodes[current_id].parent_id
        return path

    def is_descendant_of(self, node_id: str, ancestor_id: str) -> bool:
        """Return ``True`` if *node_id* is a descendant of *ancestor_id*."""
        ancestors = self.get_ancestors(node_id)
        return any(n.id == ancestor_id for n in ancestors)

    def count_nodes(self) -> int:
        """Return the total number of nodes (including root)."""
        return len(self.nodes)

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Serialize scene to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "root_node_id": self.root_node_id,
            "nodes": {
                nid: {
                    "id": node.id,
                    "name": node.name,
                    "parent_id": node.parent_id,
                    "children": list(node.children),
                    "transform": {
                        "position": list(node.transform.position),
                        "rotation": list(node.transform.rotation),
                        "scale": list(node.transform.scale),
                    },
                    "components": {
                        ct.value: _component_to_dict(comp)
                        for ct, comp in node.components.items()
                    },
                    "tags": sorted(node.tags),
                    "custom_properties": dict(node.custom_properties),
                    "visible": node.visible,
                    "locked": node.locked,
                    "selected": node.selected,
                }
                for nid, node in self.nodes.items()
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> Scene:
        """Deserialize a scene from a dict."""
        from datetime import datetime

        nodes: dict[str, SceneNode] = {}
        raw_nodes = cast("dict[str, dict[str, object]]", data.get("nodes", {}))
        for nid, ndata in raw_nodes.items():
            tdata = cast("dict[str, object]", ndata.get("transform", {}))
            pos = cast(
                "tuple[float, float, float]", tdata.get("position", (0.0, 0.0, 0.0))
            )
            rot = cast(
                "tuple[float, float, float, float]",
                tdata.get("rotation", (1.0, 0.0, 0.0, 0.0)),
            )
            scl = cast(
                "tuple[float, float, float]", tdata.get("scale", (1.0, 1.0, 1.0))
            )
            transform = Transform(
                position=tuple(pos),  # type: ignore[arg-type]
                rotation=tuple(rot),  # type: ignore[arg-type]
                scale=tuple(scl),  # type: ignore[arg-type]
            )
            raw_comp = cast("dict[str, dict[str, object]]", ndata.get("components", {}))
            components: dict[ComponentType, Component] = {
                ComponentType(ct): _component_from_dict(ct, cdata)
                for ct, cdata in raw_comp.items()
            }
            nodes[nid] = SceneNode(
                id=cast("str", ndata.get("id", nid)),
                name=cast("str", ndata.get("name", "Node")),
                parent_id=cast("str | None", ndata.get("parent_id")),
                children=cast("list[str]", ndata.get("children", [])),
                transform=transform,
                components=components,
                tags=set(cast("list[str]", ndata.get("tags", []))),
                custom_properties=cast(
                    "dict[str, object]", ndata.get("custom_properties", {})
                ),
                visible=cast("bool", ndata.get("visible", True)),
                locked=cast("bool", ndata.get("locked", False)),
                selected=cast("bool", ndata.get("selected", False)),
            )

        scene = Scene(
            id=cast("str", data.get("id", "")),
            name=cast("str", data.get("name", "Untitled Scene")),
            description=cast("str", data.get("description", "")),
            root_node_id=cast("str", data.get("root_node_id", "")),
            nodes=nodes,
        )
        created = data.get("created_at")
        updated = data.get("updated_at")
        if isinstance(created, str):
            scene.created_at = datetime.fromisoformat(created)
        if isinstance(updated, str):
            scene.updated_at = datetime.fromisoformat(updated)
        return scene

    # -- Internal ------------------------------------------------------------

    def _collect_descendants(self, node_id: str) -> list[str]:
        """Return all descendant node IDs including *node_id*."""
        result: list[str] = []
        stack = [node_id]
        while stack:
            nid = stack.pop()
            result.append(nid)
            node = self.nodes.get(nid)
            if node:
                stack.extend(node.children)
        return result

    def touch(self) -> None:
        """Mark the scene as recently modified by bumping ``updated_at``."""
        self.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _component_to_dict(component: Component) -> dict[str, object]:
    """Serialize a component to a JSON-compatible dict."""
    import dataclasses
    from dataclasses import asdict

    base: dict[str, object] = {"type": component.component_type.value}
    if dataclasses.is_dataclass(component):
        merged: dict[str, object] = cast("dict[str, object]", asdict(component))
        result = base | merged
    else:
        result = base
    return result


def _component_from_dict(comp_type: str, data: dict[str, object]) -> Component:
    """Deserialize a component from a dict."""
    ct = ComponentType(comp_type)
    factory_map: dict[ComponentType, type[Component]] = {
        ComponentType.MESH: MeshComponent,
        ComponentType.MATERIAL: MaterialComponent,
        ComponentType.CAMERA: CameraComponent,
        ComponentType.LIGHT: LightComponent,
    }
    cls = factory_map.get(ct)
    if cls is None:
        # For unknown component types, return a generic stub
        class _UnknownComponent(Component):
            @property
            @override
            def component_type(self) -> ComponentType:
                return ct

        return _UnknownComponent()
    # Remove type key before passing to dataclass constructor
    kwargs = {k: v for k, v in data.items() if k != "type"}
    return cls(**kwargs)
