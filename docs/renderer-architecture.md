# Renderer Architecture

## Overview

The renderer subsystem is the GPU-accelerated 3D rendering engine built on
**ModernGL** (raw OpenGL 3.3+ wrapper). It lives entirely in
`infrastructure/renderer/` and implements the `Renderer` / `WarpEngine`
interfaces defined in `services/renderer.py`.

```
services/renderer.py         ← interface (ABC)
infrastructure/renderer/     ← implementation
```

Design goals:

- **No game engines.** ModernGL gives us raw OpenGL with Pythonic ergonomics.
- **Pipeline architecture.** Rendering is a sequence of passes (scene, grid,
  selection, overlay, debug, background) that can be reordered or toggled.
- **Testable math.** Camera projections, mesh generation, and statistics are
  tested without a GPU context (90 tests, all in-process).

---

## Subsystems

The 16 source files divide into five concerns:

### 1. Camera System (`camera.py`)

| Class                | Role                                                                 |
| -------------------- | -------------------------------------------------------------------- |
| `Camera` (ABC)       | Base: position, target, up, near/far planes, view matrix (look-at)   |
| `PerspectiveCamera`  | FOV + aspect → perspective projection matrix                         |
| `OrthographicCamera` | Left/right/bottom/top → orthographic projection matrix               |
| `OrbitCamera`        | Wraps any Camera; spherical-coordinate orbit, pan, zoom with damping |
| `OrbitConstraints`   | Min/max distance, polar angle limits, speed multipliers              |
| `MouseButton`        | LEFT / RIGHT / MIDDLE enum for viewport input routing                |

Each camera caches its view + projection matrices and recomputes on `_dirty`
flag — avoids redundant math when neither position nor target has changed.

`OrbitCamera` is the interactive camera used by the viewport. It maintains
spherical coordinates (theta, phi, distance) relative to a target point and
applies exponential damping for smooth interpolation each frame.

### 2. Geometry / Mesh (`mesh.py`)

| Class          | Role                                                                           |
| -------------- | ------------------------------------------------------------------------------ |
| `Mesh`         | CPU-side vertex data (float32 arrays): vertices, normals, UVs, colors, indices |
| `MeshRenderer` | GPU-side VAO/VBO wrapper (requires ModernGL context)                           |

`Mesh` is a frozen-like dataclass with factory methods for primitives:

- `Mesh.cube(size=1.0)` — 8 verts, 36 indices (12 triangles)
- `Mesh.plane(size=1.0)` — 4 verts, 6 indices (2 triangles), XZ plane
- `Mesh.sphere(radius=1.0, segments=32)` — UV sphere

Properties auto-compute bounding box/center/radius and normals (via
`_compute_normals()` which averages face normals per vertex).

### 3. Pipeline (`pipeline.py` + `pipeline_pass.py`)

| Class              | Role                                                           |
| ------------------ | -------------------------------------------------------------- |
| `RenderPass` (ABC) | Single stage: name, enabled/visible toggle, target framebuffer |
| `RenderPipeline`   | Ordered list of passes with add/remove/move/get operations     |

Each `RenderPass` has a lifecycle:

```
setup(ctx, w, h) → render(ctx, scene, camera) → release()
                              ↕
                       resize(ctx, w, h)
```

Concrete passes live in `passes/`:

| Pass             | Role                                                |
| ---------------- | --------------------------------------------------- |
| `BackgroundPass` | Solid color or gradient background                  |
| `GridPass`       | Ground plane grid + axis gizmo                      |
| `ScenePass`      | Main 3D scene rendering (solid/wireframe/textured)  |
| `SelectionPass`  | Highlight pass for selected objects                 |
| `OverlayPass`    | 2D screen-space overlay (text, icons)               |
| `DebugPass`      | Diagnostic visualizations (normals, bounding boxes) |

### 4. GPU Resources

| Module             | Class                           | Role                                                     |
| ------------------ | ------------------------------- | -------------------------------------------------------- |
| `context.py`       | `ContextManager`                | ModernGL context creation (pyglet headless or Qt shared) |
| `shader.py`        | `ShaderManager`                 | GLSL program compile/link/uniform management             |
| `texture.py`       | `TextureManager`                | 2D texture load/cache/bind                               |
| `framebuffer.py`   | `FramebufferManager`            | FBO creation/resize/blit                                 |
| `material.py`      | `Material`                      | Shader + uniform values (color, textures, flags)         |
| `render_target.py` | `ScreenTarget` / `RenderTarget` | Abstract render destination (screen or FBO)              |

These all require an active ModernGL context and cannot be tested without one.

### 5. Statistics / Settings (`statistics.py` + `settings.py`)

| Module          | Role                                                                      |
| --------------- | ------------------------------------------------------------------------- |
| `statistics.py` | `RenderStatistics` — sliding-window frame timing, FPS, draw-call counting |
| `settings.py`   | `RendererSettings` — dataclass with 30+ quality/performance toggles       |

`RenderStatistics` is thread-safe by design: the render thread writes metrics
each frame, the UI thread reads the latest snapshot via `collect()`.

---

## Architecture & Data Flow

### Per-Frame Flow

```
User Input → Viewport (Qt widget)
                 │
                 ▼
          OrbitCamera.update(dt)
                 │
                 ▼
          RenderPipeline.render(ctx, scene, camera)
                 │
          ┌──────┼──────────┬──────────┬───────┐
          ▼      ▼          ▼          ▼       ▼
     Background Grid    Scene    Selection  Overlay

          ▼
     Viewport.paintGL() → Qt swap buffers
```

### Class Hierarchy

```
Camera (ABC)
├── PerspectiveCamera
├── OrthographicCamera
└── OrbitCamera  ← wraps inner Camera

RenderPass (ABC)
├── BackgroundPass
├── GridPass
├── ScenePass
├── SelectionPass
├── OverlayPass
└── DebugPass

RenderPipeline
  └── owns list[RenderPass]
```

### Threading Model

- **Render thread** (Qt's main thread via `QOpenGLWidget`): owns the ModernGL
  context, calls `render()` each frame, writes to `RenderStatistics`.
- **UI thread** (same thread — Qt is single-threaded for widgets): reads
  viewport, processes input, reads statistics snapshot.
- **Worker threads** (job manager): never touch GL resources.
- Cross-thread access to `RenderStatistics` is safe: render thread writes,
  UI thread reads `collect()` which returns an immutable `FrameMetrics` copy.

---

## Integration Path

### How the Renderer Connects to the App

```
services/renderer.py
    Renderer (ABC):  render(), render_offscreen(), warp()
    WarpEngine (ABC): warp_texture(), estimate_warp()
              ↕  implements
infrastructure/renderer/moderngl_renderer.py
    ModernGLRenderer(Renderer, WarpEngine)
              │
              ▼
         Viewport (Qt widget, embeds ModernGL context)
              │
              ▼
         RenderPipeline → various passes
```

### Bootstrap Sequence

1. `app.py` creates `ModernGLRenderer` with `RendererSettings`
2. Qt `MainWindow` creates `Viewport` widget
3. `Viewport` creates `QOpenGLContext` → ModernGL context
4. `Viewport.initializeGL()` creates `RenderPipeline`, calls `pipeline.initialize(ctx, w, h)`
5. Each pass allocates its GPU resources (shaders, VBOs, FBOs)
6. Each frame: `timerEvent()` → `update()` → `paintGL()` → `pipeline.render()` → swap buffers

### Extending the Pipeline

Add a new pass:

1. Create `infrastructure/renderer/passes/my_pass.py`
2. Extend `RenderPass`, implement `setup()` and `render()`
3. Register in the pipeline during viewport initialization:

```python
pipeline.add_pass(MyPass("my_pass"), index=2)
```

No other code changes needed — the pipeline iterates passes generically.

---

## Quality Gates & Coverage

| Gate               | Status    | Notes                                                              |
| ------------------ | --------- | ------------------------------------------------------------------ |
| mypy (renderer)    | 0 errors  | 24 source files, strict                                            |
| ruff               | 0 errors  | All rules enabled                                                  |
| Unit tests         | 90 passed | No GPU required                                                    |
| `camera.py`        | 97%       | Lines 85–86, 168, 176, 197, 276, 285, 422, 436 (all GPU-dependent) |
| `settings.py`      | 96%       | Post-init validation branches                                      |
| `statistics.py`    | 90%       | Timing-dependent branches (FPS update interval)                    |
| `pipeline_pass.py` | 100%      | All code paths tested                                              |
| `pipeline.py`      | 72%       | `initialize()`/`resize()`/`render()` need GPU context              |
| `mesh.py`          | 62%       | `MeshRenderer` + `_compute_normals` edge cases need GPU            |
| Imports            | OK        | `from projectionai.infrastructure.renderer import *` works         |

---

## Weaknesses & Known Limitations

1. **Single-context.** ModernGLRenderer owns one GL context. Multi-viewport or
   off-screen rendering to multiple windows requires context sharing (not yet
   implemented).

2. **Qt-bound.** The viewport is a `QOpenGLWidget`. Headless rendering (for
   automated screenshot, CI testing, or server-side warp) requires a
   headless GL context (pyglet/EGL). The `ContextManager` stub exists but
   hasn't been wired.

3. **No texture streaming.** All textures are loaded into VRAM at startup.
   Large assets (4K+ textures) will exhaust GPU memory.

4. **MeshRenderer unvalidated.** `MeshRenderer` wraps ModernGL VAO/VBO
   creation but has no tests — creating one requires a live GL context.

5. **Pass isolation.** A crashing pass (`render()` raises) is caught and
   logged but the pipeline continues. This means a broken pass produces
   visual artifacts rather than a hard error — could make debugging harder.

6. **No shader hot-reload.** Shaders are compiled once at setup. Editing
   GLSL files requires restart. A watch-compile-reload mechanism is planned
   but not implemented.

7. **OrbitCamera damping is frame-rate dependent.** The exponential damping
   factor uses `dt` to normalize, but very low or very high frame rates
   can cause visible jitter or sluggishness. A fixed-timestep accumulator
   would be more robust.

8. **Framebuffer blitting.** The current FBO chain blits full-resolution
   between passes. Tiled rendering or partial-update (damage-region)
   approaches would improve performance on high-DPI displays.
