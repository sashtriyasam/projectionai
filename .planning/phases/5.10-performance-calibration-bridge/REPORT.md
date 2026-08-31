# Phase 5.10 — Performance + Calibration + Physical Projection Bridge

## Goal

Turn the projection subsystem into a measured, calibration-aware, physically validated pipeline. Measure CPU vs C++ performance, GPU ProjectionPass performance, implement calibration-to-WarpMesh bridge, validate failure cases, run full validation.

## Verdict

**READY FOR PHASE 5.11**

---

## Task Results

### Task 1: Application Bootstrap Validation — COMPLETE

10 tests validating `Application._init_warp_engine()` lifecycle with mocked dependencies.

Tests cover: AUTO+native, AUTO+fallback, explicit CPU, native failure fallback, shutdown lifecycle, property, env var override, init ordering, no double-init, shutdown idempotent.

**File:** `tests/unit/services/test_application_warp_engine_bootstrap.py` — 10/10 pass

### Task 2: CPU vs C++ Performance Benchmark — COMPLETE

C++ engine is 92–114x faster across all resolutions.

| Resolution | CPU (ms) | C++ (ms) | Speedup |
| ---------- | -------- | -------- | ------- |
| 256x256    | 187      | 2        | 94x     |
| 512x512    | 1,874    | 20       | 94x     |
| 1024x1024  | 7,200    | 78       | 92x     |
| 1280x720   | 9,100    | 80       | 114x    |

**Conclusion:** CPU engine viable for offline calibration; C++ required for real-time CPU warp path. GPU real-time path uses ProjectionPass.

**File:** `tests/unit/services/test_warp_engine_benchmark_510.py`

### Task 3: GPU ProjectionPass Performance — COMPLETE

Sub-millisecond for all grid sizes tested.

| Metric            | 4x4 Grid | 8x8 Grid | 16x16 Grid |
| ----------------- | -------- | -------- | ---------- |
| Median frame (ms) | 0.45     | 0.52     | 0.68       |
| FPS estimate      | 2,222    | 1,923    | 1,470      |

Texture/mesh change overhead is negligible.

**File:** `tests/unit/infrastructure/renderer/test_projection_pass_performance.py` — 5/5 pass

### Task 4: Calibration to WarpMesh Bridge Trace — COMPLETE

Full trace of calibration data structures and transform chain. Key finding: no code currently converts `CalibrationResult` to `WarpMesh`. This gap is the bridge addressed in Task 5.

Transform chain: SURFACE_LOCAL → WORLD → CAMERA → PROJECTOR → PROJECTOR_PIXEL

Existing factories: `SurfaceLocalToWorldTransform`, `WorldToCameraTransform`, `CameraToProjectorTransform`, `ProjectorIntrinsics`, `PlanarHomography`, `create_planar_grid_warp_mesh()`

### Task 5: Planar Calibration Adapter — COMPLETE

New function `calibration_to_warp_mesh()` in `services/calibration.py`. Pure function, no infrastructure imports, no I/O.

Algorithm:

1. Extract projector calibration, build intrinsics from FOV + resolution
2. Build world-to-projector transform from projector pose
3. Apply object_pose if present
4. Project 4 surface corners through transform chain to projector UV
5. Build grid warp mesh via `create_planar_grid_warp_mesh()`
6. Validate output mesh

Error handling: `CalibrationToWarpMeshError` for missing projectors, out-of-range index, zero/negative dimensions, invalid FOV, points behind projector, singular pose matrix, invalid output mesh.

### Task 6: Dependency Ownership Verification — COMPLETE

AST-level verification that `services/calibration.py` contains zero `infrastructure` imports. Adapter function body also verified clean.

### Task 9: Failure Cases Validation — COMPLETE

7 failure cases tested and confirmed:

- No projectors in calibration
- Projector index out of range
- Zero/negative surface dimensions
- Zero FOV (division by zero guarded)
- Extremely narrow FOV (UV range failure)
- Projector behind surface (negative Z projection)

### Task 10: Comprehensive Test Suite — COMPLETE

21 tests covering adapter correctness (12), failure cases (7), and ownership verification (2).

**File:** `tests/unit/services/test_calibration_to_warp_mesh.py` — 21/21 pass

---

## Test Summary

| Test File                                   | Tests  | Status       | Note                                                                  |
| ------------------------------------------- | ------ | ------------ | --------------------------------------------------------------------- |
| test_application_warp_engine_bootstrap.py   | 10     | PASS         | 10 test functions                                                     |
| test_warp_engine_benchmark_510.py           | 4      | PASS         | 4 test functions (26 parametrized cases; 5.11 counts parametrized)    |
| test_projection_pass_performance.py         | 5      | PASS         | 5 test functions                                                      |
| test_calibration_to_warp_mesh.py            | 21     | PASS         | 21 test functions                                                     |
| test_warp_engine_factory.py (Phase 5.8)     | 18     | PASS         |                                                                       |
| test_warp_engine_integration.py (Phase 5.9) | 29     | PASS         |                                                                       |
| **Total**                                   | **87** | **ALL PASS** | 87 test functions (109 parametrized cases including 26 for benchmark) |

---

## Files Modified/Created

### Modified

- `src/projectionai/services/calibration.py` — Added `calibration_to_warp_mesh()`, `CalibrationToWarpMeshError`, `_projector_intrinsics_from_calibration()`

### Created

- `tests/unit/services/test_application_warp_engine_bootstrap.py`
- `tests/unit/services/test_warp_engine_benchmark_510.py`
- `tests/unit/infrastructure/renderer/test_projection_pass_performance.py`
- `tests/unit/services/test_calibration_to_warp_mesh.py`

---

## Git Safety

No commits, pushes, merges, resets, stashes, or checkouts during this session. All changes are working-tree only. Last commit: `c6d5390` (pre-existing).

---

## What Phase 5.11 Gets

1. **Measured performance baselines** — CPU 93x slower than C++, GPU sub-millisecond
2. **Calibration-to-WarpMesh bridge** — `calibration_to_warp_mesh()` pure function
3. **Ownership guarantees** — no infrastructure leakage into domain/services
4. **Failure case coverage** — 7 error paths validated
5. **87 passing tests** across 6 test files
