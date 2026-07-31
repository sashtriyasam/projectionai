# ADR-008: Treeified Scene Graph with Component-Based Nodes

## Status

Accepted

## Context

The editor and renderer both need a shared representation of a 3D scene: objects to render, cameras to view from, lights to illuminate, and materials to shade. Different subsystems (selection, transform, rendering, animation) each need to operate on the same scene data without conflicting.

Two competing designs were considered:

1. **Flat entity list** — a single array of independent entities with global transforms. Simple but makes parent/child hierarchies (e.g., a rigged object, a group of panels on a facade) painful to express.
2. **Treeified scene graph** — nodes form a parent/child tree; each node's world transform is derived from its parent's. Naturally expresses hierarchies and makes grouping trivial.

## Decision

Adopt a **treeified scene graph** in `src/projectionai/domain/scene.py`:

- `Scene` owns the root node and provides lookup (`get_node`, `find_by_name`, traversal).
- `SceneNode` holds a local `Transform` (position, rotation, scale) plus a parent/children relationship.
- Rich behavior is attached via a `Component` ABC with typed subclasses: `MeshComponent`, `MaterialComponent`, `CameraComponent`, `LightComponent`. Nodes are extensible without growing the node class itself.
- World transforms are computed by composing parent transforms — the graph is the source of truth, not cached matrices.

## Consequences

**Positive**

- Parent/child hierarchies and grouped selection come for free.
- Renderer, selection, and transform tools all consume the same structure.
- New node capabilities are added as new `Component` subclasses without touching `SceneNode`.

**Negative**

- Operations that need a flat world-space list (rendering) must traverse the tree first.
- Cycles are a hazard; mutation must go through `SceneManager` which enforces tree invariants.

## Compliance

Implemented in `src/projectionai/domain/scene.py` (`Scene`, `SceneNode`, `Transform`, `Component` hierarchy) and manipulated through `SceneManager` (`src/projectionai/managers/scene_manager.py`), which emits `NodeSelected` / `NodeTransformChanged` events on mutation.
