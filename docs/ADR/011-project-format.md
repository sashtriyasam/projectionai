# ADR-011: Directory-Based Project Format (`.projectai`)

## Status

Accepted

## Context

Projects must persist scenes, imported assets, and thumbnails in a way that survives restarts and is easy to reason about. A single opaque binary blob is hard to debug and hostile to incremental saves; a full database is heavyweight for a desktop tool.

## Decision

Store each project as a **`.projectai` directory** with a predictable layout:

```
my_project.projectai/
├── project.json         # Manifest: name, id, metadata, settings
├── scenes/
│   └── {scene_id}.json  # Per-scene serialized scene graph
├── assets/
│   └── {asset_id}.ext   # Imported asset files
└── thumbnails/
    └── {asset_id}.png   # Preview thumbnails
```

- The manifest (`project.json`) holds project-level metadata and settings via the domain `Project` model (`src/projectionai/domain/project.py`).
- Scenes serialize to individual JSON files so one scene can be saved without rewriting the whole project.
- Asset files are copied into the project directory, making projects self-contained and portable.
- `ProjectManager` (`src/projectionai/managers/project_manager.py`) owns lifecycle (create/open/save/close), dirty tracking, and emits `ProjectSaved` / `ProjectModified` events.

## Consequences

**Positive**

- Human-readable and debuggable on disk.
- Incremental saves and partial project recovery.
- Portable: copy the directory to share a project.

**Negative**

- Directory juggling (ensure dirs exist, handle partial writes) is the app's responsibility.
- Not a queryable database — fine for a desktop tool, a limitation if we later need cross-project search at scale.

## Compliance

Implemented in `src/projectionai/domain/project.py` (models) and `src/projectionai/managers/project_manager.py` (lifecycle + persistence), with serialization in the persistence infrastructure layer. Tested in `tests/unit/test_project_manager.py`.
