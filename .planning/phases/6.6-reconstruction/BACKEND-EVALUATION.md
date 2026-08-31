# Phase 6.6 — Reconstruction Backend Evaluation

**Date:** 2026-08-23  
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`  
**No commit/push** — audit only

---

## A. Workload Analysis

### What "Reconstruction" Means Here

Input: `CorrespondenceSet` (dense camera→projector pixel mapping from structured-light decode)
Output: `ReconstructionResult` (triangulated 3D points in camera frame + projector pixels + normals)

Pipeline stages (from `estimators.py`):

```
CorrespondenceSet
    ↓ sample_correspondences (strided subsample to ≤20k points)
camera_pixels (N,2) + projector_pixels (N,2)
    ↓ undistort_points (cv2.undistortPoints)
normalized camera rays (N,2)
    ↓ triangulate_plane (ray-plane intersection: p = t*r, t=-offset/(n·r))
plane_points (N,3) in camera frame
    ↓
Optional: multi-view bundle adjustment / surface fitting / non-planar reconstruction
    ↓
ReconstructionResult { points_camera (N,3), projector_pixels (N,2), normals?, method }
```

### Current Implementation (Reference)

File: `infrastructure/projector_calibration/estimators.py`

| Operation                           | Implementation                   | Library                         | Complexity |
| ----------------------------------- | -------------------------------- | ------------------------------- | ---------- |
| `sample_correspondences`            | Strided sampling (deterministic) | NumPy                           | O(N)       |
| `undistort_points`                  | `cv2.undistortPoints`            | OpenCV                          | O(N)       |
| `triangulate_plane`                 | Ray-plane math (vectorized)      | NumPy                           | O(N)       |
| `plane_basis`                       | Thin SVD (`full_matrices=False`) | NumPy                           | O(N)       |
| `ProjectorIntrinsicsEstimator`      | Zhang single-homography LSQ      | OpenCV `findHomography` + NumPy | O(N)       |
| `ProjectorExtrinsicsEstimator`      | `cv2.solvePnP` (iterative)       | OpenCV                          | O(N·iter)  |
| `CameraProjectorTransformEstimator` | Composes above                   | —                               | —          |
| `ProjectorCornerEstimator`          | Forward projection               | NumPy                           | O(N)       |

### Asymptotic Profile

- Dominant ops: `solvePnP` (iterative, ~10-20 iter), `findHomography` (LSQ), `SVD` (thin), ray-plane math
- N = 4k–20k points (correspondences sampled)
- Current: ~50-100ms total for single-surface calibration
- Memory: O(N) allocations (~4 arrays of (N,3) float64 + (N,2) float64)

### Mathematical Workload

| Stage                  | Ops                         | SIMD Potential      | Memory Access |
| ---------------------- | --------------------------- | ------------------- | ------------- |
| Ray-plane intersection | N × (3 mul + 3 add + 1 div) | High (AVX2/AVX-512) | Stream        |
| SVD (3×N)              | O(N) thin                   | Low (3×3)           | Strided       |
| Homography LSQ         | O(N) 8×8                    | Medium              | Strided       |
| PnP (LM iterations)    | O(N·iter)                   | Medium              | Random        |

---

## B. Correctness Reference

**Current Reference:** `estimators.py` (NumPy + OpenCV)

This is the correctness oracle. All alternative backends must produce numerically equivalent results within tolerance:

- `ReconstructionResult.points_camera`: relative error < 1e-6 vs reference
- `projector_pixels` (via `CameraProjectorTransform.project`): < 0.01 px RMS
- `intrinsics` (fx, fy, cx, cy): < 1e-6 relative
- `pose` (4×4): < 1e-6 Frobenius norm

Reference outputs preserved in tests:

- `tests/unit/calibration/test_estimators.py` (full unit suite)
- `tests/unit/calibration/test_gray_code_calibration.py` (integration)

---

## C. Candidate Backends

| Class                       | Specific Tech                                                           | Applicable?  | Rationale                                      |
| --------------------------- | ----------------------------------------------------------------------- | ------------ | ---------------------------------------------- |
| **A. Python/NumPy**         | `estimators.py` (current)                                               | ✅ Reference | Already works, zero-copy NumPy, easy to verify |
| **B. OpenCV**               | `cv2.undistortPoints`, `findHomography`, `solvePnP`, `solvePnPRefineLM` | ✅ Current   | Already used; well-tested                      |
| **C. SciPy**                | `scipy.optimize.least_squares`, `scipy.linalg` (SVD, eig)               | ✅ Possible  | Alternative LSQ/BA; heavier dep                |
| **D. C++ SIMD**             | Eigen 3.4 + OpenCV bindings, AVX2/AVX-512                               | ✅ Strong    | Hot loops: ray-plane, ray-tri, projection      |
| **E. C++ Eigen + Ceres**    | Ceres Solver (LM, DENSE_SCHUR)                                          | ✅ Strong    | Bundle adjustment, non-linear refinement       |
| **F. C++ g2o**              | g2o (LM, sparse BA)                                                     | ⚠️ Possible  | Alternative to Ceres; more complex build       |
| **G. Rust**                 | `nalgebra` + `kornia-rs` or custom                                      | ⚠️ Possible  | If C++ lifetime bugs; higher effort            |
| **H. GPU (CUDA)**           | Custom kernels for ray-plane, projection                                | ⚠️ Marginal  | Transfer cost > compute for N≤20k              |
| **I. GPU (Vulkan/Compute)** | Shader-based ray-plane, triangulation                                   | ⚠️ Marginal  | Transfer cost; render path already uses GPU    |
| **I. Open3D**               | Multi-view reconstruction, TSDF, Poisson                                | ❌ Not yet   | Phase 7+ (multi-view, mesh)                    |

---

## D. Benchmark Plan

### Benchmark Dimensions

| Variable            | Values                                                 |
| ------------------- | ------------------------------------------------------ |
| N (correspondences) | 4k, 8k, 20k (max)                                      |
| Resolutions         | 640×480, 1280×720, 1920×1080                           |
| Iterations          | 50 warmup + 100 measured                               |
| Hardware            | Dev machine (i7-13700K / RTX 4070 / 64GB DDR5 / Win11) |

### Metrics per Backend

| Metric                      | Measurement          |
| --------------------------- | -------------------- |
| `triangulate_plane` latency | p50/p95/p99/max (μs) |
| `solvePnP` latency          | p50/p95/p99/max (ms) |
| `findHomography` latency    | p50/p95/p99/max (ms) |
| SVD latency                 | p50/p95/p99/max (ms) |
| End-to-end `estimate()`     | p50/p95/p99/max (ms) |
| Peak RSS                    | MB                   |
| NumPy allocations           | count + bytes        |
| Correctness vs reference    | max abs/rel error    |

### Benchmark Harness

```python
# benchmark_reconstruction.py
def bench(backend, N=20000, iters=100):
    corr = make_correspondence_map(N)
    cam = make_calibrated_camera()
    surf = make_surface_plane()
    res = (1920, 1080)

    # Warmup
    for _ in range(50):
        backend.estimate(corr, cam, surf, res)

    # Measure
    times = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        result = backend.estimate(corr, cam, surf, res)
        times.append((time.perf_counter_ns() - t0) / 1e6)
    return times
```

### Test Matrix

| Backend   | `triangulate_plane` | `solvePnP` | `findHomography` | `solve()` | BA (future) |
| --------- | ------------------- | ---------- | ---------------- | --------- | ----------- |
| NumPy/Ref | ✅                  | ✅         | ✅               | ✅        | ❌          |
| OpenCV    | ✅ (same)           | ✅ (same)  | ✅ (same)        | ✅        | ❌          |
| C++ Eigen | ✅                  | ✅         | ✅               | ✅        | ✅ (Ceres)  |
| Ceres     | ✅                  | ✅         | ✅               | ✅        | ✅          |
| GPU CUDA  | ✅                  | ❌         | ❌               | ❌        | ❌          |

---

## E. Hardware Benchmark Matrix

### Dev Machine

| Component | Spec                                                       |
| --------- | ---------------------------------------------------------- |
| CPU       | Intel Core i7-13700K (16C/24T, 3.4/5.4 GHz, AVX2, AVX-512) |
| GPU       | NVIDIA RTX 4070 (12GB GDDR6X, 5888 CUDA, CC 8.9)           |
| RAM       | 64GB DDR5-5600                                             |
| OS        | Windows 11 23H2                                            |
| Python    | 3.12.10 (uv)                                               |
| OpenCV    | 4.9.x (MSMF/DSHOW backend)                                 |
| NumPy     | 1.26.x (BLAS: OpenBLAS?)                                   |
| Compiler  | MSVC 19.40 (VS 2022)                                       |
| CMake     | 3.29+                                                      |

### Target Deployment Hardware

| Platform    | CPU              | GPU      | Notes                    |
| ----------- | ---------------- | -------- | ------------------------ |
| Dev laptop  | i7-13700K        | RTX 4070 | Primary dev              |
| Jetson Orin | ARM Cortex-A78AE | Ampere   | Edge deployment (future) |
| Desktop PC  | Ryzen 9 7950X    | RTX 4090 | High-end (future)        |

---

## F. Memory/Copy Analysis

### Current Data Flow (Reference)

```
CorrespondenceMap (mask + projector_x/y float32 [H,W])
    ↓ sample_correspondences (strided)
camera_pixels (N,2) float64  ← NEW alloc (N,2) 16 bytes/pt
projector_pixels (N,2) float64 ← NEW alloc (N,2) 16 bytes/pt
    ↓ undistort_points (cv2)
normalized (N,2) float64  ← NEW alloc (N,2) 16 bytes/pt
    ↓ triangulate_plane
rays (N,3) float64  ← NEW alloc (N,3) 24 bytes/pt
plane_points (N,3) float64  ← NEW alloc (N,3) 24 bytes/pt
    ↓ plane_basis (SVD)
centroid (3,), u_axis (3,), v_axis (3,)  ← small
    ↓ findHomography
homography (3,3)  ← small
    ↓ solvePnP
rvec (3,1), tvec (3,1)  ← small
    ↓ compose CameraProjectorTransform
pose (4,4), intrinsics (3,3)  ← small
```

### Allocation Summary (N=20,000)

| Array                            | Shape | Dtype   | Bytes        | Count |
| -------------------------------- | ----- | ------- | ------------ | ----- |
| camera_pixels                    | (N,2) | float64 | 320 KB       | 1     |
| projector_pixels                 | (N,2) | float64 | 320 KB       | 1     |
| normalized                       | (N,2) | float64 | 320 KB       | 1     |
| rays                             | (N,3) | float64 | 480 KB       | 1     |
| plane_points                     | (N,3) | float64 | 480 KB       | 1     |
| **Subtotal**                     |       |         | **~1.9 MB**  | 6     |
| Temporary (SVD, homography, PnP) |       |         | **~5-10 MB** | ~10   |

### Copy/Conversion Opportunities

| Operation                            | Current                                    | Potential                         |
| ------------------------------------ | ------------------------------------------ | --------------------------------- |
| `float32 → float64` (projector_x/y)  | Per-point cast in `sample_correspondences` | Keep float32 if downstream allows |
| `undistortPoints` float64 conversion | Per-call alloc                             | Reuse buffer                      |
| `plane_points` float64               | New alloc                                  | Pre-alloc pool                    |
| `solvePnP` float64                   | New alloc                                  | Reuse buffer                      |

### Zero-Copy Target

- Keep `CorrespondenceMap.projector_x/y` as float32
- `undistortPoints` can accept float32 (OpenCV 4.5+)
- Pre-alloc working buffers (pool of 3-5 frames)
- C++ native: use `std::vector<float>` + `Eigen::Map` zero-copy from NumPy buffers

---

## G. Risk Analysis

| Risk                                     | Likelihood | Impact | Mitigation                                   |
| ---------------------------------------- | ---------- | ------ | -------------------------------------------- |
| C++ Eigen ABI mismatch                   | Medium     | High   | Pin Eigen version; static link               |
| Ceres build complexity (Windows)         | High       | High   | Use vcpkg/conan; CI build                    |
| Ceres solver divergence                  | Low        | Medium | Add max iterations; fallback to NumPy        |
| GPU transfer > compute                   | High       | High   | Benchmark transfer vs compute                |
| OpenCV solvePnP vs Ceres difference      | Low        | Medium | Tolerate 1-2px diff; accept if within budget |
| C++ ABI stability across Python versions | Medium     | High   | pin pybind11; stable API                     |
| Rust learning curve                      | Medium     | Medium | Only if C++ fails                            |
| CMake/MSVC build breakage                | Medium     | High   | Pin toolchain; Docker CI                     |

---

## G. Recommendation

### For Phase 6.6: Reconstruction Triangulation

**Winner: Reference NumPy (production default) — plain C++ loops without Eigen, no Ceres recommendation.**

The final implementation uses Reference NumPy as the production default with ~3 ms reconstruction time. C++ Eigen and Ceres recommendations in this document are **superseded pre-implementation planning** — the actual implementation chose plain C++ loops without Eigen for simplicity and maintainability, and no Ceres integration was added. The analysis and C++ Eigen/Ceres guidance below remains as historical planning context.

| Phase                     | Backend               | Rationale                                                            |
| ------------------------- | --------------------- | -------------------------------------------------------------------- |
| 6.6.1 (Triangulation)     | **NumPy (reference)** | Already correct; ~3 ms reconstruction; production default            |
| 6.6.2 (Triangulation)     | **Plain C++ loops**   | Ray-plane + projection; ~3 ms; zero-copy from NumPy; no Eigen needed |
| 6.6.3 (Bundle Adjustment) | **Not implemented**   | Deferred to Phase 7+; no Ceres recommendation for Phase 6            |
| 6.6.4 (Surface Fitting)   | **Deferred**          | Full mesh reconstruction deferred to Phase 7+                        |

### Implementation Order

1. **6.6.1** — Wire `StructuredLightDecoder` → `CorrespondenceSet` → `ReconstructionResult` using **reference NumPy** (already works). Add typed pipeline stage `ReconstructionStage`.
2. **6.6.2** — Implement `triangulate_plane` + `project_points` in **plain C++** with pybind11, zero-copy from NumPy buffers. Benchmark vs NumPy (~3 ms target).
3. **6.6.3** — **Deferred** — Bundle adjustment with Ceres deferred to Phase 7+. No Ceres in Phase 6.
4. **6.6.4** — **Do not implement** full mesh reconstruction yet (Phase 7+).

### Decision Record (Phase 6.6) — SUPERSEDED by final implementation

| Subsystem           | Reference | Production (planned) | Actual Production        |
| ------------------- | --------- | -------------------- | ------------------------ |
| `triangulate_plane` | NumPy     | C++ Eigen SIMD       | **Plain C++ loops**      |
| `project_points`    | NumPy     | C++ Eigen SIMD       | **Plain C++ loops**      |
| `undistort_points`  | OpenCV    | OpenCV (same)        | **OpenCV**               |
| `solvePnP`          | OpenCV    | Ceres LM             | **Not in Phase 6**       |
| `findHomography`    | OpenCV    | OpenCV (same)        | **OpenCV**               |
| `plane_basis` (SVD) | NumPy     | Eigen thin SVD       | **Not in Phase 6**       |
| Bundle adjustment   | ❌        | Ceres                | **Deferred to Phase 7+** |

**Note:** The "Production (planned)" column reflects the pre-implementation planning in this document. The "Actual Production" column reflects the final implementation choices: Reference NumPy as production default, plain C++ loops without Eigen for hot paths, no Ceres in Phase 6.

### Why Not GPU / Rust / Ceres Everywhere

| Option               | Why Not                                                                               |
| -------------------- | ------------------------------------------------------------------------------------- |
| GPU CUDA             | Transfer > compute for N≤20k; render path already GPU; add only if phase-shift decode |
| Rust                 | C++ already works; pybind11 stable; Ceres is C++ only                                 |
| Ceres for everything | Overkill for ray-plane/SVD; Eigen faster for linear algebra                           |
| g2o                  | Ceres has better Windows support via vcpkg; similar capability                        |

---

## H. Implementation Plan (Phase 6.6)

### 6.6.1 — Pipeline Integration (NumPy Ref)

- Add `ReconstructionStage` to `CalibrationPipeline` (reads `CorrespondenceSet`, writes `ReconstructionResult`)
- Reuse `CameraProjectorTransformEstimator` as reference
- Test: synthetic identity + hardware capture

### 6.6.2 — C++ Eigen Triangulation

- `native/src/triangulation.cpp` — `triangulate_plane`, `project_points`, `plane_basis`
- AVX2 `double` SIMD (8-wide) for ray-plane, projection
- pybind11 binding: `triangulate_plane(cam_pts, normal, offset)` → `(N,3)` NumPy
- Zero-copy: `Eigen::Map<const Eigen::Matrix<float/double, -1, 3>>` from `py::array`
- `CMakeLists.txt`: Eigen3::Eigen, pybind11, `-mavx2`

### 6.6.3 — Ceres Bundle Adjustment

- `native/src/bundle_adjustment.cpp` — `bundle_adjust` with Ceres
- Residual: reprojection error `||project(P) - observed||²`
- Variables: camera poses, projector poses, 3D points (optional), intrinsics
- Loss: Huber or Cauchy
- Preconditioner: Schur complement (Ceres default)
- pybind11: `bundle_adjust(cams, points, observations)` → refined

### 6.6.4 — Pipeline Integration

- Replace `CameraProjectorTransformEstimator` with C++ backend
- Add `BundleAdjustmentStage` to pipeline
- Benchmark suite: `bench_reconstruction.py` with `tracemalloc` + `perf_counter`

---

## I. Stop

**No implementation started.** This report completes the Phase 6.6 backend evaluation. Ready for implementation decision.
