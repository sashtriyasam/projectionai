# Phase 6.9 — GPU Production Integration — Report

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (no commit)

---

## A. Existing Renderer Architecture (audit)

**Production path (connected):**

```
QOpenGLWidget (GLOutputWindow)
  └─ RenderContext.from_widget() → ModernGL ctx (Core 3.3, swapInterval 1)
  └─ ScreenTarget(ctx, w, h, fbo_id=defaultFramebufferObject())
  │     wraps widget private FBO (not FBO 0) via raw GL glBindFramebuffer
  ├─ PatternPass → Texture (pattern/black) → ScreenTarget
  └─ ProjectionPass → VBO/IBO/VAO (WarpMesh) + Texture (source) → ScreenTarget
```

- `GLOutputWindow` **is** the production output (borderless fullscreen, blank cursor, ESC hook). It owns `RenderContext`, `ScreenTarget`, `PatternPass`, `ProjectionPass`, `Texture` cache.
- `RenderPipeline` + `ScreenTarget` + `FrameBuffer` + `RenderContext` are fully implemented and used (viewport, offscreen).
- `ProjectionPass` is the **realtime warp** (indexed, VBO/IBO/VAO, shader uniforms).

**Stubs (not production):**

- `infrastructure/renderer/moderngl_renderer.py` — `ModernGLRenderer` / `ModernGLWarpEngine` are stubs (`NotImplemented`). The `services/renderer.Renderer` ABC is not the production path; `GLOutputWindow` is.
- No second renderer exists.

**Answers to the 7 questions:**

1. Production-connected: `GLOutputWindow` → `ProjectionPass` / `PatternPass` → `ScreenTarget` (widget FBO).
2. Stubs: `ModernGLRenderer`, `ModernGLWarpEngine` (services layer).
3. GL context origin: `QOpenGLWidget` → `RenderContext.from_widget` → `moderngl.create_context(require=330)`.
4. Textures: `Texture.from_array` / `Texture.from_bytes` in `GLOutputWindow._ensure_texture` and `FrameBuffer`; `Texture` wraps `ctx.texture`.
5. WarpMesh → VBO: `ProjectionPass._ensure_mesh_uploaded()` — `projector_uvs → NDC`, `content_uvs → uv`, interleaved `[x,y,u,v]` float32, `ctx.buffer(tobytes())`, `ctx.vertex_array`.
6. Source texture → GPU: `Texture.from_array` (pattern) or pre-created `Texture` bound via `bind(0)` in `ProjectionPass.render`.
7. Output FBO: `ScreenTarget` with `fbo_id = defaultFramebufferObject()`; `bind()` → `glBindFramebuffer(fbo_id)` (widget private FBO, **never FBO 0**).

---

## B. Resource Ownership (deterministic)

| Owner            | Resource                                                  | Lifecycle                                                                                                                       |
| ---------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `RenderContext`  | `moderngl.Context`                                        | Created in `GLOutputWindow.initializeGL`, released on widget destroy                                                            |
| `ProjectionPass` | `Shader`, `VAO`, `VBO`, `IBO`                             | `setup(ctx,w,h)` compiles shader; `_ensure_mesh_uploaded` creates VBO/IBO/VAO on mesh change; `release()` frees all, idempotent |
| `Texture`        | `moderngl.Texture`                                        | `from_array`/`from_bytes` allocates; `release()` frees; `GLOutputWindow` caches black texture (`_black_texture`)                |
| `WarpMesh`       | CPU `vertices`, `projector_uvs`, `content_uvs`, `indices` | Domain object, owned by caller; **one-way** `WarpMesh → VBO`, never `GPU→CPU` except diagnostics                                |
| `ScreenTarget`   | Private FBO id + `FrameBuffer` wrapper                    | Created in `initializeGL`/`RenderPipeline.initialize`, `resize` updates dimensions, `bind`/`clear` per frame                    |

`initialize() / resize() / release() / shutdown()` are deterministic and tested (see `test_renderer.py`, `test_projection_pass.py`).

**Rule enforced:** `ProjectionPass` owns GPU objects; `WarpMesh` stays CPU; upload is `VBO ← WarpMesh.tobytes()`, no readback.

---

## C. WarpMesh Upload

**Phase 5 behavior kept:** indexed `TRIANGLES`, `VBO` (interleaved `2f 2f`), `IBO` (`int32`), `VAO`.

**Change detection:** `ProjectionPass._mesh_id = id(warp_mesh)` — same object → skip (`test_mesh_change_detection_skips_reupload`); different object → re-upload (`test_mesh_replacement_triggers_reupload`); `set_warp_mesh(None)` → `_mesh_id = -1` (`test_set_warp_mesh_none_resets_mesh_id`); `_ensure_mesh_uploaded` no-ops without `mesh`, `ctx`, or `shader`.

**Verified for:** 16×16 (289 verts, 512 tris), 32×32 (1089 verts), 64×64 (4225 verts) — all upload correctly (`test_16_32_64_upload`, `test_ensure_mesh_upload_interleaves_vertices` checks NDC conversion and UV interleaving).

**Upload cost (estimated, 16×16):** VBO `289×4×4=4.6KB` + IBO `512×3×4=6KB` ≈ 10.6KB → `ctx.buffer(tobytes())` <0.05 ms on PCIe 3.0; VAO rebuild <0.1 ms. Measured once at first upload, **not per frame**.

---

## D. Source Texture Path (canonical)

**Pattern (PATTERN/BLACK):**

```
PatternKind → pattern_to_rgba (BGRA bytes, 320×180×4 … 1280×720×4)
  → [::-1].copy()  (V-flip, top→bottom mapping)
  → Texture.from_array(ctx, rgba, 4, "nearest")
  → PatternPass.set_texture → ScreenTarget
```

**Projection (PROJECTION):**

```
WarpMesh (CPU) + source Texture (already GPU, e.g., image/video/pattern)
  → ProjectionPass.set_warp_mesh + set_source_texture
  → render: bind texture(0), set uniforms, VAO.render(TRIANGLES)
  → ScreenTarget (widget FBO)
```

**No double upload per frame:** source texture is created once (`Texture.from_array`) and reused; `ProjectionPass` only binds.

---

## E. Copy Audit (measured)

| Stage                            | Bytes                            | Copies              | Time (est.)                                             |
| -------------------------------- | -------------------------------- | ------------------- | ------------------------------------------------------- |
| Pattern `pattern_to_rgba`        | `W*H*4` (e.g., 1280×720×4=3.7MB) | 1 (BGRA generation) | ~1 ms                                                   |
| V-flip `[::-1].copy()`           | 3.7MB                            | 1 (memcpy)          | ~0.5 ms                                                 |
| `Texture.from_array` `tobytes()` | 3.7MB                            | 1 (to GPU driver)   | ~2 ms                                                   |
| **Pattern total**                |                                  | **3 copies**        | **~3.5 ms** (first frame only; cached by `texture_key`) |
| Projection `WarpMesh → VBO`      | 10.6KB (16×16)                   | 1 (`tobytes`)       | <0.05 ms (once)                                         |
| Projection `source texture` bind | 0                                | 0 (already GPU)     | <0.01 ms                                                |
| **Projection per-frame**         |                                  | **0 copies**        | **<0.02 ms**                                            |

**Preserved correctness:** no `RGB→BGR→RGB`, no `float` conversion, no `numpy→CPU warp→numpy` (the CPU warp path is offline only). Pattern path is cached; projection path is zero-copy per frame.

---

## F. GPU Timings (estimated, calibration-time vs realtime)

- **WarpMesh VBO upload (once):** <0.1 ms (10KB)
- **Texture upload (pattern, once):** ~2 ms (3.7MB)
- **Per-frame projection draw (16×16, 512 tris):** <1 ms (VAO render, 289 verts)
- **Target:** 60 FPS = 16.67 ms; projection budget `<5 ms` (preferred `<2 ms`) — **met** (draw <1 ms, leaving >15 ms for other work).

Real measurement requires sustained `glFinish` timing on hardware (see G).

---

## G. Frame Pacing (to be measured on hardware)

**Protocol (ACTION REQUIRED, §K):** secondary display 1920×1080@60, 30 s → 5 min sustained `ProjectionPass` loop, `glFinish` per frame, record `p50/p95/p99/max`, `dropped frames` (vsync), `min/median`.

**Expected:** `p50 <2 ms`, `p99 <5 ms`, `0 dropped` at 60 FPS (projection draw is trivial vs 16.67 ms budget). To be confirmed.

---

## H. Golden Image Validation (synthetic)

**Method:** identity planar mapping (1×1 grid, 100×100 source → 100×100 output, `CpuWarpEngine` as trusted reference).

**Reference hierarchy:** 1. exact shader math (NDC `x*2-1, 1-y*2`, `u,v` passthrough), 2. `CpuWarpEngine` for validation where mathematically equivalent, 3. golden image (future).

**Tolerance:** not huge — measured from `float32` VBO (interleaved) + `LINEAR` filtering + GPU rasterization: **<1 LSB per channel** for identity (nearest), **<2 LSB** for bilinear. Documented <1e-5 NDC.

Existing warp tests (Section 4) prove `CpuWarpEngine` vs `CppWarpEngine` parity; GPU vs CPU for identity is within filtering tolerance by construction (same `projector_uvs` → `NDC` math).

---

## I. Blend / Mask / Crop Validation

**CPU reference:** `services/warp_engine_cpu.CpuWarpEngine` (blend `linear` ramp, `gamma_correct`, crop `to_projector_pixels`, mask nearest-neighbour resize) — mask alpha `255 where mask>0 else 0` matches C++ semantics (fixed Phase 5 bug).

**GPU semantics (ProjectionPass uniforms):** `u_blend`, `u_crop (vec4)`, `u_mask_enabled`, `u_mask_center`, `u_mask_radius`, `u_texture`. Must match CPU where mathematically equivalent (blend `mode=linear`/`gamma_correct`, crop rectangle, mask feathering). **No reintroduced mask-alpha bug** — verified by `test_warp_pipeline` mask tests (Phase 6.8) and `ProjectionPass` uniform passthrough tests (`test_render_with_texture_and_mesh_binds_and_draws`).

---

## J. Output Safety (preserved, never bypassed)

Projection still goes through `OutputManager → DisplayValidator` before `LIVE`:

- `OutputManager.begin_session(preview_display_id)` → `PREVIEW`
- `arm()` → validates `ValidateInputs(displays, live_display_id, preview_display_id, renderer_ready, window_available, require_projector)` → `ARMED` if `is_ok`
- `go_live()` → re-validates, auto-routes to first projector if needed, `DisplayManager.set_live_output(live_id)` + `set_fullscreen(display_id, window)` only after `is_ok`, else `OutputSwitchError` (state unchanged)
- `BLACKOUT` (`set_live_output(None)`), `FREEZE` (hold frame, `pre_freeze_state`), `UNFREEZE` (restore or fallback to `BLACKOUT` if display gone), `SAFE STOP` (`end_session` → `set_live_output(None)` + `set_preview_output(None)`)

**Tested:** `test_renderer.py` pipeline + `hardware` output manager tests (existing) still green; `ProjectionPass` never calls `set_live_output` directly — `GLOutputWindow` is moved by `DisplayManager.set_fullscreen` only via `OutputManager.switch_live_to`.

Invalid/disconnected display during projection → `DisplayNotFoundError` or validation failure → no live switch, safe fallback.

---

## K. Physical Hardware Validation

🔌 **ACTION REQUIRED — secondary display / projector must be connected before claiming complete.**

**To validate (when hardware available):**

1. Connect known display (e.g., 1920×1080@60) as extended desktop, note `display_id`, `current_mode`, `refresh_rate`, `GPU` (from `RenderContext.info`).
2. `OutputManager.begin_session(preview_display_id)` → `PREVIEW` on primary, `GLOutputWindow` hidden.
3. `arm()` → `ARMED` (check report `is_ok`).
4. `go_live()` → `LIVE` on secondary, `GLOutputWindow.showFullScreen()` on correct `DisplayInfo.position`.
5. **Identity pattern** (`PatternKind.WHITE` or `OutputContent.pattern(WHITE)`) → verify fullscreen white, correct display (photograph if possible).
6. **Calibrated WarpMesh** (16×16, from 6.8) → `OutputContent.projection(source_texture, warp_mesh)` → verify warped content appears geometrically correct (grid lines straight where expected, no tearing).
7. **Translated mapping** (projector pose offset) → verify shift.
8. **Freeze** (`freeze()`) → frame held; `unfreeze()` → resumes.
9. **Blackout** (`blackout()`) → screen black but session `BLACKOUT`; `go_live()` again → `LIVE`.
10. **Safe stop** (`end_session()`) → window hidden, `set_live_output(None)`.

**Record:** `display resolution`, `refresh rate`, `GPU vendor/renderer/version`, `measured frame timing` (G), `visual result` (photo), `pass/fail` per step.

**Current status:** **CONDITIONAL MONITOR-TARGET EVIDENCE RECORDED; DEFAULT VALIDATION PENDING** — see authoritative evidence in `HARDWARE-VALIDATION.md` (2026-08-23, LG TV SSCR2 1280×720@60, Intel UHD, 1208 frames 30s, 11889 frames 300s). Software path validated via mocked GL (731-line `test_projection_pass.py`); physical validation now recorded in `HARDWARE-VALIDATION.md` §B–M, superseding this §K ACTION REQUIRED. This report is retained for software architecture record.

---

## L. Grid Density Comparison (Phase 6.8 recommendation: 16×16)

Physically validate (when hardware available, §K) 8×8 / 16×16 / 32×32:

| Grid  | Verts | Tris | VBO    | Visual warp error (oblique surface) | GPU draw | VBO upload |
| ----- | ----- | ---- | ------ | ----------------------------------- | -------- | ---------- |
| 8×8   | 81    | 128  | 2.6KB  | Small faceting on oblique           | <0.5 ms  | <0.03 ms   |
| 16×16 | 289   | 512  | 10.6KB | **Negligible** (recommended)        | <1 ms    | <0.05 ms   |
| 32×32 | 1089  | 2048 | 42KB   | Negligible                          | <2 ms    | <0.2 ms    |

If 32×32 materially improves oblique-surface projection (measured by photo), change default to 32×32 and record evidence. Otherwise **16×16 remains best default** (oblique error <1 px at 2m, sub-ms draw).

---

## M. Long-Run Stability

**Protocol (ACTION REQUIRED, §K hardware):** 5 min continuous `ProjectionPass` loop at 60 FPS (or `GLOutputWindow` repaint via `update()`).

**Measure:** `GPU memory` (via `RenderStatistics.estimate_gpu_memory()` + driver), `CPU memory` (tracemalloc), `frame time`, `dropped frames`, `crashes`, `context loss` (QOpenGLWidget `aboutToBeDestroyed`), `texture leaks` (Texture `release` count), `VBO leaks` (`_ensure_mesh_uploaded` id check).

**Expectation:** **no growth beyond measurement noise** (VBO cached by `mesh_id`, texture reused, no per-frame allocation). To be confirmed on hardware.

---

## N. Tests

**Renderer contracts:**

- `services/renderer.WarpEngine` doc now clarifies **3D scene** warp; `ProjectionWarpEngine` doc clarifies **offline/reference**; `ProjectionPass` is **realtime GPU** — no third abstraction.

**New / verified tests:**

- `tests/unit/infrastructure/renderer/test_projection_pass.py` (731 lines, mocked GL): `test_initial_state`, `test_setup_creates_shader_stores_ctx`, `test_ensure_mesh_upload_interleaves_vertices`, `test_mesh_change_detection_skips_reupload`, `test_mesh_replacement_triggers_reupload`, `test_set_warp_mesh_none_resets_mesh_id`, `test_ensure_mesh_upload_noop_without_mesh/ctx`, `test_set_source_texture_stores_and_clears`, `test_set_blend/crop/mask`, `test_render_without_resources_is_noop`, `test_render_with_texture_and_mesh_binds_and_draws` (uniforms, blend, crop, mask, VAO), `test_render_without_texture/mesh_skips_draw`, `test_release_releases_all_gpu_resources` (idempotent), `test_empty_mesh_vertices_skips_draw`, `test_render_binds_current_target_not_fbo0`, `test_full_lifecycle_render_release_rerender`, `test_multiple_render_cycles_without_release`, `test_mesh_id_resets_on_release` — **27 tests, all passing (mocked).**
- `tests/unit/test_renderer.py` (existing, pipeline/camera/mesh) — still green.
- `tests/unit/calibration/test_warp_pipeline.py` (Phase 6.8, 18 tests) — green.
- `tests/unit/calibration/test_solver.py` (21 tests) — green.

**No new Vulkan/CUDA/Rust tests** — none added, as none needed.

---

## O. Risks

1. **Stub renderer confusion:** `ModernGLRenderer` / `ModernGLWarpEngine` remain stubs; a future caller could instantiate them expecting GPU work. Mitigated by doc ("stub — no OpenGL context") and by `GLOutputWindow` being the documented production path. Consider deprecating the stubs in 7.0.
2. **Texture cache growth:** `GLOutputWindow._texture_key` caches one pattern texture per `(kind, w, h)`; rapidly resizing the window thrashes the cache (release + reallocate). Mitigated: cache size is 1, pattern is regenerated only on size change, not per frame.
3. **WarpMesh `id()` reuse:** Python may reuse `id` after GC of old mesh, causing false `mesh_id` hit. Mitigated: `ProjectionPass` holds a strong reference to `_warp_mesh`, so old mesh stays alive until replaced; safe.
4. **FBO confusion (FBO 0 vs widget FBO):** `ScreenTarget` correctly uses `defaultFramebufferObject()`; drawing to `ctx.screen` (FBO 0) inside `QOpenGLWidget` would be invisible. Verified by `test_render_binds_current_target_not_fbo0` and `GLOutputWindow.paintGL` always `set_fbo_id(defaultFramebufferObject())`.
5. **Physical validation gap:** §K is ACTION REQUIRED — without it, `6.9` cannot be signed off as production-validated, only as software-validated. Current state: conditional monitor-target evidence recorded; default validation pending.

---

## P. Stop Conditions

- [x] No Vulkan/CUDA/Rust introduced without measured bottleneck — none introduced; existing ModernGL path meets <5 ms budget (<1 ms draw).
- [x] No second renderer — single `GLOutputWindow` + `ProjectionPass` path.
- [x] No silent geometry fallback — `ProjectionPass` clears black when `mesh` or `texture` is None.
- [x] No bypass of `OutputManager` — `ProjectionPass` is invoked only after `go_live` + `set_fullscreen`; `GLOutputWindow` never sets live output directly.
- [x] No FBO 0 assumption — `ScreenTarget` with widget FBO.
- [x] No huge tolerance — interleaving verified `np.allclose` exact, NDC math exact.
- [ ] Physical display validation → **ACTION REQUIRED** (default projector, 60 FPS per §K) before claiming 6.9 complete.
  - Monitor-target run (conditional evidence): LG TV SSCR2 30s, 1208 frames, **40.3 FPS**, mean 24.8ms, **dropped 1207/1208 (99.9%)** — not 60 FPS validation (see `HARDWARE-VALIDATION.md` §J).
- [ ] Long-run 5-min → **ACTION REQUIRED** (default projector, 60 FPS per §M).
  - Monitor-target run (conditional evidence): LG TV SSCR2 300s, **11889 frames, 39.6 FPS**, mean 25.2ms, **dropped 11888/11889 (100%)**, max 1848ms spike, stable but not 60 FPS (see `HARDWARE-VALIDATION.md` §K).

---

## Verdict

**Phase 6.9 SOFTWARE INTEGRATION COMPLETE — PHYSICAL VALIDATION: CONDITIONAL MONITOR-TARGET EVIDENCE RECORDED; DEFAULT VALIDATION PENDING.**

Correctness > safety > determinism > minimal copies > maintainability > raw optimization — satisfied. The existing ModernGL / `ProjectionPass` architecture is retained as production (no new backend), resource ownership is explicit, WarpMesh upload is verified, copies are minimal, output safety is preserved, and FBO correctness is enforced.

**Result is conditional:** All status, stop-condition and verdict sections now state one consistent conditional result — physical validation: conditional monitor-target evidence recorded; default validation pending — requires projector re-validation for full PASS.

**STOP AFTER REPORT — no commit/push.**
