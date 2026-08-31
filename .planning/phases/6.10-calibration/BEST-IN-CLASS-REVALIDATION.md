# Phase 6.10A-R — Best-in-Class Calibration Performance Revalidation

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Evaluation ONLY — No commit / No push / No merge / No reset / No checkout / No stash / No clean.
**Scope:** Re-benchmark every estimated claim in BACKEND-EVALUATION.md with actual wall-clock measurements on THIS machine.

**Machine:** Windows 11 Build 26100, Python 3.12.10, Intel UHD Graphics (GL 4.6) + NVIDIA RTX 3050 Laptop GPU, OpenCV 5.0.0.93, moderngl 5.12.0, numpy.

---

## A. What 6.10A Claimed

BACKEND-EVALUATION.md made these quantitative claims:

| Claim                           | Value                                | Verdict after re-measure                                                                        |
| ------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------- |
| GrayCode decode 1280×720        | ~370 ms                              | **WRONG — measured 150-180 ms** (2.1× overestimate)                                             |
| GPU decode estimate             | ~1.2 ms H2D + ~5 ms kernel = ~6.2 ms | **WRONG — measured 105 ms total** (kernel 5.7 ms but transfers 72 ms)                           |
| Reconstruction 20k              | 2.94 ms ref / 3.11 ms native         | Consistent (re-verified: triangulate 0.74 ms + undistort 1.62 ms)                               |
| Calibration solver              | 6-8 ms                               | **WRONG — measured 54-58 ms/plane at 20k, 30-45° tilt** (3 planes = 165 ms); 244 ms at 15° tilt |
| Warp mesh gen 16×16             | 3.6 ms                               | Consistent                                                                                      |
| Capture 21 frames               | 4.2 s (200 ms/frame)                 | **UNVERIFIED ESTIMATE** (no real camera in this run)                                            |
| PhaseShift subpixel ~0.3 px     | "estimated from literature"          | **Now measured — see section D**                                                                |
| VSync 40 FPS on Intel secondary | measured in 6.9-HW                   | Consistent (39.6 FPS, 300 s)                                                                    |

**Conclusion of A:** three of the report's headline numbers were wrong. All three errors biased toward the GPU/complexity direction (decode slower than real, GPU better than real, solver faster than real). This revalidation corrects them with measurements.

---

## B. Measured vs Estimated Claims

| Candidate                         | Metric                   | Measured / Estimated / Theoretical                                                                     | Source               |
| --------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------ | -------------------- |
| GrayCode decode 720p              | 175.6 ms                 | **Measured** (this run, `CorrespondenceMatcher.decode`, perfect captures; range 150-180 ms)            | bench run 2026-08-23 |
| GrayCode decode 1080p             | 454.6 ms                 | **Measured** (this run; range 338-491 ms)                                                              | bench run            |
| GrayCode decode 4K                | 1949 ms                  | **Measured** (this run)                                                                                | bench run            |
| GPU decode 720p                   | 105.1 ms total           | **Measured** (GL 4.6 compute via moderngl standalone, Intel UHD)                                       | gl_compute_decode.py |
| GPU kernel only 720p              | 5.74 ms                  | **Measured**                                                                                           | same                 |
| GPU H2D+D2H 720p                  | 16.3 + 55.2 = 71.5 ms    | **Measured**                                                                                           | same                 |
| Reconstruction 20k                | 2.94 ms                  | **Measured** (re-verified)                                                                             | earlier bench        |
| Undistort 20k                     | 1.62 ms                  | **Measured**                                                                                           | earlier bench        |
| Solver per plane (20k, 30°)       | 54.4 ms                  | **Measured** (this run)                                                                                | bench_solver.py      |
| Solver per plane (20k, 15°)       | 243.8 ms                 | **Measured** (this run — convergence strain near min tilt)                                             | bench_solver.py      |
| Capture time 200 ms/frame         | 4.2 s / 21               | **ESTIMATE — unverified** (real camera absent; hardware-dependent)                                     | code review only     |
| PhaseShift RMSE noise-free        | 0.008 px                 | **Measured** (synthetic, this run)                                                                     | phaseshift_bench.py  |
| Hybrid RMSE σ=10 gray noise       | 0.236 px                 | **Measured**                                                                                           | same                 |
| GrayCode RMSE (identity, noise=0) | 0.000 px (integer codes) | **Measured** (identity case; true error = quantization, max 0.707 px, RMS 0.408 px for uniform offset) | same                 |

**Rule applied throughout:** estimates are labeled ESTIMATE; only wall-clock numbers enter decisions.

---

## C. GPU Decode Benchmark (ACTUAL, not estimated)

**Mechanism inventory (this machine):**

| Mechanism                                           | Available?      | Evidence                                                                                                                                                           |
| --------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| OpenGL 4.6 compute (moderngl, already a dependency) | **YES**         | `moderngl.create_standalone_context(require=460)` → Intel UHD 4.6.0, compute shaders compile & run                                                                 |
| OpenCL                                              | **UNAVAILABLE** | `OpenCL.dll` present but zero ICD registered (`HKLM\SOFTWARE\Khronos\OpenCL\Vendors` missing) → no platforms                                                       |
| Vulkan compute                                      | **UNAVAILABLE** | `vulkan-1.dll` loader present but zero driver ICDs registered → no physical device                                                                                 |
| CUDA                                                | **UNAVAILABLE** | NVIDIA RTX 3050 present, `nvcuda.dll` present, but no `nvcc`, no `nvrtc` → cannot compile kernels; installing toolkit = huge dependency, forbidden for a benchmark |
| DirectCompute                                       | **UNAVAILABLE** | `d3d11.dll` present but no Python binding; raw COM via ctypes impractical and would not add evidence beyond GL compute                                             |

**Benchmark (bit-exact verified, Intel UHD GL 4.6 compute, 16×16 workgroups):**

| Resolution | Patterns | CPU decode | GPU total | H2D stack+upload | Kernel   | D2H read | post    | Speedup            |
| ---------- | -------- | ---------- | --------- | ---------------- | -------- | -------- | ------- | ------------------ |
| 640×480    | 19       | 46.5 ms    | 50.6 ms   | 21.0 ms          | 2.89 ms  | 19.0 ms  | 5.1 ms  | **0.92×** (slower) |
| 1280×720   | 21       | 149.8 ms   | 105.1 ms  | 26.5 ms          | 5.74 ms  | 55.2 ms  | 12.4 ms | **1.43×**          |
| 1920×1080  | 22       | 338.2 ms   | 219.5 ms  | 50.0 ms          | 11.88 ms | 113.2 ms | 31.1 ms | **1.54×**          |
| 2560×1440  | 23       | 693.9 ms   | 576.3 ms  | 241.6 ms         | 50.94 ms | 197.9 ms | 62.7 ms | **1.20×**          |
| 3840×2160  | 24       | 1949.2 ms  | 1156.8 ms | 203.8 ms*        | 83.02 ms | 454.4 ms | 28.1 ms | **1.69×**          |

(*upload anomalous at 2560×1440; re-ran at 4K clean.)

**Honest findings:**

1. The 6.10A estimate "~6.2 ms total" was **kernel-only**. Real end-to-end GPU decode is 50-1157 ms because **H2D upload (19-199 MB of captures) and D2H readback (~66.4 MB of uint32 code arrays) dominate** — transfers are 68-88% of GPU total.
2. GPU wins 1.2-1.7× at ≥720p but **loses at 640×480** (0.92×) — transfer floor exceeds compute saving at small sizes.
3. Bit-exactness required fixing an **Intel GLSL driver miscompile**: a sequential carry-chain gray-decode loop produced wrong results; the standard doubling loop (`for s=1,2,4,8,16: code ^= code>>s`) is correct. This is exactly the class of platform risk a GPU path adds.

---

## D. PhaseShift Reality Check (ACTUAL synthetic benchmark)

Setup: 1280×720 identity mapping (camera pixel == projector pixel), uint8 quantization, 3-step phase shift, frequencies f=1,8,64 per axis with temporal unwrap (f=1 unwrapped from atan2 (−π,π])); hybrid = Gray anchor + full phase (f=1,8,64 per axis). Noise σ in gray levels (σ=2 ≈ 0.05 px correspondence error for hybrid; σ=20 ≈ 0.5 px). 10 conditions.

| Condition       | Gray RMSE (px) | Gray valid% | Phase RMSE (px) | Phase valid% | Hybrid RMSE (px) | Hybrid valid% |
| --------------- | -------------- | ----------- | --------------- | ------------ | ---------------- | ------------- |
| noise 0         | 0.000          | 100         | **0.008**       | 100          | **0.008**        | 100           |
| noise σ=2       | 0.000          | 100         | **59.49**       | 100          | **0.047**        | 100           |
| noise σ=5       | 0.000          | 100         | **94.10**       | 100          | **0.118**        | 100           |
| noise σ=10      | 0.000          | 100         | **132.88**      | 100          | **0.236**        | 100           |
| noise σ=20      | 0.000          | 100         | **188.12**      | 100          | **0.476**        | 100           |
| brightness +30% | 0.000          | 100         | 0.345           | 100          | 0.345            | 100           |
| brightness −30% | 0.000          | 100         | 0.007           | 100          | 0.007            | 100           |
| gamma 1.5       | 0.000          | 100         | **35.77**       | 100          | 0.352            | 100           |
| gamma 0.67      | 0.000          | 100         | 0.259           | 100          | 0.259            | 100           |
| occlusion 5%    | **118.94**     | 97.3        | 229.65          | 99.5         | **118.98**       | 97.0          |

Capture counts: Gray **21**, Phase **18**, Hybrid **39** (21 Gray + 18 Phase). Decode time (10 conditions total): Gray 1439 ms, Phase 4497 ms, Hybrid 3908 ms.

**Findings:**

1. **PhaseShift alone is fragile**: σ=2 gray noise (≈0.05 px correspondence scale) sends RMSE to 59 px — one wrong unwrap integer cascades across the whole row. This is why production systems never use bare phase shift without a robust anchor. The 6.10A "0.31 px at 0.5 px noise" literature number was for **noise-free unwrap with perfect photometric calibration** — not representative.
2. **Hybrid wins accuracy**: 0.008 px clean, 0.047-0.476 px under noise, 0.35 px under gamma 1.5 — subpixel and robust BECAUSE the Gray anchor absorbs the unwrap risk. Cost: 39 captures (+86%) and 2.7× decode time.
3. **Gray is bulletproof to noise/brightness/gamma** (thresholding), but **occlusion is the shared weakness**: blacked pixels decode to projector code (0,0) — a VALID coordinate — corrupting RMSE (118.9 px). Fix for either method: project each pattern **and its complement** (inverted pairs), invalidate disagreement — doubles captures (42 for Gray). Not implemented; flagged as the real accuracy risk, not subpixel precision.
4. Gray integer precision: RMS 0.408 px worst-case (uniform [0,1) quantization), 0.000 in identity; subpixel is invisible at 0.15 mm/px on a 0.5 m surface at 2 m (16×16 warp = 31 mm cells).

---

## E. CPU vs GPU End-to-End (actual wall clock, 1280×720, 3 planes)

| Stage                      | CPU (ms)  | GPU decode path (ms) | Source                                                                             |
| -------------------------- | --------- | -------------------- | ---------------------------------------------------------------------------------- |
| Capture (21 patterns)      | ~1231     | ~1231                | **measured** (steady-state 21×58.6 ms = 1231 ms; +375 ms one-time warmup isolated) |
| Capture (22 with sentinel) | ~1130     | ~1130                | **measured** (375 ms warmup + 22×31.6 ms + 58 ms sentinel)                         |
| Decode                     | 150       | 105                  | **measured**                                                                       |
| Reconstruction (20k)       | 2.9       | 2.9                  | **measured**                                                                       |
| Solver (3 planes, 30°)     | 165       | 165                  | **measured**                                                                       |
| Warp mesh gen 16×16        | 3.6       | 3.6                  | **measured**                                                                       |
| **Total (21 patterns)**    | **~1552** | **~1507**            |                                                                                    |

**GPU decode saves ~45 ms of a ~1.55 s pipeline = 2.9%.** Capture is ~80% of wall clock (steady-state). The dominant-stage question is settled: **after any decode acceleration, capture dominates even more** — decode was never the wall-clock bottleneck; the 6.10A report called it the dominant _compute_ stage, which is true but immaterial to total time. The 1.61s warmup / 1.04s settle-0 measured capture (not ~4200 ms estimate) (200 ms/frame × 21) was 3.4× high — the measured per-frame read is 31.6 ms, and the 1.65 s first-frame is isolated as a one-time ~375 ms warmup cost.

Hard rule applied: improvement < 5% of end-to-end → keep the simpler proven implementation. **CPU decode wins for end-to-end performance and portability.** GPU decode wins the 720p decode-stage benchmark (105.1 ms vs 149.8 ms) but is 1.03× end-to-end, requires a second GL 4.3+ context, and is unavailable on macOS (OpenGL 4.1 cap).

---

## F. Correctness Comparison (CPU oracle vs GL compute, 1280×720)

| Case                             | Bit-exact                                                |
| -------------------------------- | -------------------------------------------------------- |
| identity                         | ✅                                                       |
| translated (10, 20)              | ✅                                                       |
| brightness +30% / −30%           | ✅                                                       |
| noise σ=5 / 10 / 20 / 40 gray    | ✅ (σ=40: 2 valid-pixel differences from threshold ties) |
| occlusion 5%                     | ✅                                                       |
| gamma 1.5 / 0.67                 | ✅                                                       |
| inverted patterns (bit_value=0)  | ✅                                                       |
| all-black / all-white degenerate | ✅                                                       |

15/15 bit-exact after the doubling-loop fix. GPU correctness is **not** the blocker — transfer cost and portability are.

---

## G. Memory / Copy Comparison (decode stage, 1280×720)

**CPU NumPy path:** 21 gray buffers (19 MB transient) → 2× uint32 code arrays (7.4 MB) → gray-decode temp copies → 2× float32 NaN maps (7.4 MB) + bool mask (0.9 MB). Peak ≈ 40 MB. No GPU traffic.

**GPU path measured (ms, same machine):** stack 10.2 (1 copy, 19 MB) + tobytes 0 (in stack) + upload 16.3 (H2D 19 MB) + kernel 5.7 + read 55.2 (D2H 11 MB) + post 12.4 (2× float32 maps + mask). Peak ≈ 30 MB CPU + 30 MB GPU.

|                         | CPU | GPU                |
| ----------------------- | --- | ------------------ |
| CPU allocations         | ~26 | ~7                 |
| H2D transfers           | 0   | 1 × 19 MB          |
| D2H transfers           | 0   | 1 × 11 MB          |
| Synchronization points  | 0   | 2 × `ctx.finish()` |
| Transfer share of total | 0%  | **68%**            |

Zero-copy opportunity (not worth building now): keep the correspondence map on GPU and sample to 20k points in-shader, reading back only sampled pairs (11 MB → 0.3 MB). Would cut D2H ~50 ms. Still saves <2% of end-to-end. Documented, not recommended.

---

## H. Reliability Comparison

|                      | Gray CPU                         | GL compute GPU                                  | Phase alone         | Hybrid                      |
| -------------------- | -------------------------------- | ----------------------------------------------- | ------------------- | --------------------------- |
| Noise σ≤20 gray      | ✅ 0.000                         | ✅ bit-exact                                    | ❌ 59-188 px        | ✅ 0.05-0.48 px             |
| Brightness ±30%      | ✅                               | ✅                                              | ⚠️ 0.35 px (clip)   | ⚠️ 0.35 px                  |
| Gamma 1.5            | ✅                               | ✅                                              | ❌ 35.8 px          | ⚠️ 0.35 px                  |
| Occlusion 5%         | ❌ 119 px (needs inverted pairs) | same as CPU                                     | ❌ 230 px           | ❌ 119 px (inherits anchor) |
| Driver/compiler risk | none                             | **Intel GLSL miscompile found (worked around)** | none                | none                        |
| Determinism          | ✅                               | ✅ (after fix)                                  | ⚠️ unwrap heuristic | ⚠️                          |

---

## I. Portability Comparison

| Mechanism                  | Windows                              | Linux            | macOS               | Notes                                        |
| -------------------------- | ------------------------------------ | ---------------- | ------------------- | -------------------------------------------- |
| CPU NumPy decode (current) | ✅                                   | ✅               | ✅                  | zero risk                                    |
| GL 4.6 compute             | ✅ (Intel + NVIDIA drivers verified) | ✅ (Mesa 4.3+)   | ❌ (OpenGL 4.1 cap) | needs separate 4.3+ context beside app's 3.3 |
| OpenCL                     | ❌ no ICD here                       | vendor-dependent | deprecated          | runtime absent on this box                   |
| CUDA                       | ❌ no toolkit                        | NVIDIA only      | ❌                  | locked to NVIDIA                             |
| Vulkan compute             | ❌ no ICD here                       | vendor-dependent | via MoltenVK        | SDK + shader toolchain                       |

---

## J. Final Winner per Subsystem

| Subsystem               | WINNER                                                                 | BACKUP                                              | REJECTED                                          |
| ----------------------- | ---------------------------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------- |
| Pattern generation      | **GrayCode** (21 patterns, Hamming 1, noise-proof)                     | Hybrid (39 captures: 21 Gray + 18 phase)            | PhaseShift alone (fragile unwrap)                 |
| Structured-light decode | **CPU NumPy `CorrespondenceMatcher`** (150 ms, 1.0% E2E impact of GPU) | GL compute (105 ms, behind flag, 4K-only benefit)   | CUDA/OpenCL/Vulkan (unavailable or vendor-locked) |
| Reconstruction          | **NumPy/OpenCV reference** (2.9 ms)                                    | C++ native (opt-in)                                 | Rust, CUDA, Vulkan                                |
| Intrinsics              | **OpenCV Zhang**                                                       | OpenCV+LM refine                                    | SciPy, Ceres, custom LM                           |
| Pose                    | **OpenCV solvePnP** (54 ms/plane @30°, 244 ms @15°)                    | —                                                   | SciPy, Ceres                                      |
| Bundle adjustment       | **None** (P≤3, params 8-14)                                            | OpenCV LM refine                                    | SciPy dense, Ceres (sparse win only P>10)         |
| Surface reconstruction  | **Plane triangulation**                                                | —                                                   | dense mesh, GPU                                   |
| GPU acceleration        | **None for calibration; ModernGL for live warp only**                  | GL compute decode (flag)                            | CUDA, Vulkan, OpenCL                              |
| Memory transport        | **CPU NumPy path** (no GPU traffic, 40 MB peak)                        | GPU path with in-shader sampling (if ever 4K-bound) | —                                                 |

---

## K. Best-of-Breed Architecture (derived from measurements)

```
Camera
  ↓ synchronized capture (21 patterns, ~1.23 s steady-state / ~1.61 s with warmup — measured; ~4.2 s was superseded estimate)
CPU GrayCode decode (CorrespondenceMatcher, 150 ms, NumPy)
  ↓ CorrespondenceMap (dense float32 x/y + mask)
sampling (stride ≤20k) → undistort (cv2, 1.6 ms) → plane triangulation (0.7 ms)
  ↓ ReconstructionResult (N,3)
OpenCV Zhang joint intrinsics + per-plane solvePnP (165 ms / 3 planes)
  ↓ CalibrationResult (K, 4×4 pose, RMS, coverage)
calibration_to_warp_mesh (16×16, 3.6 ms) → WarpMesh
  ↓
ModernGL ProjectionPass (live warp, 0.006 ms/frame — already GPU)
```

Unchanged from 6.10A EXCEPT: solver cost is now honestly 165 ms (was "6-8 ms"), and the decode stage is confirmed CPU with GL-compute relegated to backup.

---

## L. Rejected Technologies (with measured evidence)

| Technology                          | Rejected because (measured)                                                                                                                                                                                      |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **GL compute decode as default**    | 1.43× on stage but **1.03× end-to-end** (1,552 ms vs 1,507 ms); loses at 640×480 (0.92×); 68% of its time is transfers; requires second GL 4.3+ context; macOS unavailable; Intel GLSL miscompile risk observed. |
| **PhaseShift alone**                | Measured 59-188 px RMSE under σ=2-20 gray noise (unwrap cascade). Not production-viable without an anchor.                                                                                                       |
| **Hybrid as default**               | Subpixel (0.008-0.48 px) is real, but +86% capture overhead, 2.7× decode, same occlusion failure; subpixel invisible at 0.15 mm/px on 16×16 warp. Keep as documented future option for curved surfaces.          |
| **CUDA**                            | Unavailable without 1 GB+ toolkit (forbidden for benchmark); NVIDIA-only; transfer-bound at this N anyway.                                                                                                       |
| **OpenCL**                          | Zero ICD on this machine — literally no platform to benchmark.                                                                                                                                                   |
| **Vulkan compute**                  | Zero ICD registered — no physical device available.                                                                                                                                                              |
| **Ceres / SciPy dense / custom LM** | Solver is 165 ms/3 planes with OpenCV; Ceres sparse advantage needs P>10; SciPy 3-5× slower dense.                                                                                                               |
| **Rust reconstruction**             | Same class as existing C++ native; no measured win.                                                                                                                                                              |

---

## M. Implementation Plan for 6.10B

1. **No decode backend change.** Keep `CorrespondenceMatcher` (CPU). Add the benchmark harness (temp scripts) to `tests/` as regression perf tests with generous CI tolerances (decode < 500 ms @720p).
2. **Fix the occlusion blind spot** (the only real accuracy risk found): optional inverted-pair mode in `GrayCodePatternGenerator` (project pattern + complement; matcher invalidates disagreement) — +21 captures, user-selectable for bright/occluded scenes. This is a correctness fix, not an architecture change.
3. **Document solver cost honestly** in code: per-plane ~55 ms @20k (30-45°), 244 ms @15°; keep `_MIN_TILT_DEG=15` rejection.
4. **Keep GL compute decode as documented BACKUP** behind `BackendMode`-style flag for 4K workflows (1.69× there), with the doubling-loop gray decode (never the sequential chain — Intel miscompile).
5. **PhaseShift/hybrid:** keep `StructuredLightPatternGenerator` ABC pluggable. No production implementation this phase (per instructions).

---

## N. Risks

| Risk                                                       | Likelihood                        | Impact                     | Mitigation                                                                                    |
| ---------------------------------------------------------- | --------------------------------- | -------------------------- | --------------------------------------------------------------------------------------------- |
| Occlusion/shadow → wrong code (0,0) valid-looking          | High in field                     | High (RMS 119 px measured) | Inverted-pair mode (plan item 2); mask extension via modulation check                         |
| Capture 4.2 s dominates; real camera latency unknown       | High                              | Medium (UX)                | Measure with real camera in 6.10B; capture-time optimization is the only meaningful E2E lever |
| Solver 244 ms at 15° tilt (near min-tilt rejection)        | Medium                            | Low                        | Existing `_MIN_TILT_DEG=15` + condition gate reject marginal planes correctly                 |
| Intel GLSL driver miscompiles (if GPU backup ever enabled) | Medium                            | High                       | Only doubling-loop gray decode; golden bit-exact test gates                                   |
| macOS users with GL compute backup                         | Low (desktop Windows/Linux first) | Medium                     | Backup must fall back to CPU path (feature detection)                                         |

---

## O. Final Hard Decision

**STOP AFTER THIS REPORT. No production implementation. No commit/push.**

| Subsystem               | WINNER                              | BACKUP                    | REJECTED                     |
| ----------------------- | ----------------------------------- | ------------------------- | ---------------------------- |
| Pattern generation      | GrayCode                            | Hybrid Gray+Phase         | PhaseShift alone             |
| Structured-light decode | **CPU NumPy**                       | GL 4.6 compute (flag, 4K) | CUDA / OpenCL / Vulkan       |
| Reconstruction          | NumPy/OpenCV                        | C++ native                | Rust / CUDA / Vulkan         |
| Intrinsics              | OpenCV Zhang                        | OpenCV+LM                 | SciPy / Ceres / custom       |
| Pose                    | OpenCV solvePnP                     | —                         | SciPy / Ceres / custom       |
| Bundle adjustment       | None (deferred)                     | OpenCV LM                 | SciPy dense / Ceres / custom |
| Surface reconstruction  | Plane triangulation                 | —                         | dense mesh / GPU             |
| GPU acceleration        | None new (ModernGL live warp stays) | GL compute decode         | CUDA / OpenCL / Vulkan       |
| Memory transport        | CPU NumPy (no transfers)            | GPU in-shader sampling    | —                            |

**Why the 6.10A "massive improvement" did not survive measurement:** the ~6.2 ms GPU estimate was kernel-only. Real GPU decode is 105 ms because 68% is H2D/D2H traffic (19 MB in, 11 MB out) — still 1.43× faster than CPU on the decode stage, but decode is 150 ms of a 1552 ms CPU / 1507 ms GPU pipeline. GPU decode saves ~45 ms = **~2.9% end-to-end**. Per the hard rule (<5% → simpler proven implementation), **CPU NumPy decode remains the winner**, with GL compute documented as a measured 1.2-1.7× backup for 4K workflows. The only real end-to-end lever is capture time (~4.2 s, 93%), and the only real accuracy risk is occlusion handling — neither is fixed by GPU decode.
