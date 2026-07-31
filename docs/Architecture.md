# Architecture

> Architecture Decision Records (ADRs) are in [docs/ADR/](ADR/) — see ADR-007 for the domain-driven structure, ADR-006 for the event bus, and ADR-005 for the render pipeline.

## Design Principles

- **Parse, don't validate** — types guarantee invariants; validation happens at boundaries
- **Typed errors** — recoverable failures use typed exception hierarchy; unexpected failures crash with full traceback
- **Dependency inversion** — domain defines interfaces; infrastructure implements them
- **Isolated state** — each manager owns its state; communication happens via events
- **Testability** — pure domain logic, swappable infrastructure via service interfaces

## Overview

ProjectionAI follows **Clean Architecture** with strict dependency direction:

```
UI → Application → Domain
                       ↕
Services (interfaces) ← Infrastructure (implementations)

            ┌──────────────────────────────────┐
            │           Manager Layer          │
            │  Settings · Plugin · Command ·   │
            │  Scene · Asset · Job · Project · │
            │  Workspace                       │
            ├──────────────────────────────────┤
            │           Event Bus              │
            └──────────────────────────────────┘
```

- **Domain** at the center — pure Python, zero dependencies on frameworks
- **Services** define interfaces (Protocols + ABCs) that the domain depends on
- **Infrastructure** implements those interfaces — this is where the framework code lives
- **Application** orchestrates workflows using domain models and service interfaces
- **Manager layer** provides the operational framework: lifecycle, undo/redo, background jobs, project management, asset tracking, scene manipulation, and settings persistence
- **Event Bus** decouples all layers — managers communicate by emitting/receiving typed events
- **UI** is a thin presentation layer using MVVM

## Layer Responsibilities

### Core (`src/projectionai/core/`)

Shared framework utilities that every layer may use.

| Module       | Responsibility                                                      |
| ------------ | ------------------------------------------------------------------- |
| `base.py`    | ABCs, Protocols, `Result[Ok, Error]` type, `Service` lifecycle base |
| `plugin.py`  | Capability-based plugin registry, discovery, lifecycle management   |
| `events.py`  | Typed event bus with weak references and async dispatch             |
| `config.py`  | Pydantic-settings configuration with layered loading                |
| `logging.py` | Structured logging (console + rotating file, JSON format)           |
| `errors.py`  | Complete exception hierarchy rooted at `ProjectionAIError`          |

### Domain (`src/projectionai/domain/`)

Pure business entities. No UI, no infrastructure, no framework imports.

| Module           | Responsibility                                                          |
| ---------------- | ----------------------------------------------------------------------- |
| `geometry.py`    | `Vec3`, `Pose`, `Mesh`, `PointCloud`, `BoundingBox`                     |
| `surface.py`     | `ProjectionSurface`, `SurfaceType` enum, `SurfaceDetectionResult`       |
| `calibration.py` | `CalibrationPoint`, `CalibrationResult`, `ProjectorCalibration`         |
| `scene.py`       | `Scene`, `SceneNode`, `Transform`, `Component` types (full scene graph) |
| `project.py`     | `Project`, `ProjectMetadata`, `ProjectSettings`, `HistoryEntry`         |
| `asset.py`       | `Asset`, `AssetType`, `AssetDependency`, `ThumbnailInfo`                |
| `job.py`         | `Job` ABC, `JobStatus`, `JobPriority`, `ProgressCallback`               |
| `command.py`     | `Command` ABC, `CommandGroup`, `CommandHistory` (undo/redo stacks)      |
| `workspace.py`   | `WorkspaceLayout`, `PanelState`, `WorkspaceSettings`                    |
| `material.py`    | `ProjectedContent`, `ContentType`, `Material`                           |

### Manager Layer (`src/projectionai/managers/`)

The manager layer is the operational heart of the application. Each manager owns a single concern and communicates via events.

| Manager            | Responsibility                                                   | Events Emitted                                                                           |
| ------------------ | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `SettingsManager`  | Pydantic-typed settings with per-category mutation & persistence | `SettingsChanged`                                                                        |
| `PluginManager`    | Capability-based plugin lifecycle (discovery → load → shutdown)  | `PluginLoaded`, `PluginUnloaded`, `PluginError`                                          |
| `CommandManager`   | Undo/redo command stack with transaction support                 | `CommandExecuted`, `CommandUndone`, `CommandRedone`, `CommandHistoryCleared`             |
| `SceneManager`     | Multi-scene graph management, node CRUD, selection tracking      | `SceneCreated`, `SceneActivated`, `SceneChanged`, `NodeSelected`, `NodeTransformChanged` |
| `AssetManager`     | In-memory asset database with dependency graph and search        | `AssetImported`, `AssetDeleted`, `AssetUpdated`                                          |
| `JobManager`       | Background thread pool job queue with priority, progress, cancel | `JobQueued`, `JobStarted`, `JobProgress`, `JobCompleted`, `JobFailed`, `JobCancelled`    |
| `ProjectManager`   | Project lifecycle (create/open/save/close), recent-projects list | `ProjectCreated`, `ProjectOpened`, `ProjectSaved`, `ProjectClosed`, `ProjectModified`    |
| `WorkspaceManager` | UI layout/panel state management with persistence                | `WorkspaceLayoutChanged`, `WorkspaceSettingsChanged`                                     |

All managers extend the `Manager` ABC from `managers/__init__.py`, which provides:

- `initialize()` / `shutdown()` lifecycle with `_require_initialized()` guard
- Self-registration in the global `ManagerRegistry`
- Typed convenience accessors via `registry.get("name")`

### Services (`src/projectionai/services/`)

Abstract interfaces (Protocols and ABCs) that define what the application needs
from the outside world. These are **stable** — they change rarely.

| Module                  | Interface                             | Methods                                                                            |
| ----------------------- | ------------------------------------- | ---------------------------------------------------------------------------------- |
| `vision.py`             | `VisionPipeline`                      | `process_frame`, `detect_surfaces`, `estimate_pose`, `compute_calibration`         |
| `ai.py`                 | `AIProvider`                          | `generate`, `chat`, `generate_stream`, `chat_stream`                               |
| `renderer.py`           | `Renderer`, `WarpEngine`              | `render`, `render_offscreen`, `warp`                                               |
| `calibration.py`        | `Calibrator`                          | `start_calibration`, `add_correspondence`, `compute_calibration`, `auto_calibrate` |
| `camera_calibration.py` | `CameraCalibrationAlgorithm`          | `detect`, `calibrate`                                                              |
| `storage.py`            | `StorageService`, `ProjectRepository` | `save`, `load`, `delete`, `list_projects`                                          |

### Infrastructure (`src/projectionai/infrastructure/`)

Concrete implementations of service interfaces. Swappable.

| Module                          | Implements                   | Technology            |
| ------------------------------- | ---------------------------- | --------------------- |
| `ai/gemini.py`                  | `AIProvider`                 | Google Gemini API     |
| `ai/openai_provider.py`         | `AIProvider`                 | OpenAI API            |
| `ai/anthropic.py`               | `AIProvider`                 | Anthropic API         |
| `ai/replicate.py`               | `AIProvider`                 | Replicate API         |
| `vision/opencv_pipeline.py`     | `VisionPipeline`             | OpenCV                |
| `renderer/moderngl_renderer.py` | `Renderer`, `WarpEngine`     | ModernGL              |
| `calibration/manual.py`         | `Calibrator`                 | Point correspondences |
| `calibration/automatic.py`      | `Calibrator`                 | ICP (Open3D)          |
| `calibration/chessboard.py`     | `CameraCalibrationAlgorithm` | OpenCV checkerboard   |
| `persistence/database.py`       | `StorageService`             | SQLite via aiosqlite  |

### Application (`src/projectionai/application/`)

Use-case orchestrators. Each workflow is a class that takes service interfaces
via dependency injection and orchestrates a multi-step operation.

- `scan_workflow.py` — Camera → VisionPipeline → Scene object
- `generate_workflow.py` — Text prompt → AIProvider → ProjectedContent
- `warp_workflow.py` — Content + Surface → WarpEngine → Warped texture
- `preview_workflow.py` — Scene → Renderer → Viewport
- `project_workflow.py` — Project CRUD, import/export

### UI (`src/projectionai/ui/`)

PySide6 desktop UI following the **MVVM** pattern:

```
View (PySide6 widget) ↔ ViewModel (state + commands) ↔ Application/use cases
```

- Views are thin: they bind to ViewModel properties and emit user actions
- ViewModels hold all state and orchestrate application use cases
- ViewModels are testable without Qt (no QWidget dependency)

### Editor (`src/projectionai/editor/`)

Qt-free viewport interaction layer (testable without a GL context):

- `viewport_controller.py` — per-frame view state (zoom, pan), calibration status/detection API; emits `ViewportDirty` on changes
- `calibration_overlay.py` — pure-numpy geometry (line vertices/colors) for detected board corners + calibration status text; revision counter gates per-frame sync
- `overlay_renderer.py` — owns renderer-side overlay state; exposes the calibration overlay
- `viewport_widget.py` — PySide6 viewport; async handlers for core calibration events (`CalibrationStarted/Progress/Complete/Failed`); syncs overlay geometry to the renderer's `OverlayPass` each frame only when the overlay revision changed

The renderer's `OverlayPass` draws calibration corner lines (`LINES` primitives) through the shared overlay shader using the viewport size uniform.

## Manager Wiring (`app.py`)

The `Application` class in `app.py` wires all managers in dependency-safe order:

1. **EventBus** — always ready
2. **SettingsManager** + **PluginManager** — no dependencies
3. **CommandManager** + **JobManager** — depend on event bus only
4. **SceneManager** + **AssetManager** — domain managers
5. **ProjectManager** + **WorkspaceManager** — top-level managers
6. Infrastructure services — storage, AI, vision, renderer, calibrator

Managers are accessed via the `ManagerRegistry`:

```python
app = Application(config)
await app.initialize()

# Via registry
scene_mgr = app.managers.get("scenes")

# Via shortcut properties
app.scenes  # SceneManager
app.project  # ProjectManager
app.jobs  # JobManager
```

## Capability-Based Plugin System

Every external extension is a **plugin** declaring _capabilities_ they support
(rather than being classified by provider name):

```
Plugins declare capabilities:  "llm_provider", "image_generator",
                                "depth_estimator", "segmenter",
                                "renderer", "audio_provider",
                                "calibration_provider"

Capability protocols:  LLMProvider, ImageGenerator, DepthEstimator,
                       Segmenter, Renderer, AudioProvider,
                       CalibrationProvider
```

**Usage:**

```python
registry = get_registry()
for plugin in registry.get_by_capability("llm_provider"):
    result = await plugin.generate("prompt")
```

**Discovery chain:**

1. `PluginRegistry.discover_entry_points()` — scans installed packages for entry point `projectionai.plugins`
2. `PluginRegistry.discover_package()` — scans a directory for Python modules exposing `create_plugin()`
3. `PluginManager` wraps the registry with event bus integration

**Adding a new provider:**

1. Create `infrastructure/ai/my_provider.py`
2. Implement the relevant capability protocol
3. Create a `PluginDescriptor` and register it
4. Add API key to `.env.example` and `config.py`
5. Add optional dependency group to `pyproject.toml`

## Event System

The event bus enables decoupled communication between managers and UI:

```python
# Emitting
await event_bus.emit(SceneChanged(scene_id="abc"))

# Listening
@event_bus.on(SceneChanged)
async def on_scene_changed(event: SceneChanged):
    status_bar.show(f"Scene updated: {event.scene_id}")
```

Key properties:

- **Typed events** — every event is a frozen dataclass
- **40+ event types** covering all manager operations
- **Weak references** — UI listeners don't prevent garbage collection
- **Async dispatch** — listeners run concurrently via `asyncio.gather`
- **Error isolation** — one failing listener doesn't block others

## Configuration

Layered configuration (later overrides earlier):

| Layer               | Source       | Example                                               |
| ------------------- | ------------ | ----------------------------------------------------- |
| 1. Defaults         | Code         | `ai_provider: str = "gemini"`                         |
| 2. `.env` file      | Project root | `PROJECTIONAI_AI_PROVIDER=openai`                     |
| 3. Environment vars | System       | `PROJECTIONAI_AI_PROVIDER=anthropic` (overrides .env) |

Settings are strongly typed using Pydantic sub-models managed by `SettingsManager`:

| Category    | Sub-model                | Fields (examples)                                  |
| ----------- | ------------------------ | -------------------------------------------------- |
| Scene       | `SceneSettings`          | default_node_scale, unit_scale                     |
| Rendering   | `RenderingSettings`      | resolution, framerate, color_space, vsync          |
| Calibration | `CalibrationSettings`    | checkerboard_size, max_reprojection_error          |
| Workspace   | `WorkspaceSettingsModel` | restore_last_layout, auto_save                     |
| Job         | `JobSettings`            | max_concurrent, queue_capacity, log_retention_days |

## Error Handling

All application exceptions inherit from `ProjectionAIError`:

```
ProjectionAIError
├── ConfigurationError
├── DomainError
│   ├── InvalidSceneError
│   ├── CalibrationError
│   ├── SceneNodeNotFoundError
│   └── InvalidSceneOperationError
├── ManagerError
│   ├── ManagerNotInitializedError
│   └── ManagerStateError
├── CommandError
│   ├── CommandExecutionError
│   ├── CommandValidationError
│   └── CommandHistoryEmptyError
├── JobError
│   ├── JobExecutionError
│   ├── JobCancelledError
│   ├── JobNotFoundError
│   └── JobQueueFullError
├── AssetError
│   ├── AssetNotFoundError
│   ├── AssetImportError
│   ├── AssetExportError
│   └── AssetDuplicateError
├── ProjectError
│   ├── ProjectNotFoundError
│   ├── ProjectFormatError
│   ├── ProjectSaveError
│   └── ProjectLoadError
├── ServiceError
│   ├── VisionError
│   ├── RendererError
│   └── StorageError
├── AIProviderError
│   ├── AIProviderTimeoutError
│   ├── AIProviderRateLimitError
│   └── AIProviderContentFilteredError
└── PluginError
    ├── PluginNotFoundError
    ├── PluginLoadError
    ├── PluginConflictError
    └── PluginCapabilityError
```

- UI layer catches `ProjectionAIError` → user-friendly toast notification
- Unexpected exceptions (`Exception`) → logged with full traceback → generic error dialog
- AI provider errors include retry policies (exponential backoff for rate limits)

## Logging

- **Structured JSON output** for production log aggregation
- **Console** with colored formatting in development mode
- **Rotating file** (10 MB, 5 backups) in platform-appropriate directory
- Per-module loggers via standard `logging.getLogger(__name__)`
- Quietened third-party libraries (PIL, httpx, openai, anthropic, google) at WARNING

## Project Format (`.projectai`)

Projects are stored as `.projectai` directories:

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

The API abstracts over the internal structure — consumers work with `Project`, `Scene`, and `Asset` objects.

## Future Extension Points

| Extension                  | Mechanism                              | Location                             |
| -------------------------- | -------------------------------------- | ------------------------------------ |
| New AI provider            | Plugin system + capability descriptor  | `infrastructure/ai/`                 |
| New renderer               | Implement `Renderer` ABC               | `infrastructure/renderer/`           |
| New vision algorithm       | Extend or replace `VisionPipeline`     | `infrastructure/vision/`             |
| New calibration method     | Implement `Calibrator` ABC             | `infrastructure/calibration/`        |
| Multi-projector            | Add `ProjectorCalibration` to scene    | Existing data model                  |
| Collaborative editing      | Event bus over WebSocket               | Future: `application/collaboration/` |
| Hardware projector control | New `infrastructure/hardware/` package | Future                               |
| MIDI/DMX control           | Plugin system                          | Future                               |
| Timeline / animation       | New `application/` workflow            | Future                               |
