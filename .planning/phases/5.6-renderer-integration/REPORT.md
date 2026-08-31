# Phase 5.6 — Renderer Integration: Final Report

## Summary

Successfully integrated the Phase 5.5 warp pipeline into the existing ModernGL render path. The GPU-accelerated `ProjectionPass` now renders content textures warped through a `WarpMesh` using vertex-shader-driven distortion, with blend/mask/crop support. The existing `PatternPass`/blackout/freeze/live output flow remains intact.

## Deliverables Implemented

### 1. GLSL Shaders (`_glsl.py`)

Added two new embedded shaders:

- **`projection.vert`** — Vertex shader that applies warp mesh distortion. Takes `in_position` (projector UV → clip space) and `in_uv` (content UV), passes `v_uv` to fragment shader.
- **`projection.frag`** — Fragment shader with:
  - Crop region discard (uniform `u_crop`: x, y, width, height)
  - Circular feathered mask (uniforms `u_mask_enabled`, `u_mask_center`, `u_mask_radius`)
  - Blend opacity (uniform `u_blend`)

### 2. Shader Class Extension (`shader.py`)

Added `set_vec2(name, x, y)` method for setting vec2 uniforms (used for mask center).

### 3. ProjectionPass Rewrite (`passes/projection.py`)

Complete GPU implementation following `PatternPass` pattern:

- **VAO/VBO setup**: Interleaved vertex buffer format `"2f 2f"` (position.xy, uv.xy)
- **Mesh upload**: Interleaves `WarpMesh.projector_uvs` (projector output coordinates) and `WarpMesh.content_uvs` into VBO on change detection (by object identity)
- **Uniforms**: Blend, crop, mask parameters passed each frame
- **Render flow**: Binds source texture, sets uniforms, draws VAO
- **Bugfix (5.6-R)**: Fixed `set_warp_mesh()` which was incorrectly setting `_mesh_id`, preventing `_ensure_mesh_uploaded()` from ever detecting changes. Now `_mesh_id` is only updated after a successful VBO upload.

### 4. Output Content Kind Extension (`output_content.py`)

- Added `OutputContentKind.PROJECTION = "projection"`
- Added `OutputContent.projection(warp_mesh, source_texture)` factory method
- Validation ensures `warp_mesh` only present for PROJECTION kind

### 5. GLOutputWindow Integration (`output_window.py`)

- Added `ProjectionPass` member, initialized in `initializeGL()`
- Modified `paintGL()` to route PROJECTION content to `ProjectionPass` (bypasses pipeline), all other kinds to `PatternPass`
- Both passes resized in `resizeGL()`

## Validation Results

| Check              | Result                                           |
| ------------------ | ------------------------------------------------ |
| `ruff check`       | ✅ Clean (renderer + test files)                 |
| `mypy` (strict)    | ✅ Clean (renderer + test files)                 |
| Full test suite    | ✅ 1320 passed (0 failed, no deselection needed) |
| Coverage           | ✅ 68.26% (> 60% threshold)                      |
| `git diff --check` | ✅ No whitespace errors (only CRLF warnings)     |

## Bugfix: VBO Upload Path

**Root cause**: `set_warp_mesh()` was setting `self._mesh_id = id(mesh)` immediately, which meant `_ensure_mesh_uploaded()` always saw `self._mesh_id == id(self._warp_mesh)` and skipped the upload. The VBO upload path never fired.

**Fix**: Removed `_mesh_id` update from `set_warp_mesh()`. Now `_mesh_id` is only updated by `_ensure_mesh_uploaded()` after a successful VBO write. When `set_warp_mesh(None)` is called, `_mesh_id` resets to -1 to allow the next mesh upload.

## Architecture Compliance

- **No architecture replacement**: Existing QtDisplayProvider → DisplayManager → OutputManager → GLOutputWindow → QOpenGLWidget private FBO → ModernGL 5.12 → PatternPass/ScreenTarget flow preserved
- **Additive rendering**: ProjectionPass renders additively; PatternPass unchanged
- **Vertex-shader-driven warp**: GPU does warp per-frame; no CPU rasterize → upload
- **Consumes existing contracts**: Uses `WarpMesh` from Phase 5.5 as-is; no domain changes
- **No forbidden work**: No C++, native/, CMake, pybind11, multi-projector, media engine, editor workflow

## Files Modified (5.6 + 5.6-R)

### Production files

| File                                                            | Change Type                                |
| --------------------------------------------------------------- | ------------------------------------------ |
| `src/projectionai/infrastructure/renderer/_glsl.py`             | Added `projection.vert`, `projection.frag` |
| `src/projectionai/infrastructure/renderer/shader.py`            | Added `set_vec2()`                         |
| `src/projectionai/infrastructure/renderer/passes/projection.py` | Complete GPU rewrite + VBO bugfix          |
| `src/projectionai/infrastructure/renderer/output_content.py`    | Added `PROJECTION` kind + factory          |
| `src/projectionai/infrastructure/renderer/output_window.py`     | Added ProjectionPass, routing logic        |

### Test files

| File                                                                   | Change Type                              |
| ---------------------------------------------------------------------- | ---------------------------------------- |
| `tests/unit/infrastructure/renderer/test_projection_pass.py`           | NEW: 24 ProjectionPass unit tests        |
| `tests/unit/infrastructure/renderer/test_output_content_projection.py` | NEW: 16 OutputContent PROJECTION tests   |
| `tests/unit/infrastructure/renderer/test_output_window.py`             | Extended: routing + FBO validation tests |

## Test Inventory (5.6-R)

### ProjectionPass tests (`test_projection_pass.py` — 24 tests)

- **A. Initialization**: initial state, setup creates shader/VBO/VAO
- **C. Mesh upload**: interleaving, change detection, replacement, None reset, noop without mesh/VBO
- **E. Source texture**: store and clear
- **F. Blend/mask/crop**: set_blend, set_crop, set_mask, set_output_size
- **G. Render**: noop without resources/target/texture/mesh, full render path, mask disabled
- **I. Release**: releases GPU resources, idempotent, noop without resources
- **K. FBO**: binds current target, empty mesh skips draw

### OutputContent PROJECTION tests (`test_output_content_projection.py` — 16 tests)

- Kind value, four kinds exist
- Factory: basic, requires warp_mesh, None source_texture allowed
- Invariants: pattern/black/freeze cannot carry warp_mesh, projection must have warp_mesh
- Pattern kind guard: pattern requires pattern_kind, non-pattern rejects it
- Equality/inequality, immutability

### GLOutputWindow routing tests (`test_output_window.py` — 10 new tests)

- Routes PROJECTION → ProjectionPass, PATTERN/BLACK/FREEZE → PatternPass
- Missing texture falls back to black
- FBO id refreshed before every render
- Resize updates both passes
- ScreenTarget receives widget's defaultFramebufferObject()
- paintGL always refreshes FBO before rendering

## Next Steps (Post-5.6)

1. **Phase 5.7** — C++/native engine work (blocked until user decides)
2. **Integration test** — End-to-end projection content through DisplaysViewModel
3. **Visual validation** — Manual verification on hardware with real projector
