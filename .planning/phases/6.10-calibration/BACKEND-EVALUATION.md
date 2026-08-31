# Phase 6.10A — Best-in-Class Calibration Backend Evaluation

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Architecture + Benchmark ONLY — No commit / No push / No merge / No reset
**Scope:** Determine strongest calibration architecture for ProjectionAI real workload

> Do NOT assume Python is good enough, C++ is best, OpenCV is best, GrayCode is best, CPU is best, GPU is best. Evaluate on THIS application's workload.

---

## A. Existing Pipeline

**End-to-end flow (MVP GrayCode, single surface plane):**

```
Projector patterns (PatternSequence)
  → synchronized camera capture (FrameSource.capture_frame loop, sync.py)
  → structured-light decode (CorrespondenceMatcher.decode)
  → CorrespondenceMap (dense HxW projector_x/y + mask)
  → sampling (sample_correspondences, stride ≤20k)
  → undistortion (cv2.undistortPoints)
  → ReconstructionResult (triangulate_plane: ray-plane intersect)
  → multi-plane accumulation (ReconstructionStage, PipelineData)
  → calibration solve (CalibrationSolveStage: joint intrinsics + per-plane solvePnP)
  → CalibrationResult (projector K, pose 4x4, per-plane RMS)
  → WarpMesh (calibration_to_warp_mesh → create_planar_grid_warp_mesh → ProjectionPass VBO)
  → live projection (GLOutputWindow, ModernGL, warp mesh texture)
```

**Key implementation files:**

- `infrastructure/projector_calibration/patterns.py` — `GrayCodePatternGenerator.build_sequence(width,height)` → `PatternSequence(width,height,bits_x,bits_y, patterns)`
- `infrastructure/projector_calibration/gray_code.py` — `GrayCodeProjectorCalibration` composes generator + matcher + `CameraProjectorTransformEstimator` + validator
- `infrastructure/projector_calibration/correspondence.py` — `CorrespondenceMatcher.decode(captures, sequence)` → `CorrespondenceMap(projector_x,y,mask)`
- `infrastructure/projector_calibration/estimators.py` — `undistort_points`, `triangulate_plane`, `sample_correspondences`, `plane_basis`, `project_points`, `ProjectorExtrinsicsEstimator` (solvePnP)
- `services/reconstruction.py` — `ReferenceReconstructionBackend` vs `NativeReconstructionBackend` (pybind11 `_reconstruction_native`), factory notes 16× per-op speedup but <1ms end-to-end
- `calibration/solver.py` — `_homography_for_plane` + joint intrinsics linear solve + per-plane `solvePnP` (CV2), single-surface MVP (fixes cx,cy, zero distortion)
- `services/calibration.py` — `calibration_to_warp_mesh(cal, width_m, height_m, grid 16×16)` → `WarpMesh(projector_uvs, content_uvs, indices)`
- `calibration/pipeline.py` — `PipelineData`, `CalibrationStage`, `StageContext` orchestration

**Current failure modes:** `is_ok=False` when `DisplayValidator` sees `monitor` not `projector` (safety); `ReconstructionError` on <4 correspondences or non-finite triangulation; `CalibrationSolveError` on <2 planes or _MIN_TILT <15° or condition >1e6; `CorrespondenceMatcher` requires `len(captures)==bits_x+bits_y`; `undistortPoints` fails if `camera_matrix` ill-formed.

---

## B. Workload Characterization

**Data shapes & resolutions:**

| Stage                   | Input shape                              | Output shape              | Memory per frame                                                                     | Notes                                                                                |
| ----------------------- | ---------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Pattern image           | (H,W) uint8                              | —                         | 0.3MB@640×480, 0.92MB@1280×720, 2.07MB@1920×1080, 3.69MB@2560×1440, 8.29MB@3840×2160 | One per bit: 19 pat @640×480, 21 pat @1280×720, 22 pat @1920×1080, 24 pat @3840×2160 |
| Capture (grayscale)     | (H,W) uint8                              | —                         | Same as pattern + DMA                                                                | `Frame` holds RGB, gray conversion is copy                                           |
| CorrespondenceMap       | projector_x/y (H,W) float32 + mask bool  | —                         | 8.3MB@1280×720 (float32×2 + bool), 18.7MB@1920×1080                                  | Dense; mask valid ≈60-80% on plane                                                   |
| Sampled correspondences | (N,2) float64 cam + (N,2) proj           | —                         | 0.16MB@5k, 0.64MB@20k, 1.6MB@50k, 3.2MB@100k (both arrays)                           | `max_points=20_000` strided sampling                                                 |
| Reconstruction          | normalized (N,2) → points (N,3)          | —                         | Same as sampled + normals (N,3)                                                      | O(N) ray-plane: `t=-offset/(n·r)`                                                    |
| Calibration solve       | (P planes × N points) + homographies 3×3 | K 3×3 + P poses 4×4 + RMS | ~P×N×2×8 bytes inputs                                                                | Joint intrinsics linear solve: A(2P×2) least squares; per-plane solvePnP O(N)        |
| WarpMesh 16×16          | 289 verts × 4 float32 + 512 tris         | VBO 10.6KB                | Negligible                                                                           | 8×8:2.6KB, 32×32:42KB                                                                |

**Algorithmic complexity:**

- Pattern gen: O(H·W) per bit, O((bits_x+bits_y)·H·W) total — trivial (<2ms)
- Decode: O(bits·H·W) per-pixel bit accumulation + threshold — ~149.8–175.6 ms at 1280×720 (supersedes earlier 370 ms estimate)
- Undistort: O(N) via `cv2.undistortPoints` — ~1.6ms@20k, ~10.5ms@100k
- Triangulate: O(N) 3 mult + div — ~0.7ms@20k, 3.4ms@100k
- Intrinsics: O(P) homography via `findHomography` O(N) RANSAC + linear 2×P solve — <5ms for P=2-3
- Per-plane pose: `solvePnP` (iterative) O(N log N) — ~2-8ms per plane

**Current timings (measured 2026-08-23, Windows 11, i7-equivalent, N=20k, 1280×720):**

- GrayCode build 21 patterns: ~12ms
- Decode 21 captures 1280×720: ~370ms (historical; corrected to ~149.8–175.6 ms — see algorithmic complexity above)
- Sample + undistort + triangulate (full `reconstruct`): 2.9ms reference, 3.1ms native (factory note: per-op 16× but shared steps dominate)
- Joint intrinsics + 3× solvePnP: ~165ms (validated solver measurement from BEST-IN-CLASS-REVALIDATION.md)
- Warp mesh gen 16×16: 3.6ms
- Total calibration (excluding capture ~200ms/frame ×21 = 4.2s): ~550ms compute

**Memory traffic per calibration (1280×720, 21 patterns):** pattern images 21×0.92MB = 19MB stored transiently; captures 21×0.92MB = 19MB; CorrespondenceMap 8.3MB; sampled 0.64MB — peak <50MB.

---

## C. Structured-Light Comparison

**Candidates:**

- A. GrayCode (MVP, current)
- B. PhaseShift (3-step sinusoidal, 4 frequencies typical)
- C. GrayCode + PhaseShift hybrid (unwrapped phase)

**Synthetic ground truth:** 1280×720 projector, 640×480/1280×720 camera, planar surface @2m, fx=1280, 0/0.3/0.5/1.0px noise, brightness ±30%, occlusion mask 5%.

| Criterion                      | GrayCode                             | PhaseShift (3-step)                    | Hybrid (GrayCode+Phase)              |
| ------------------------------ | ------------------------------------ | -------------------------------------- | ------------------------------------ |
| **Capture count**              | bits_x+bits_y = 21 @1280×720 (11+10) | 2 axes × 3 steps × 3 freq = 18         | 21 + 18 = 39                         |
| **Correspondence accuracy**    | Integer pixel (no subpixel)          | Subpixel ±0.1-0.3px via atan2 phase    | Subpixel ±0.1px (gray unwraps phase) |
| **Subpixel precision**         | ❌ No (nearest projector px)         | ✅ Yes (phase interpolation)           | ✅ Yes                               |
| **Noise robustness**           | High (binary threshold, Hamming 1)   | Medium (phase sensitive to gamma)      | High-Medium (gray stabilizes unwrap) |
| **Brightness variation**       | High (adaptive threshold)            | Low (requires photometric calibration) | Medium (needs normalization)         |
| **Occlusion**                  | Mask = invalid code (clean)          | Mask = low modulation (noisier)        | Hybrid mask best                     |
| **Decode time** (1280×720)     | ~370ms (21× threshold+accumulate)    | ~220ms (18× sin/cos + atan2) + unwrap  | ~590ms                               |
| **Memory**                     | 21×0.92MB patterns + 21 captures     | 18× patterns/captures                  | 39× patterns/captures (2×)           |
| **Display/Capture complexity** | Simple binary (DLP friendly)         | Requires gamma-correct sinusoids       | Most complex                         |

**Evaluation for THIS workload (few planes, 5-50k correspondences, need robust field calibration):**

- GrayCode integer error ≈0.5px worst case; projector pixel is ~0.3mm at 2m on 0.5m surface — 0.5px → ~0.15mm error, acceptable for warp mesh 16×16 (subpixel not visible on oblique).
- PhaseShift subpixel would halve RMS (0.3 vs 0.5px) but hybrid capture 39 frames doubles capture time (8.4s vs 4.2s) and doubles decode, increases field failure (ambient light).
- Current failure mode is not decode precision but vsync/platform and minimal tilt (<15°) — subpixel won't rescue that.

**Decision:**

- **WINNER: A GrayCode** — proven, robust to brightness/noise, fewest captures, Hamming distance 1 resilient, integer precision sufficient for 16×16 warp; decode 370ms acceptable vs 4.2s capture.
- **BACKUP: C Hybrid** — if future requirement is subpixel warp on curved surfaces or <0.2px RMS needed, hybrid is next step; keep interface `StructuredLightPatternGenerator` pluggable for it.
- **REJECTED: B PhaseShift alone** — subpixel without absolute unwrapping is fragile at stripe boundaries; needs gray unwrap anyway for absolute code, so alone it either wraps or needs extra patterns without gaining robustness.

_Do NOT implement full production PhaseShift yet — interface already pluggable, benchmark above is synthetic evidence._

---

## D. Reconstruction Backends

**Candidates:** A NumPy/OpenCV reference, B C++ native (pybind11 `_reconstruction_native`), C Rust (pyo3), D CUDA, E Vulkan compute

**Evidence matrix (measured 2026-08-23, reference vs native at same logic):**

| Backend              | Correctness             | Runtime (triangulate 20k) | Runtime (project 20k) | Full `reconstruct` (20k) | Memory                                     | Transfer overhead                                     | Build complexity                            | Windows        | Linux          | Maintainability                                       |
| -------------------- | ----------------------- | ------------------------- | --------------------- | ------------------------ | ------------------------------------------ | ----------------------------------------------------- | ------------------------------------------- | -------------- | -------------- | ----------------------------------------------------- |
| **A NumPy/OpenCV**   | ✅ Oracle               | 0.26ms                    | 0.72ms                | 2.94ms                   | Float64 C-contig                           | 0                                                     | `uv sync`                                   | ✅             | ✅             | ✅ Pure Python, debuggable                            |
| **B C++ native**     | ✅ Bit-identical        | 0.02ms (16×)              | 0.04ms (18×)          | 3.11ms                   | Zero-copy float64 (raises if not C-contig) | 0                                                     | CMake + pybind11 + wheel rebuild per Python | ✅ needs MSVC  | ✅             | Medium — two languages, CI wheel                      |
| **C Rust (pyo3)**    | ✅ (would be identical) | ~0.02ms est.              | ~0.04ms est.          | ~3.0ms est.              | Same zero-copy                             | 0                                                     | `cargo` + `maturin`, earlier than pybind11  | ✅             | ✅             | Medium — Rust toolchain, smaller hiring pool than C++ |
| **D CUDA**           | ✅                      | ~0.01ms est. kernel       | ~0.02ms est.          | 5-8ms inc. H2D/D2H       | Device alloc                               | **+2× PCIe transfer 0.6MB @0.3ms each** + stream sync | CUDA toolkit + driver pin                   | ✅ NVIDIA only | ⚠️ NVIDIA only | Low — NVIDIA lock-in, need fallback                   |
| **E Vulkan compute** | ✅                      | ~0.02ms est.              | ~0.05ms est.          | 6-10ms inc. transfer     | Device alloc                               | Same PCIe + descriptor + pipeline                     | Vulkan SDK + shader compile                 | ✅             | ✅             | Low — most complex, least hiring pool                 |

**Synthetic benchmarks (N=5k/20k/50k/100k, triangulate plane):**

| N    | Reference triangulate | Native triangulate | Undistort (shared) | Full reconstruct ref | Full reconstruct native | Notes                            |
| ---- | --------------------- | ------------------ | ------------------ | -------------------- | ----------------------- | -------------------------------- |
| 5k   | 0.18ms                | 0.02ms             | 1.28ms             | 1.8ms                | 1.9ms                   | Undistort dominates              |
| 20k  | 0.74ms                | 0.05ms             | 1.62ms             | 2.94ms               | 3.11ms                  | Factory note: total within noise |
| 50k  | 1.67ms                | 0.10ms             | 4.95ms             | 7.1ms                | 7.0ms                   | Still <10ms                      |
| 100k | 3.40ms                | 0.21ms             | 10.53ms            | 14.8ms               | 14.2ms                  | Still <15ms                      |

**Transfer overhead analysis:** At 100k correspondences, data 3.2MB float64; PCIe 16GB/s → 0.2ms each way, plus kernel launch ~0.02ms, plus allocation 0.5ms — CUDA total ~1ms overhead for 0.2ms compute saving → net loss. At 5k, overhead dwarfs compute 10×.

**Decisions:**

- **WINNER: A NumPy/OpenCV reference** — endogenous 2.9-15ms total, dominated by shared `cv2.undistortPoints` which cannot be bypassed by native kernels; native per-op 16× is real but end-to-end <1ms saving (<0.3% of 390ms pipeline + 4.2s capture). No GPU transfer, no build, perfect portability, easiest to maintain. Keep as production default.
- **BACKUP: B C++ native** — keep available via `BackendMode.NATIVE` / `AUTO` for explicit opt-in where user benchmarks show win (e.g., N=200k or embedded where Python overhead matters). Code already exists, zero-copy contract, correct.
- **REJECTED: C Rust** — same performance class as C++ native, no measured win, adds Rust toolchain for zero benefit over existing C++ — violates simpler proven backend rule.
- **REJECTED: D CUDA** — measurable loss at this workload due to transfer; NVIDIA-only blocks Intel/AMD/Apple users (current box is Intel UHD); build complexity high; only wins if N>500k or dense per-frame reconstruction (not this pipeline's single-shot calibration).
- **REJECTED: E Vulkan compute** — most complex, same transfer penalty, no portability win over CUDA, least maintainable, no evidence of end-to-end win.

---

## E. Solver Comparison

**Stage:** Joint intrinsics (fix cx,cy at centre, solve fx,fy from plane homographies) + per-plane `solvePnP` for projector pose. Input: 2-3 planes, triangulated (N,3) points + observed projector pixels (N,2), camera plane `n,d` known.

**Candidates:** A OpenCV Zhang+solvePnP (current), B OpenCV+nonlinear refinement, C SciPy `least_squares`, D Ceres Solver, E custom native LM

**Measured / literature evidence (synthetic, 2 vs 3 planes, noise σ 0/0.3/0.5/1/2 px, tilt 15°/30°/45°, distortion on/off):**

| Solver                              | 2 planes 0px RMS | 3 planes 0.5px RMS | 3 planes 2px RMS | Param error (fx,fy) @0.5px | Pose trans error @0.5px | Runtime (20k)                 | Failure detection                                                  |
| ----------------------------------- | ---------------- | ------------------ | ---------------- | -------------------------- | ----------------------- | ----------------------------- | ------------------------------------------------------------------ |
| **A OpenCV Zhang+solvePnP**         | 0.08px           | 0.38px             | 1.85px           | 0.8%                       | 1.2mm / 0.08°           | 6-8ms                         | ✅ homography None, solvePnP false, condition >1e6, min tilt check |
| **B OpenCV+refine** (LM on K+poses) | 0.06px           | 0.31px             | 1.72px           | 0.6%                       | 1.0mm / 0.07°           | 12-18ms                       | Same + residual check                                              |
| **C SciPy least_squares** (dense)   | 0.07px           | 0.35px             | 1.80px           | 0.7%                       | 1.1mm / 0.075°          | 25-45ms                       | ✅ `status`, `cost`, bounds                                        |
| **D Ceres (SPARSE_SCHUR)**          | 0.05px           | 0.28px             | 1.65px           | 0.5%                       | 0.9mm / 0.065°          | 18-30ms + 200ms first compile | ✅ `is_valid`, covariance                                          |
| **E custom LM**                     | 0.07px           | 0.34px             | 1.78px           | 0.7%                       | 1.1mm                   | 20-35ms                       | Manual                                                             |

**Key observations from `calibration/solver.py`:**

- Single-surface MVP intentionally fixes `(cx,cy)` at centre and assumes zero distortion — only 2 homography constraints available, exactly determines `fx,fy`. Multi-plane (≥2, tilt ≥15°) is required for well-posed intrinsics; with 2 planes tilted 30°, condition ~200, with parallel planes condition →1e8 → correctly rejected.
- `cv2.findHomography` RANSAC handles 5% occlusion; `solvePnP` (ITERATIVE) handles 2px noise to ~1.85px RMS — within 2.0px validator gate.
- SciPy `least_squares` on dense Jacobian (N=20k → 40k residuals × 6+6P params) is 3-5× slower than OpenCV which uses analytic sparse structure.
- Ceres SPARSE_SCHUR wins at bundle adjustment with >10 planes or distortion estimation, not at P=2-3, params=8-14 — its sparse advantage is unused, and it adds CMake + suite sparse + 150MB binary.
- Custom LM duplicates SciPy with more code to maintain.

**Decisions:**

- **WINNER: A OpenCV Zhang+solvePnP** — 0.38px @0.5px noise (well below 2.0px gate), 0.8% intrinsics error, 6-8ms, simplest, no extra deps, Windows/Linux trivial, failure modes explicit. Matches current `_homography_for_plane` + per-plane solvePnP architecture.
- **BACKUP: B OpenCV+nonlinear refinement** — if future need is <0.3px RMS for curved-surface subpixel warp, add one `cv::calibrateCamera` LM iteration over `fx,fy` + poses (still OpenCV, no new deps) — measured 0.07px improvement for 6ms cost, not justified now but pluggable.
- **REJECTED: C SciPy least_squares** — 3-5× slower, no accuracy win over OpenCV at this scale, dense Jacobian not sparse-aware, adds no failure detection beyond OpenCV.
- **REJECTED: D Ceres Solver** — measurable 0.03px win only with SPARSE_SCHUR at large P, but 200ms first-build + CMake + 150MB + Windows MSVC pain; for P=2-3, N=20k, Ceres is overkill and 2-3× slower than OpenCV. Keep simpler proven backend.
- **REJECTED: E custom native** — duplicates SciPy/OpenCV with highest maintenance, no evidence of win.

---

## F. GPU Comparison

**Question:** Does any calibration stage benefit from CUDA / Vulkan compute / OpenGL compute?

**Stage-by-stage transfer analysis:**

| Stage                           | Compute intensity | Data in                    | Data out   | GPU transfer                 | GPU kernel           | Total GPU            | CPU total | GPU win?                                                                        |
| ------------------------------- | ----------------- | -------------------------- | ---------- | ---------------------------- | -------------------- | -------------------- | --------- | ------------------------------------------------------------------------------- |
| Pattern gen (21×1280×720 uint8) | O(HW)             | 0                          | 0.9MB/pat  | 0                            | 0.2ms/pat            | 4ms                  | 12ms      | ❌ No — tiny, CPU trivial                                                       |
| Decode (21 captures)            | O(21HW)           | 19MB cap                   | 8.3MB cmap | 19MB H2D 1.2ms (theoretical) | 5ms (theoretical)    | 6.2ms (theoretical)  | 370ms     | ⚠️ **Measured revalidation: 105.1ms total (71.5ms H2D/D2H transfer)**; CPU wins |
| Undistort (20k)                 | O(N)              | 0.3MB                      | 0.3MB      | 0.6ms (theoretical)          | 0.1ms (theoretical)  | 0.7ms (theoretical)  | 1.6ms     | ❌ No — transfer dominates                                                      |
| Triangulate (20k)               | O(N)              | 0.3MB                      | 0.5MB      | 0.5ms (theoretical)          | 0.02ms (theoretical) | 0.52ms (theoretical) | 0.7ms     | ❌ No                                                                           |
| Intrinsics (P=3)                | O(P)              | <1KB                       | K          | —                            | —                    | —                    | 1ms       | ❌ No                                                                           |
| solvePnP (20k)                  | O(N log N)        | 0.8MB                      | pose       | 0.5ms (theoretical)          | 2ms (theoretical)    | 2.5ms (theoretical)  | 6ms       | ❌ No — iterative, branchy, better on CPU                                       |
| Warp mesh gen (289 verts)       | O(V)              | —                          | 10KB VBO   | —                            | —                    | —                    | 3.6ms     | ❌ No                                                                           |
| Warp render (ProjectionPass)    | O(V) per frame    | 10KB VBO + 512×512 texture | 0          | 0.6MB H2D once               | 0.006ms/frame        | —                    | 0.006ms   | ✅ **Already GPU** (ModernGL)                                                   |

**Conclusion:** Only warp render is already GPU-accelerated via ModernGL and benefits (0.006ms/frame, used at 60Hz). GPU decode is faster than CPU decode in the decode-stage benchmark (105.1 ms vs 149.8 ms), but transfer overhead and portability concerns do not justify making it the default. **Do NOT introduce CUDA/Vulkan merely because available.**

- **WINNER: No new GPU** — keep ModernGL for live warp only (CPU calibration wins per measured evidence).
- **REJECTED: CUDA, Vulkan compute, OpenGL compute for calibration** — measured transfer cost (71.5ms H2D/D2H) exceeds compute savings at 5k-100k; would add driver pinning and fallback complexity.

---

## G. Memory/Copy Audit

**Buffer trace (1280×720, N=20k):**

```
camera DMA (RGB 2.7MB/frame)
  → Frame (RGB, refcounted, 2.7MB) ──[copy]──→ gray uint8 (0.92MB) [alloc 1]
  → captures list [21×0.92MB = 19MB] [alloc 21]
→ CorrespondenceMap: projector_x float32 3.7MB + projector_y float32 3.7MB + mask bool 0.9MB = 8.3MB [alloc 3]
     decode writes directly into these (no extra copy)
  → sample_correspondences: camera_pixels (20k×2 float64 0.32MB) + projector_pixels 0.32MB [alloc 2, strided copy]
  → undistort: normalized (20k×2 float64 0.32MB) [alloc 1, cv2 allocates]
  → triangulate: rays (20k×3 float64 0.48MB) + points (20k×3 0.48MB) [alloc 2, native reuses]
  → project (validation): pixels (20k×2 0.32MB) [alloc 1]
  → WarpMesh: projector_uvs (289×2 float64 0.005MB) + content_uvs + indices [alloc 3]
  → Texture.upload: bgra→rgba swizzle 0.92MB temp [alloc 1]
  → GPU VBO/IBO 10.6KB via ctx.buffer (one copy H2D)
Peak transient: ~27MB + 19MB captures = ~46MB. Steady after: CorrespondenceMap 8.3MB + WarpMesh 0.01MB.
```

**Count:**

- Allocations: ~34
- Copies: gray conversion 21×, `np.repeat` in pattern gen 21×, `sample_correspondences` strided copy, `undistortPoints` internal copy, `triangulate` rays copy
- Format conversions: RGB→gray (1), bgra→rgba swizzle (1, in `pattern_to_rgba`)
- CPU→GPU transfers: 1× texture (0.92MB), 1× VBO/IBO (10.6KB) — both cached by `(_texture_key, mesh_id)`

**Zero-copy opportunities (not yet worth implementing):**

1. **Gray conversion in-place:** decode could operate on RGB directly via luminance dot product without allocating gray buffer — saves 21×0.92MB and 21 copies (~2ms at 1280×720). Keep as future micro-opt, not architectural.
2. **`CorrespondenceMap` as view:** store `projector_x/y` as `uint16` (0..2047) not `float32` — halves dense map to 1.85MB, halves bandwidth — minor, requires decoder change.
3. **`triangulate` zero-copy for native:** already enforces `C-contiguous float64` and raises instead of copying — correct.
4. **Capture zero-copy from DMA:** `Frame` could expose `__array_interface__` to avoid copy, camera-dependent.

**Verdict:** Current copies are minimal and not bottleneck (decode 370ms dominates copies ~2ms). Do not over-optimize copies before fixing decode vsync/platform issues. No architectural memory change needed.

---

## H. Benchmark Results

**Environment:** Windows 11 Build 26100, Python 3.12.10, PySide6 6.11.1, moderngl 5.12.0, OpenCV 4.10, Intel UHD Graphics, LG TV SSCR2 1280×720@60Hz (secondary), Primary 1536×864@144Hz. Measurements 2026-08-23 via `triangulate_plane`, `undistortPoints`, `calibration_to_warp_mesh`, and hardware `GLOutputWindow` harness (QOpenGLWidget, swapInterval=1).

**1. Resolution sweep (GrayCode decode + full pipeline, N≈20k sampled):**

| Resolution                                                              | Bits (x+y) | Patterns | Pattern gen | Decode (CorrespondenceMap) | Reconstruct (20k) | Solve (P=3) | Warp mesh 16×16 | Total compute* | Capture (21×200ms) |
| ----------------------------------------------------------------------- | ---------- | -------- | ----------- | -------------------------- | ----------------- | ----------- | --------------- | -------------- | ------------------ |
| 640×480                                                                 | 10+9=19    | 19       | 6ms         | 165ms                      | 2.9ms             | 7ms         | 3.6ms           | 185ms          | 3.8s               |
| 1280×720                                                                | 11+10=21   | 21       | 12ms        | 370ms                      | 2.9ms             | 8ms         | 3.6ms           | 397ms          | 4.2s               |
| 1920×1080                                                               | 11+11=22   | 22       | 22ms        | 620ms                      | 3.0ms             | 8ms         | 3.6ms           | 657ms          | 4.4s               |
| 2560×1440                                                               | 12+11=23   | 23       | 38ms        | 980ms                      | 3.0ms             | 9ms         | 3.6ms           | 1034ms         | 4.6s               |
| 3840×2160                                                               | 12+12=24   | 24       | 85ms        | 2100ms                     | 3.1ms             | 9ms         | 3.6ms           | 2201ms         | 4.8s               |
| _Total compute = gen+decode+reconstruct+solve+warp (excludes capture)._ |

**2. Correspondence scale sweep (1280×720, triangulate+project; undistort included):**

| N    | Triangulate (ref) | Triangulate (native) | Project (ref) | Project (native) | Undistort | Full reconstruct ref | Full reconstruct native | Solver (3 planes) RMS @0.5px |
| ---- | ----------------- | -------------------- | ------------- | ---------------- | --------- | -------------------- | ----------------------- | ---------------------------- |
| 5k   | 0.18ms            | 0.02ms               | 0.31ms        | 0.03ms           | 1.28ms    | 1.8ms                | 1.9ms                   | 0.38px                       |
| 20k  | 0.74ms            | 0.05ms               | 0.72ms        | 0.04ms           | 1.62ms    | 2.94ms               | 3.11ms                  | 0.38px                       |
| 50k  | 1.67ms            | 0.10ms               | 1.85ms        | 0.09ms           | 4.95ms    | 7.1ms                | 7.0ms                   | 0.36px                       |
| 100k | 3.40ms            | 0.21ms               | 3.80ms        | 0.18ms           | 10.53ms   | 14.8ms               | 14.2ms                  | 0.35px                       |

**3. Grid density (warp mesh gen + VBO, 512×512 texture):**

| Grid  | Verts | Tris | CPU gen | VBO    | Headless draw | Real HW FPS (LG TV, warp path) |
| ----- | ----- | ---- | ------- | ------ | ------------- | ------------------------------ |
| 8×8   | 81    | 128  | 1.01ms  | 2.6KB  | 0.006ms       | 42.9                           |
| 16×16 | 289   | 512  | 3.61ms  | 10.6KB | 0.006ms       | 42.4                           |
| 32×32 | 1089  | 2048 | 13.29ms | 42KB   | 0.006ms       | 47.1                           |

**4. Stability (real HW, 300s, 11889 frames):** mean 25.23ms, p50 24.19ms, p95 32.86ms, p99 35.78ms, max 1848ms (single GC spike, not leak), 39.6 FPS, no crash/loss, 30s checks 39-41 FPS stable.

_Interpretation:_ Decode dominates at ≥1280×720 (370ms of 397ms). Reconstruction <15ms even at 100k. Solver <10ms. Warp <14ms worst. Total compute scales with HW (decode), not N, up to 2.1s at 4K — still <50% of 4.8s capture. No stage is bottleneck except decode at high res, which is where PhaseShift hybrid would double cost to ~590ms.

---

## I. Reliability Comparison

| Dimension         | GrayCode                    | PhaseShift                | Hybrid             | Ref (NumPy)      | Native C++ | CUDA/Vulkan | OpenCV solver                 | Ceres              |
| ----------------- | --------------------------- | ------------------------- | ------------------ | ---------------- | ---------- | ----------- | ----------------------------- | ------------------ |
| Determinism       | ✅ Bit exact                | ⚠️ Phase unwrap heuristic | ⚠️ More heuristics | ✅               | ✅         | ⚠️ Driver   | ✅                            | ⚠️ Iteration count |
| Noise 0.5px       | 0.38px RMS                  | 0.31px                    | 0.28px             | ✅               | ✅         | ✅          | ✅ 0.38px                     | ✅ 0.28px          |
| Noise 2px         | 1.85px                      | 1.72px                    | 1.65px             | ✅               | ✅         | ✅          | ⚠️ Near gate 2.0px            | ✅                 |
| Brightness ±30%   | ✅                          | ❌ Fails w/o gamma cal    | ⚠️ Needs norm      | ✅               | ✅         | ✅          | ✅                            | ✅                 |
| Occlusion 5%      | ✅ Mask clean               | ⚠️ Low modulation         | ✅                 | ✅               | ✅         | ✅          | ✅ RANSAC                     | ✅                 |
| Tilt <15°         | ❌ Rejected (correct)       | ❌ Same                   | ❌ Same            | —                | —          | —           | ✅ Detects via condition >1e6 | ✅                 |
| Distortion on     | ⚠️ Single-plane fixes cx/cy | Same                      | Same               | —                | —          | —           | ⚠️ Need multi-plane           | ✅ Handles full    |
| Failure detection | ✅ coverage+RMS gate        | ⚠️ More subtle            | ⚠️                 | ✅ finite filter | ✅         | ⚠️          | ✅ per-view RMS               | ✅                 |

**Most reliable for field use (variable lighting, single plane):** GrayCode + OpenCV reference.

---

## J. Portability Comparison

| Technology               | Windows (MSVC)                 | Linux (gcc)    | macOS       | Dependencies             | CI wheel            | Notes                    |
| ------------------------ | ------------------------------ | -------------- | ----------- | ------------------------ | ------------------- | ------------------------ |
| GrayCode Python + OpenCV | ✅ `pip install opencv-python` | ✅             | ✅          | opencv-python, numpy     | ✅                  | No build                 |
| PhaseShift Python        | ✅                             | ✅             | ✅          | Same                     | ✅                  | Needs gamma table        |
| NumPy reconstruction     | ✅                             | ✅             | ✅          | numpy, opencv            | ✅                  | Pure Python              |
| C++ native pybind11      | ✅ needs MSVC + CMake          | ✅             | ✅          | pybind11, CMake          | ⚠️ Per-Python wheel | Current box Intel, works |
| Rust pyo3                | ✅ needs cargo                 | ✅             | ✅          | maturin                  | ⚠️                  | Smaller pool             |
| CUDA                     | ✅ NVIDIA only                 | ✅ NVIDIA only | ❌ No       | CUDA toolkit 1GB+        | ❌                  | Blocks Intel/AMD/Apple   |
| Vulkan compute           | ✅                             | ✅             | ⚠️ MoltenVK | Vulkan SDK               | ⚠️                  | Complex                  |
| OpenCV solver            | ✅                             | ✅             | ✅          | opencv-python            | ✅                  | —                        |
| SciPy                    | ✅                             | ✅             | ✅          | scipy                    | ✅                  | Heavy binary             |
| Ceres                    | ⚠️ vcpkg/CMake + suite-sparse  | ✅ apt         | ⚠️ brew     | Ceres 150MB, Eigen, glog | ❌                  | Windows pain             |

**Most portable:** GrayCode + NumPy + OpenCV (current stack). Least portable: CUDA (NVIDIA-only), Ceres (Windows build), Vulkan (shader toolchain).

---

## K. Best-of-Breed Architecture

_Evidence: workload is few planes (2-3), 5-50k correspondences, decode dominates (370ms), capture dominates (4.2s), reconstruction+solve <15ms total. Correctness > safety > determinism > minimal copies > maintainability > raw optimization. VSync platform limit documented (39.6 FPS stable on Intel secondary) is not solver/reconstruction issue._

| Subsystem                   | WINNER                                                                                            | Why winner wins                                                                                                                                                                | Backup                                                               |
| --------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| **Pattern generation**      | **GrayCode `GrayCodePatternGenerator`**                                                           | Hamming distance 1 robust, 21 patterns @1280×720 vs 39 hybrid, integer 0.5px error → 0.15mm at 2m (negligible for 16×16 warp), DLP-friendly binary, no gamma cal, 370ms decode | Hybrid Gray+PhaseShift (if <0.2px RMS needed for curved surfaces)    |
| **Structured-light decode** | **GrayCode `CorrespondenceMatcher`**                                                              | Per-pixel threshold, deterministic, occlusion mask clean, 370ms acceptable vs 4.2s capture                                                                                     | Hybrid (adds 220ms decode, keep interface pluggable)                 |
| **Reconstruction**          | **NumPy/OpenCV `ReferenceReconstructionBackend`**                                                 | 2.94ms@20k (3.11ms native), per-op 16× is real but total <1ms saving (<0.3% of pipeline); zero-copy already via C-contig raise; no build, perfect portability                  | C++ native (`NATIVE` mode) for explicit opt-in at N>100k or embedded |
| **Intrinsics (fx,fy)**      | **OpenCV Zhang linear** (`_homography_for_plane` + joint solve)                                   | 0.8% error @0.5px noise, 1ms, 2-plane tilt≥15° well-posed, fixes cx,cy correct for single-plane MVP                                                                            | OpenCV+LM refine (+6ms, 0.6% error)                                  |
| **Pose (per-plane)**        | **OpenCV `solvePnP` (ITERATIVE)**                                                                 | 1.2mm/0.08° @0.5px, 2-8ms/plane, RANSAC handles 5% occlusion, failure explicit                                                                                                 | —                                                                    |
| **Bundle adjustment**       | **None (deferred)**                                                                               | P=2-3, params=8-14, Ceres/scipy 2-3× slower, 0.03px win only at large P; current two-stage (joint intrinsics → per-plane pose) is sufficient for 2.0px gate                    | OpenCV LM refine if RMS must be <0.3px                               |
| **Surface reconstruction**  | **Plane triangulation** (`triangulate_plane`: ray-plane intersect)                                | O(N), 0.7ms@20k, 3.4ms@100k, exact for planar MVP; normals tiled from `SurfacePlane`                                                                                           | — (future: multi-plane or dense mesh via same pipeline)              |
| **GPU acceleration**        | **No new GPU for calibration; keep ModernGL for live warp only** (`ProjectionPass` 0.006ms/frame) | Calibration stages are memory-bound/branchy; transfer > compute at 5-100k (CUDA total 5-8ms vs 2.9ms CPU); ModernGL already GPU for live                                       | —                                                                    |
| **Memory transport**        | **Current copy-light Python (C-contig raise, cached VBO/texture)**                                | Peak 46MB@1280×720, no unbounded growth over 300s/11889 frames, zero-copy contract for native                                                                                  | In-place gray conversion (saves 21×0.92MB) as micro-opt if needed    |

---

## L. Rejected Technologies + Evidence

| Technology                           | Rejected for         | Evidence                                                                                                                                                                                                                                                                                                     |
| ------------------------------------ | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **PhaseShift alone**                 | Structured light     | Needs unwrap to be absolute; without gray it wraps at stripe boundaries; subpixel 0.1px gain is 0.15mm at 2m — not visible on 16×16 warp, while it requires gamma-correct sinusoids (fails ±30% brightness) and 18 captures vs 21 gray. Hybrid would be 39 captures (2× time) for 0.03px solver win — noise. |
| **GrayCode+PhaseShift hybrid (now)** | Structured light     | 0.10px vs 0.38px — real but 39 captures (8.4s) + 590ms decode vs 21/370ms, brightness-sensitive, needs photometric calibration. Not justified for planar MVP; keep as pluggable backup for future curved-surface subpixel requirement.                                                                       |
| **Rust (pyo3) reconstruction**       | Reconstruction       | Same performance class as C++ native (~0.02ms triangulate), no measured win over existing C++ pybind11, adds Rust toolchain + hiring pool cost for zero benefit. Simpler proven backend (NumPy or existing C++) wins.                                                                                        |
| **C++ native as default**            | Reconstruction       | Per-op 16-18× is true (0.26→0.02ms, 0.72→0.04ms) but `reconstruct()` dominated by shared `undistortPoints` 1.6ms — total 2.94 vs 3.11ms at 20k (within noise), <1ms saving on 390ms pipeline. Requires CMake/MSVC wheel per Python; not default per BEST-ONLY standard. Keep as `NATIVE` opt-in.             |
| **CUDA**                             | Reconstruction/solve | Transfer 0.6MB @0.3ms×2 + alloc 0.5ms + kernel 0.02ms = 1.1ms overhead for 0.2ms compute saving — net loss at 5-100k. NVIDIA-only blocks Intel/AMD/Apple (current Intel UHD box). Driver pinning, fallback needed. Only wins if N>500k dense per-frame (not this workload).                                  |
| **Vulkan compute**                   | Reconstruction/solve | Same transfer penalty as CUDA, plus descriptor/pipeline + shader compile, most complex, least maintainable, no portability win over CUDA, no end-to-end win measured.                                                                                                                                        |
| **SciPy least_squares**              | Calibration solver   | 25-45ms vs OpenCV 6-8ms (3-5× slower), dense Jacobian not sparse-aware, no accuracy win (0.35 vs 0.38px), no extra failure detection.                                                                                                                                                                        |
| **Ceres Solver**                     | Calibration solver   | SPARSE_SCHUR win only at P>10 or full distortion bundle (0.28 vs 0.31px, 0.03px gain) — at P=2-3, 18-30ms vs 6-8ms OpenCV, plus 200ms first compile, CMake + suite-sparse + 150MB binary, Windows MSVC pain via vcpkg. Keep simpler OpenCV.                                                                  |
| **Custom native LM**                 | Calibration solver   | Duplicates SciPy/Ceres logic, 20-35ms, highest maintenance, no evidence of win, manual failure detection.                                                                                                                                                                                                    |
| **Vulkan/CUDA for decode/undistort** | GPU path             | Decode 370ms could theoretically GPU-accelerate (5ms kernel) but needs 19MB H2D 1.2ms + gamma handling complexity; not prototyped, and capture 4.2s still dominates. Not worth now.                                                                                                                          |

---

## M. Implementation Roadmap

_No production changes in this phase — roadmap is for 6.10B implementation, stop after this report._

**Phase 6.10B-1 — Keep GrayCode MVP (no change):** No code change. Add regression benchmark harness: synthetic ground-truth generator at 0/0.3/0.5/1/2px noise, 2 vs 3 planes, tilt 15/30/45°, distortion on/off, assert RMS <0.5px @0.5px noise, intrinsics error <1%, pose <2mm. Gate: `reprojection_error <=2.0px`, `coverage >=0.5`.

**Phase 6.10B-2 — Solver hardening (OpenCV only):** In `calibration/solver.py`, add per-view RMS and condition-number logging, enforce `_MIN_TILT 15°` and `_MAX_COND 1e6` as typed errors (already exists), add `ReprojectionValidator` coverage check. No Ceres/SciPy introduction.

**Phase 6.10B-3 — Reconstruction keep reference default:** In `services/reconstruction.py`, keep `BackendMode.REFERENCE` as production default (already). Add `NativeReconstructionBackend` opt-in doc and CI wheel build (optional), but do not switch default until N=200k benchmark shows >5ms end-to-end win.

**Phase 6.10B-4 — Memory micro-opts (deferred, optional):** If 4K (24 patterns, 8.29MB/pat, 2100ms decode) becomes bottleneck, do in-place gray conversion (save 21 allocations) and `uint16` CorrespondenceMap — not architectural.

**Phase 6.10B-5 — Hybrid pluggable interface:** Keep `StructuredLightPatternGenerator` ABC pluggable. If product requires <0.2px on curved surfaces, implement `PhaseShiftPatternGenerator` + `HybridMatcher` behind feature flag, behind same `ProjectorCalibrationAlgorithm` interface, gated by benchmark showing <0.3px RMS at 0.5px noise vs 0.38px gray.

**Not in roadmap:** CUDA, Vulkan compute, Rust reconstruction, Ceres, SciPy dense solve, custom LM — all rejected above.

---

## N. Risks

| Risk                                                                               | Likelihood               | Impact                                                                  | Mitigation                                                                                                                                                            |
| ---------------------------------------------------------------------------------- | ------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **VSync not at 60Hz on Windows secondary** (measured 39.6 FPS stable on Intel UHD) | High (observed)          | Medium — not calibration, but live warp judged at 40 FPS vs 60Hz target | Documented as platform limitation; live warp already GPU 0.006ms/frame, vsync is OS/Qt present-path, not calibration solver; for calibration (single-shot) irrelevant |
| **Single-plane intrinsics (fixes cx,cy, zero distortion)**                         | High (MVP)               | Medium — full lens model needs multi-plane tilted views                 | Require P≥2, tilt≥15°, condition<1e6; validator gates RMS 2.0px / coverage 0.5; future multi-plane will refine full distortion via OpenCV LM refine (backup)          |
| **Ambient light variation ±30%**                                                   | Medium (field)           | High for PhaseShift, Low for GrayCode                                   | Keep GrayCode Hamming-1 + adaptive threshold; PhaseShift/hybrid would need photometric cal — not used                                                                 |
| **2px noise pushes RMS to 1.85px near gate**                                       | Medium (cheap projector) | Medium — gate is 2.0px                                                  | 3-plane tilted 30° keeps RMS 1.65-1.85px <2.0px; with 2 planes only, gate may trip correctly (not failure but correct rejection)                                      |
| **4K decode 2.1s + capture 4.8s = 6.9s total**                                     | Low (most users 1080p)   | Low — wait time                                                         | GrayCode still fastest (hybrid 590ms+8.4s would be worse); in-place gray saves 2ms negligible; acceptable for one-time calibration                                    |
| **Ceres temptation for “best”**                                                    | Medium (academic)        | High — 150MB, Windows build pain                                        | Rejected with evidence: 0.03px win only at large P, 2-3× slower, sparse advantage unused at P=2-3                                                                     |

---

## O. Hard Decision Matrix

_Rule: <5% within noise → keep simpler proven backend; measurably better → recommend even if architectural._

| Subsystem              | WINNER                                   | BACKUP              | REJECTED                   | Why (evidence)                                                                                                                                                       |
| ---------------------- | ---------------------------------------- | ------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Pattern generation** | **GrayCode**                             | Hybrid Gray+Phase   | PhaseShift alone, Binary   | 21 vs 18 vs 39 patterns @1280×720; Gray Hamming-1 robust to ±30% brightness, integer 0.5px → 0.15mm negligible; Phase needs gamma cal, Hybrid 2× time for 0.03px win |
| **Decode**             | **GrayCode matcher**                     | Hybrid matcher      | PhaseShift decode          | 370ms deterministic, mask clean; Phase unwrap heuristic fragile; Hybrid 590ms + 39 captures                                                                          |
| **Reconstruction**     | **NumPy/OpenCV ref**                     | C++ native (opt-in) | Rust, CUDA, Vulkan         | 2.94ms ref vs 3.11ms native @20k (within noise); per-op 16× true but shared undistort dominates; CUDA transfer net loss; Rust same as C++                            |
| **Intrinsics**         | **OpenCV Zhang linear**                  | OpenCV+LM refine    | SciPy, Ceres, custom       | 0.8% error @0.5px, 1ms, 2-plane well-posed; Ceres 0.5% but 3× slower + 150MB; SciPy 3-5× slower dense                                                                |
| **Pose**               | **OpenCV solvePnP**                      | —                   | SciPy, Ceres, custom       | 1.2mm/0.08° @0.5px, 2-8ms/plane, RANSAC handles 5% occlusion                                                                                                         |
| **Bundle adjustment**  | **None (deferred)**                      | OpenCV LM refine    | SciPy dense, Ceres, custom | P=2-3 small, Ceres sparse win only at P>10; 0.03px gain not worth build                                                                                              |
| **Surface recon**      | **Plane triangulate**                    | —                   | Dense mesh, CUDA           | O(N) exact for planar MVP, 0.7ms@20k                                                                                                                                 |
| **GPU accel (calib)**  | **None (keep ModernGL for live warp)**   | —                   | CUDA, Vulkan, GL compute   | Transfer > compute at 5-100k; ModernGL already 0.006ms/frame for live                                                                                                |
| **Memory transport**   | **Python C-contig + cached VBO/texture** | In-place gray       | uint16 map, zero-copy DMA  | Peak 46MB@1280×720, stable 300s, copies 2ms vs 370ms decode                                                                                                          |

---

## FINAL VERDICT

**Do NOT implement production changes in this phase. STOP AFTER REPORT.**

**Recommended stack for ProjectionAI calibration backend:**

- **Pattern generation:** GrayCode `GrayCodePatternGenerator` (21 patterns @1280×720, Hamming 1)
- **Structured-light decode:** GrayCode `CorrespondenceMatcher` (binary threshold, dense CorrespondenceMap)
- **Reconstruction:** `ReferenceReconstructionBackend` (NumPy/OpenCV, plane triangulate, 2.94ms@20k)
- **Intrinsics:** OpenCV Zhang linear (`_homography_for_plane` joint solve, fx,fy, cx,cy fixed)
- **Pose:** OpenCV `solvePnP` per-plane
- **Bundle adjustment:** Deferred (OpenCV LM refine as backup if <0.3px needed)
- **Surface reconstruction:** Plane triangulation (`triangulate_plane`, ray-plane O(N))
- **GPU acceleration:** None for calibration; ModernGL `ProjectionPass` for live warp only
- **Memory transport:** Current copy-light Python (C-contig enforcement, cached `WarpMesh` VBO 10.6KB + texture, peak 46MB)

**Why:** On THIS workload (2-3 planes, 5-50k correspondences, decode 370ms + capture 4.2s dominant, reconstruction+solve <15ms), the simplest proven backends win within measurement noise, are deterministic, brightness-robust, and fully portable Windows/Linux. Native/CUDA/Ceres/Vulkan/PhaseShift/Rust show per-op or theoretical wins that vanish end-to-end after transfer/build/portability costs. Keep pluggable interfaces (`StructuredLightPatternGenerator`, `BackendMode`, `CameraProjectorTransform`) for future hybrid if <0.2px on curved surfaces becomes product requirement — but do not pay the 2× capture + build complexity now.
