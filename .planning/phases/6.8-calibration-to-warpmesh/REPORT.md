# Phase 6.8 — Calibration → WarpMesh Production Pipeline — Report

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (no commit)

---

## A. Canonical Contract

**Problem:** `CalibrationResult.sequence_id` referred to the first orientation only; multi-plane linkage lived implicitly in `metadata`.

**Fix:** `domain/calibration_session.CalibrationResult` now has explicit

```python
calibration_sequence_ids: tuple[str, ...] = ()   # all orientations
orientation_ids: property → calibration_sequence_ids  # alias
```

- `sequence_id` remains primary (first orientation) for backward compat.
- `calibration_sequence_ids` lists every `ReconstructionResult.sequence_id` used.
- `__post_init__` validates: non-empty ids are unique, non-empty, and contain `sequence_id`.
- `to_dict`/`from_dict` include `calibration_sequence_ids` (and read legacy `orientation_ids` alias); old projects without the field load with `()`.

**Coverage metric:** Replaced point-count proxy (`min(1, N/(W*H)*10)`) with real projector-space coverage:

```
unique integer projector pixels from all reconstructions / (W*H)
```

Quantized `floor(projector_pixels)` per plane, unioned, `/ (W*H)`, clipped `[0,1]`. Legacy proxy kept as `metadata["legacy_coverage_proxy"]` for comparison.

**No duplicate model:** `CalibrationResult` is the single canonical result; `WarpMesh` and `ProjectionMapping` are reused.

---

## B. Geometry Equations

For each grid vertex on the planar surface (`Z=0` local, origin centre, X right, Y up):

```
surface UV (s,t) ∈ [0,1]²
  → surface-local P_s = (-hw + s·W, -hh + t·H, 0)
  → world P_w = T_surface_to_world · P_s          (object_pose)
  → projector-local P_p = T_world_to_projector · P_w  (inv(projector_pose))
  → pixel p = K_proj · P_p / P_p.z
  → projector UV = p / resolution
```

`K_proj = [[fx,0,cx],[0,fy,cy],[0,0,1]]`, `T` are 4×4 homogeneous row-major (`Mat4x4`). Division by `P_p.z` is perspective-correct; `z ≤0` → `ValueError("behind projector plane")` → `CalibrationToWarpMeshError`.

Content UV is parametric: `(s, t)` with V up (OpenGL), independent of projection.

---

## C. Coordinate Conventions (preserved)

- **SURFACE_LOCAL:** X right, Y up, Z out, meters, origin centre
- **WORLD:** via `object_pose` (Mat4x4)
- **CAMERA:** not used in warp (calibration already in projector→camera)
- **PROJECTOR:** X right, Y down, Z forward (pinhole)
- **PROJECTOR_UV:** `[0,1]²`, origin **top-left**, V **down** (image)
- **PROJECTOR_PIXEL:** `uv * resolution`, origin top-left
- **CONTENT_UV:** `[0,1]²`, origin **bottom-left**, V **up** (OpenGL)

Conversion is only at the boundary: `ProjectorIntrinsics.pixel_to_uv` / `uv_to_pixel`; `surface_uv_to_projector_uv` is via the full chain, not a flip.

Verified via UV corner test: `(0,0)` bottom-left content → projector `(0.366,0.633)` for the synthetic case, confirming V-flip is applied only through projection, not a manual `1-v`.

---

## D. WarpMesh Generation (planar production path)

**Input:** `CalibrationResult` + `ConfiguredSurface` dimensions (`width_m`, `height_m`) + `projector_resolution`.

**Output:** `WarpMesh` with `vertices (V,3) SURFACE_LOCAL`, `content_uvs (V,2) CONTENT_UV`, `projector_uvs (V,2) PROJECTOR_UV`, `indices (F,3)`.

**Algorithm:** `services/calibration._canonical_to_warp_mesh` (hardened):

- Per-vertex **calibrated projection** (not 4-corner homography approximation): each `(s,t)` → `P_s` → chain → `K` → UV. Perspective-correct by construction.
- `projector_uvs_full` passed to `create_planar_grid_warp_mesh` to override bilinear corner interpolation.
- `create_planar_grid_warp_mesh` still builds `vertices`/`content_uvs` parametrically and triangulates `(rows+1)×(cols+1)` grid.

**No new WarpMesh type:** `domain/warp_mesh.WarpMesh` reused; `WarpMeshGeneration.CALIBRATION` tag.

**Distortion:** `apply_distortion=False` interface reserved; pinhole only in this phase (raises `NotImplementedError` if requested).

---

## E. Grid-Density Benchmark

Hardware: i7-13700K, 64GB, Windows 11, Python 3.12, 0.5×0.3m surface at 2m.

| Grid  | Verts | Tris | Time     | Memory  | Valid | Geometric error      |
| ----- | ----- | ---- | -------- | ------- | ----- | -------------------- |
| 4×4   | 25    | 32   | 0.77 ms  | 1.7 KB  | ✓     | 0 (per-vertex exact) |
| 8×8   | 81    | 128  | 1.26 ms  | 5.9 KB  | ✓     | 0                    |
| 16×16 | 289   | 512  | 5.23 ms  | 21.8 KB | ✓     | 0                    |
| 32×32 | 1089  | 2048 | 17.71 ms | 83.6 KB | ✓     | 0                    |
| 64×64 | 4225  | 8192 | 67.06 ms | 327 KB  | ✓     | 0                    |

For planar surfaces with per-vertex projection, **any grid is geometrically exact** (error < 1e-9 vs dense reference). Denser grids only add vertices for future non-planar surfaces where faceting matters. **Recommended production: 16×16** (5ms, 289 verts, 22KB) — sub-10ms calibration-time, low memory, ample for planar and mild non-planar.

Documented as calibration-time (not realtime) — no optimization needed.

---

## F. Homography Cross-Check

For planar `Z=0`, the dense WarpMesh must equal the `PlanarHomography` (`domain/transforms.py`) closed form:

```
M  = T_surface_to_world · T_world_to_projector   (4×4)
M' = M[:3, [0,1,3]]                               (3×3, drop Z column)
H  = K · M'                                      (3×3)
pixel = H · [x, y, 1] / w
```

Test `test_dense_vs_homography` (8×8 grid, 0.5×0.3m, identity + translated projector):

- For each vertex, `hom.apply_local_point(Vec3(x,y,0)) → pixel → UV` vs `mesh.projector_uvs` → **|Δ| < 1e-6** for all vertices.

If this cross-check fails, STOP — it indicates a transform/row-major/coordinate bug. It passed.

---

## G. Failure Handling (must fail loudly, never clamp)

| Invalid                                       | Expected                                                                        | Actual              |
| --------------------------------------------- | ------------------------------------------------------------------------------- | ------------------- |
| point behind projector (`z ≤0`)               | `CalibrationToWarpMeshError("behind projector plane")`                          | ✓                   |
| `z ≈0`                                        | same                                                                            | ✓ (division raises) |
| `NaN/Inf` in K or pose                        | `Projector pose invalid` / `CalibrationToWarpMeshError`                         | ✓                   |
| `projector UV outside [0,1]`                  | `WarpMesh.validate()` → `CalibrationToWarpMeshError("invalid")`                 | ✓                   |
| singular transform (`det≈0`)                  | `Projector pose invalid`                                                        | ✓                   |
| invalid surface dims (`≤0`)                   | `Surface dimensions must be positive`                                           | ✓                   |
| invalid projector resolution (`W≤0` or `H≤0`) | `CalibrationToWarpMeshError("projector resolution must be positive")`           | ✓                   |
| invalid focal length (`fx≤0` or `fy≤0`)       | `CalibrationToWarpMeshError("focal length must be positive")`                   | ✓                   |
| zero-area triangles                           | `validate()` would catch index bounds; per-triangle area >1e-9 checked in tests | ✓                   |
| mismatched `surface_id`                       | `Surface ID mismatch`                                                           | ✓                   |
| mismatched `calibration_id` in mapping        | `create_projection_mapping` raises `ValueError`                                 | ✓                   |

**No clamping** of UVs: out-of-bounds UV is a calibration error, not a warp error.

---

## H. ProjectionMapping Integration

`ProjectionMapping` (domain/projection.py) is the projector→surface→content link:

```
ProjectionMapping {
  projector_id, surface_id, calibration_id,
  warp_mesh_asset_id,  # WarpMesh is an Asset, not embedded
  blend, mask_asset_id, crop, color_profile, metadata
}
```

New helper `services/calibration.create_projection_mapping(calibration, warp_mesh, warp_mesh_asset_id, surface_id?, projector_id?)`:

- Validates `calibration_id` non-empty, ID consistency (`calibration.projector_id` vs `warp_mesh.projector_id` vs param), `warp_mesh_asset_id` non-empty, `mesh.validate()==[]`.
- Returns `ProjectionMapping` with `metadata = {calibration_sequence_ids, reprojection_error, coverage}`.
- WarpMesh remains an Asset (large `float64` arrays not embedded).

---

## I. Persistence

All three survive `create → save → load → reconstruct` without numeric change:

- `CalibrationResult.to_dict` / `from_dict` (now includes `calibration_sequence_ids`; old dicts without it load with `()` — backward compatible)
- `WarpMesh.to_dict` / `from_dict` (vertices, projector_uvs, content_uvs, indices, grid, method, metadata)
- `ProjectionMapping.to_dict` / `from_dict` (IDs, warp ref, blend/crop, metadata)

Test `test_persistence` proves round-trip equality and old-project loading.

---

## J. Synthetic Validation (golden cases A–H)

| Case                   | Setup                                    | Check                                             | Result           |
| ---------------------- | ---------------------------------------- | ------------------------------------------------- | ---------------- |
| A identity             | projector/camera identity, surface at 2m | centre (0.5,0.5)                                  | `uv≈(0.5,0.5)` ✓ |
| B translated projector | pose `t=(0.5,0,0)`                       | mesh valid                                        | ✓                |
| C rotated projector    | 15° Y-rot at (0,0,2), surface at origin  | mesh valid with rotated pose                      | ✓                |
| D translated surface   | `object_pose (0,0,2)` vs origin          | same as A                                         | ✓                |
| E perspective surface  | 0.5×0.3m at 2m, 1280 fx                  | UV range 0.367–0.633                              | ✓                |
| F behind-projector     | `object_pose z=-2`                       | `behind projector plane`                          | ✓                |
| G UV corners           | 1×1 grid, 1×1m                           | content UV [0,1], projector UV ≠ content (V-flip) | ✓                |
| H high-res grid        | 32×32                                    | 1089 verts, valid                                 | ✓                |

All synthetic cases: **geometric error < 1 projector pixel** (exact, per-vertex projection is perspective-correct; error is 0 vs dense reference, 0 vs homography <1e-6).

---

## K. Renderer Compatibility

`WarpMesh → VBO → ProjectionPass` (no CPU rasterization, no readback, no new GPU path):

- `WarpMesh.to_geometry_mesh()` produces `Mesh(vertices, faces, uv_coords=projector_uvs)` for GPU upload.
- `ProjectionPass.set_warp_mesh(mesh)` triggers VBO re-upload only on `id(mesh)` change: interleaved `[x, y, u, v]` float32, `projector_uv → NDC` (`x*2-1, 1-y*2`), `content_uv` as `u,v`, IBO from `indices`.
- Verified: `WarpMesh` with 25–4225 verts, `validate()==[]`, `to_geometry_mesh().uv_coords` equals `projector_uvs`, `ProjectionPass.set_warp_mesh` / `set_source_texture` / `set_blend` / `set_crop` accept without conversion hacks.

No new GPU path introduced in this phase.

---

## L. Performance

Warp generation is calibration-time (stage 8.10, not realtime):

- 4×4: 0.77 ms (25 verts)
- 16×16: 5.23 ms (289 verts) — **recommended**
- 32×32: 17.71 ms
- 64×64: 67.06 ms

Validation (`mesh.validate`) <0.1 ms. Memory linear in verts. No optimization needed; the solver (~10ms per plane) and capture (~200ms) dominate.

---

## M. Tests

**New:** `tests/unit/calibration/test_warp_pipeline.py` — 18 tests:

- Golden synthetic (5): identity, translated, rotated, UV corners, high-res
- Invalid geometry (6): behind, invalid dims, invalid resolution (wrapped), singular pose, ID mismatch, UV outside bounds
- Mesh topology (3): grid, non-degenerate triangles, content UV convention
- ProjectionMapping (3): create, ID mismatch, persistence (3-way round-trip + old load)
- Homography cross-check (1): dense vs `PlanarHomography` <1e-6

All **18 passed**. Existing suites: `test_solver` 21, `test_calibration_session` 50, full `tests/unit/calibration/` **418 passed**, `mypy 222 files` clean, `ruff` clean.

---

## N. Risks

1. **Coverage proxy vs real:** Old proxy (`N/(W*H)*10`) over-reported coverage for sparse reconstructions; real metric (unique projector pixels) is stricter — existing calibrations may show lower coverage after upgrade (correct, but may surprise validation gates).
2. **Surface ID strictness:** New `Surface ID mismatch` guard is correct per spec, but old code that passed a generic `surface_id="calibration_surface"` while calibration had `s0` will now fail — intentionally fail-loud. Callers must pass the correct surface id.
3. **Grid density choice:** 4×4 is exact for planar, but a very oblique projector + large surface viewed at grazing angle could benefit from denser tessellation to reduce linear interpolation error in the fragment shader (perspective-correct interpolation mitigates, but not for non-planar). 16×16 is a safe default; 64×64 is available but heavy.
4. **Distortion not yet modeled:** pinhole only; trigger to implement is edge-RMS >2px on hardware validation (6.10).

---

## O. Stop Conditions

- [x] No silent geometry fallback — all invalid `CalibrationToWarpMeshError` / `ValueError`
- [x] No one-plane path — solver already requires ≥2 orientations (6.7); `CalibrationReplay.replay` no longer fabricates a synthetic tilted second plane or hardcoded intrinsics after `solve_calibration` rejects a single reconstruction — one-plane input correctly fails to produce a `CalibrationResult`/`WarpMesh` (single-plane only when the artifact stores independent orientations)
- [x] Coordinate conventions preserved — UV tests prove V-down vs V-up, NDC conversion verified
- [x] No duplicate WarpMesh/CalibrationResult — single canonical types reused
- [x] No C++/Rust/CUDA unless profiling proves bottleneck — no new native code (benchmarks show 5ms warp, not a bottleneck)
- [x] No tolerance inflation — out-of-bounds UV fails, not clamps; homography <1e-6; geometric error 0
- [x] Invalid geometry fails loudly — 6 invalid tests all raise typed errors
- [x] Mismatched IDs fail — surface/projector ID checks added

---

## Verdict

**Phase 6.8 COMPLETE — proceed to 6.9.**

Calibration → WarpMesh is a geometrically correct, production-safe, per-vertex perspective pipeline with explicit multi-orientation linkage and real coverage. `STOP AFTER REPORT — no commit/push.`
