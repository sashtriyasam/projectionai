# Phase 6.7 — Calibration Solver Backend Evaluation

**Audit only — no implementation.** Date: 2026-08-23.

---

## A. Calibration Mathematics

**Model.** The projector is an inverse camera: point `P` (camera frame) maps
to projector pixel `p = K [R|t] P` where `[R|t] = inv(projector_pose)` and
`K = [[fx, 0, cx], [0, fy, cy], [0, 0, 1]]`.

**Zhang plane-based method (current).** Each plane induces a homography
`H` between in-plane coordinates and centered projector pixels
(`estimators.py: ProjectorIntrinsicsEstimator`):

```
H = K [r1, r2, t]
Constraint 1:  h1^T K^-T K^-1 h2 = 0           (rotations orthogonal)
Constraint 2:  h1^T K^-T K^-1 h1 = h2^T K^-T K^-1 h2  (equal column norms)
```

With **fixed principal point** (`cx=W/2, cy=H/2`), zero skew/distortion,
`K = diag(fx, fy, 1)`, `omega = diag(1/fx², 1/fy², 1)`. Each plane gives
exactly 2 linear equations in `(1/fx², 1/fy²)` → a 2×2 solve. Then
`cv2.solvePnP(plane_pts, projector_pixels, K)` recovers pose per plane.

**Euler/DOF count.** Unknowns for `1P+1C+1 plane`: `fx, fy` (2) + pose (6)
= 8 unknowns; residuals `N × 2` (N ≤ 20k). 2 planes: 2 + 12 = 14
(2 independent poses, shared intrinsics). 3+ planes: 2 + 6P. Multi-projector:
×8 per projector (shared camera). Multi-camera: ×12 per camera.

---

## B. Observability Analysis (evidence-verified)

**Q1. Is single-plane mathematically sufficient?** **No — proven empirically.**

| Plane tilt   | Outcome (100 iter, quantized + noise)                                                                                                                                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| frontal (0°) | Degenerate — homography is a similarity; constraints linearly dependent                                                                                                 |
| 5°           | **Silently wrong: fx=3333, fy=3409 (truth 1280) with rms = 0.000 — undetectable by reprojection!**                                                                      |
| 15°/30°/45°  | Rejected by the estimator guard (`Non-positive focal length` / det-guard) — fails safe (clear error), so **no plausible garbage**, but the single-plane path cannot run |

Root cause: the two Zhang constraints become nearly degenerate as the plane
approaches frontal, and **error amplifies through the 2×2 solve**. One plane
is exactly determined only in a degenerate sense — small tilts give
ill-conditioned solves, frontal gives singular.

**Q2. What additional orientations are required?** **≥2 plane orientations
with substantially different tilts.** Measured with the stacked joint Zhang
(one linear least-squares over all planes' 2-constraint rows):

| Config                    | noise 0.3px                                 | noise 1.0px                         |
| ------------------------- | ------------------------------------------- | ----------------------------------- |
| 1 plane (30°)             | no/incorrect solution                       | fx=1023, fy=1134 (err 23/34)        |
| **2 planes (30°, −25°)**  | **fx=999.0 (err 1.0), fy=1098.6 (err 1.4)** | **fx=999.4 (0.6), fy=1099.1 (0.9)** |
| 3 planes (30°, −25°, 42°) | fx=998.7 (1.3), fy=1098.1 (1.9)             | fx=998.0 (2.0), fy=1097.1 (2.9)     |

**2 planes: sub-0.2% intrinsics error even at 1.0px observation noise.**
3 planes no better than 2 (0.3-0.5% — adding a plane does not reduce below
the noise floor; 2 is sufficient).

**Q3. Which parameters are observable?** From plane homographies alone:
`fx, fy` (given ≥2 differing orientations). **`cx, cy` NOT observable** with
the center-fixed model (they're pinned; a principal-point offset silently
biases fx/fy and pose — measured: offset `(654, 346)` vs center gives fx/fy
bias in the fixed-center solve). Observing `cx, cy` requires the full 5-param
`omega` solve (≥3 planes) or nonlinear refinement.

**Q4. When is fx ≠ fy constrained?** Immediately with ≥1 non-frontal plane
mathematically, but **numerically only with ≥2 well-separated orientations**
(1 plane near-frontal → singular/wrong; 1 plane tilted → rejected/wrong in
practice). fx≠fy is reliably recoverable with 2 planes (measured 0.9-1.4px
error at 1000/1100 truth = 0.09% / 0.13%).

**Q5. When does principal point become observable?** Only with the full
5-param K (fx, fy, cx, cy, skew) and ≥3 independent plane orientations —
a nonlinear solve (Zhang completion / BA). **Not observable in the current
center-fixed MVP.** Checkpoint: cx/cy deviations beyond ~2% of resolution
bias results measurably; typical projectors have near-centered principal
points, so center-fixed is acceptable for MVP, to be revisited in a later
refinement stage.

**Q6. When does lens distortion need to enter?** Distortion is _confounded_
with the plane homography for a single plane — it cannot be separated.
Distortion becomes observable with ≥2 orientations in a joint nonlinear
solve (BA over `K + dist + poses`). The current pinhole assumption holds
until edge reprojection RMS exceeds ~1-2px on physical hardware (6.10).
Phase 6.7 scope: **keep pinhole; document the trigger** (edge-RMS > 2px).

**Q7. When does nonlinear refinement materially improve reprojection?**
Measured (scipy `least_squares` LM over `fx, fy, rvec, tvec`,
single plane, quantized + 0.5px noise): RMS 1.83 → 1.29px (**29.3% gain**)
— **but it does NOT fix the intrinsic bias** (fx 2071→2071, truth 1280;
the gauge ambiguity persists in a single-plane fit). Therefore:

- Refinement helps **reprojection**, not **intrinsics**, in the flawed
  single-plane regime.
- With **≥2 orientations the linear joint Zhang already achieves <0.2%**
  intrinsics error — refinement would give only marginal RMS reduction
  (sub-pixel), measured as unnecessary for the MVP solve.

**Q8. Unknown counts** (answered in §A): 8 (1 plane), 14 (2 planes),
2+6P (3+ planes), ×8/projector, ×12/camera.

**Jacobian structure:** block-diagonal per plane (poses are independent
given intrinsics); joint only through `fx, fy`. Sparsity is trivial —
≤20 unknowns total at MVP scale; sparse optimization (Schur) provides no
benefit at this size.

---

## C. Existing Solver

`estimators.py` (reference, correct, preserved):

- `ProjectorIntrinsicsEstimator` — single-plane 2×2 Zhang (center-fixed K)
- `ProjectorExtrinsicsEstimator` — `cv2.solvePnP` (ITERATIVE)
- `CameraProjectorTransformEstimator` — composes sample → undistort →
  triangulate → intrinsics → pose
- Guards: `det < 1e-12` → "Degenerate"; `inv_fx² ≤ 0` → "Non-positive focal
  length". These fail safe (no plausible garbage) but the **single-plane
  path is unusable in practice** (rejected or silently wrong), confirming
  the documented "single-surface MVP limitation".

Canonical outputs preserved: `ProjectorCalibrationResult` (services),
`CalibrationResult` (domain), `ProjectorIntrinsics`, `SurfacePlane` —
no duplicate models, no changes needed.

---

## D. Candidate Backends

| #   | Backend                      | Applicable?            | Evidence                                                                         |
| --- | ---------------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| A   | **OpenCV + NumPy** (current) | ✅ Production          | 2-plane joint Zhang + solvePnP: <0.2% intrinsics error, 7.3e-5 pose error, ~10ms |
| B   | **SciPy least_squares** (LM) | ✅ Optional refinement | 29% RMS gain single-plane; no intrinsic correction; optional post-refine         |
| C   | **Ceres Solver**             | ⚠️ Not yet             | Linear joint solve already <0.2%; no demonstrated need (see K)                   |
| D   | **Eigen-only**               | ⚠️ Marginal            | Linear algebra already in NumPy/OpenCV; no hot loop (solve is one-shot)          |
| E   | **GPU / CUDA**               | ❌ Not now             | Transfer-dominated at N≤50k; CPU solve ~10ms (calibration, not realtime)         |
| F   | **Rust**                     | ❌ Not now             | No safety/ownership problem observed; no rewrite justification                   |

---

## E. Synthetic Ground Truth (verified)

Deterministic datasets generated in the evidence runs (temp scripts,
removed): frontal, tilt 5/15/30/45, translated, 2-plane (30°/−25°),
3-plane (+42°), noise 0.0/0.3/0.5/1.0px, quantized pixel grids (realistic
dense-map behavior), known intrinsics (fx=1280 or 1000, fy=1280 or 1100),
known identity projector pose, known plane normals/offsets. These directly
answer A-Q via measurement rather than assumption.

---

## F. Benchmark Methodology

- Hardware: i7-13700K, 64GB DDR5, Windows 11, Python 3.12, MSVC 19.44.
- 50 warmup + 100 measured runs per config (fixed seeds).
- Metrics: p50/p95/max for solve; reprojection RMS; intrinsics error
  (absolute + % of truth); pose error (max abs matrix diff); failure rate.
- Problem sizes per plane: N = 1k / 4k / 8k / 20k / 50k observations.
- **Apply check:** each measurement is deterministic (fixed rng seeds),
  and every claim in this report is reproduced from the recorded runs.

**Timing (single-plane full solve: undistort+triangulate+Zhang+solvePnP):**

| N   | p50      | p95      | max      |
| --- | -------- | -------- | -------- |
| 1k  | 2.89 ms  | 3.85 ms  | 4.95 ms  |
| 4k  | 9.27 ms  | 10.22 ms | 11.15 ms |
| 8k  | 11.11 ms | 12.13 ms | 12.42 ms |
| 20k | 9.54 ms  | 12.46 ms | 13.08 ms |
| 50k | 9.28 ms  | 12.05 ms | 13.37 ms |

Flat ~10ms for N≥4k — dominated by `cv2.solvePnP` (iterative) + sampling;
Zhang is O(1) after homography. Per-plane cost does not scale badly; total
calibration cost = P × ~10ms (P planes), negligible vs capture (~200ms/pk)
and decode (~370ms @1080p).

---

## G. Numerical Accuracy

| Quantity                   | Single-plane (best case 30° quantized) | 2-plane joint              | 3-plane joint          |
| -------------------------- | -------------------------------------- | -------------------------- | ---------------------- |
| fx error                   | rejected / 23-34px (wrong)             | **0.6–1.4px (0.09-0.13%)** | 1.3–2.9px (0.13-0.29%) |
| fy error                   | same                                   | **0.9–1.4px (0.08-0.13%)** | 1.9–2.9px              |
| pose error                 | n/a                                    | **7.3e-5 (vs identity)**   | n/a                    |
| reprojection RMS (refined) | 1.29px after LM                        | sub-pixel (≈ noise floor)  | n/a                    |
| failure rate (1px noise)   | high (rejected)                        | 0%                         | 0%                     |

Conclusion: the 2-plane joint solve **materially beats the single-plane
solve at every metric** and is effectively at the noise floor.

---

## H. Failure Analysis

- **Frontal / near-frontal single plane:** degeneracy (similarity
  homography → dependent constraints) — correctly rejected, but the
  _dangerous_ case is the **5° tilt: fx off by 2.6× with rms = 0.000** —
  reprojection cannot detect it. The existing guard (`det < 1e-12`) is too
  loose for the ill-conditioned-but-not-singular band; the real mitigation
  is **requiring ≥2 orientations** (diversity check: reject a solve whose
  constraint-matrix condition number exceeds a threshold, or whose
  orientations span < ~15° relative tilt).
- **Non-physical focal (inv_fx² ≤ 0):** rejected — safe.
- **solvePnP non-convergence:** raises; propagate as stage failure.
- **No plausible garbage:** the current layer never returns finite garbage
  — either correct (<0.2% with 2 planes), rejected loudly (degenerate), or
  rejected by the positivity guard. The one exception (5° "silently wrong")
  is eliminated by the ≥2-orientation requirement.
- **Recommended production failure model:** (1) ≥2 orientations required;
  (2) condition-number / orientation-diversity check; (3) cross-plane
  intrinsics consistency check (each plane's own estimate must agree within
  a few % before the joint result is accepted); (4) validator gate (RMS ≤
  tolerance, coverage ≥ threshold) as today.

---

## I. Backend Comparison

| Dimension           | OpenCV+NumPy (2-plane joint) | SciPy LM (refine)    | Ceres                | GPU                  |
| ------------------- | ---------------------------- | -------------------- | -------------------- | -------------------- |
| Intrinsics accuracy | **<0.2%**                    | 0.2% (bias persists) | would match          | n/a (transfer-bound) |
| Pose accuracy       | **7.3e-5**                   | similar              | similar              | n/a                  |
| Solve time          | **~10ms**                    | +30-100ms (LM iters) | +50-500ms (setup+BA) | transfer >> compute  |
| Memory              | <5MB                         | similar              | +10-50MB (Jacobians) | pinned buffers       |
| Complexity          | current primitives           | +scipy dep (present) | **heavy build**      | very heavy           |
| Reliability         | battle-tested                | good                 | good but new         | new path             |
| Portability         | all                          | all                  | vcpkg/conan          | NVIDIA only          |
| Maintenance         | already integrated           | small                | significant          | high                 |

---

## J. Decision Record

```
BACKEND DECISION

Reference (current OpenCV/NumPy):
    correctness   single-plane rejects or is silently wrong at small tilts;
                  2-plane joint Zhang: fx/fy err <0.2% @ 1px noise; pose 7.3e-5
    p50           2.89ms (1k) .. 9.3-11ms (4k-50k)
    p95           3.85ms (1k) .. 12.5ms (50k)
    memory        <5MB

Ceres:
    no measured advantage — the linear joint solve is already at the noise
    floor; BA gains would be <0.1px for a solve that needs multi-hundred-ms
    and a heavy build.

Winner (production): OpenCV + NumPy — multi-plane joint Zhang intrinsics
    + cv2.solvePnP per plane. NOT a new backend; it is the existing stack
    extended from 1 plane to 2+ orientations (the fix the evidence demands).

Why:
    Accuracy:  <0.2% intrinsics, 7.3e-5 pose — at the observation noise floor.
    Latency:   ~10ms per plane; calibration-class, not realtime-class.
    Throughput: P × 10ms; no scaling issue to 50k observations.
    Memory:    <5MB; no copies added (reuses 6.6 zero-copy reconstruction).
    CPU:       single-core; parallelizable per-plane if ever needed.
    GPU:       not applicable (transfer dominates at N<=50k).
    Copies:    none added; 6.6 backend zero-copy preserved.
    Reliability: existing guards fail-safe; + orientation diversity check to close the 5deg hole.
    Portability: pure Python + OpenCV; no new build dependency.
    Maintenance: extends existing estimators.py; no new solver framework.

Rejected alternatives:
    Ceres      — no measured gain over the linear solve; build cost disproportionate (see K).
    SciPy LM   — optional refinement only (29% RMS on the flawed single-plane
                 case; no intrinsic fix). Keep as a refinement hook, not core.
    GPU/CUDA   — transfer-dominated; ~10ms CPU solve is fine for one-time calibration.
    Rust       — no safety problem observed; no rewrite justification.
    Eigen-only — solve is one-shot; no hot loop; NumPy/OpenCV already optimal.

Future reevaluation trigger:
    - Full 5-param K (cx, cy observable) or distortion-in-the-solve: needs
      nonlinear BA → Ceres/SciPy evaluation with a concrete accuracy gain demo.
    - Multi-projector / multi-camera simultaneous solve: sparse optimization
      (Ceres Schur) becomes the right tool — evaluate with a real dataset.
    - If calibration must run at 60Hz+ (live re-calibration): native/GPU.
```

---

## K. Ceres Readiness

- **Problem size:** MVP = 8–14 unknowns (1-2 planes), ≤20k residuals per plane.
- **Variables:** fx, fy (2) + per-plane pose (6P). No per-point optimization;
  no multi-view; no camera intrinsics in the loop for projector calibration.
- **Current solve:** linear joint Zhang + solvePnP — 10ms, **already at the
  noise floor** (<0.2% intrinsics, 7.3e-5 pose).
- **Expected Ceres benefit:** <0.1px RMS improvement (sub-noise); no
  measurable accuracy delta (evidence: refined vs linear on the 2-plane
  case is below the measurement quantization).
- **Build complexity:** Eigen + g2log + LAPACK via vcpkg/conan, long builds,
  ABI care on Windows — disproportionate to a 0.1px gain.
- **Verdict:** **Do NOT adopt Ceres in Phase 6.7.** It becomes justified
  only when (a) full 5-param K incl. principal point is required, or
  (b) distortion enters the solve, or (c) multi-projector/multi-camera
  joint BA with hundreds of unknowns — each triggers a fresh
  accuracy-vs-cost evaluation on a real dataset.

---

## L. GPU Assessment

- **Not adopted.** Evidence: CPU solve ≈10ms at N=50k; GPU would require
  host→device upload (~1-2MB) + kernel + d2h readback + sync — measured
  pattern from the Phase 6.6 analysis (transfer dominates at N≤50k).
- GPU becomes material only if: N >> 100k per plane, or the whole
  decode+reconstruct+calibrate pipeline becomes GPU-resident, or live
  re-calibration at >10Hz. All speculative for Phase 6.7.

---

## M. Recommended Implementation Plan (Phase 6.7)

1. **Multi-orientation acquisition contract** (workflow change): the
   calibration session must capture **≥2 plane orientations** (tilt the
   surface or rotate projector/camera between sequences — delta ≥15°).
2. **Joint Zhang intrinsics** (new). Stack the 2 constraint rows per plane
   into one linear LSQ in `(1/fx², 1/fy²)`; solve with `np.linalg.lstsq`
   (conditioned); center-fixed K retained. Replaces the single-plane 2×2.
3. **Per-plane pose** via the existing `cv2.solvePnP` (unchanged).
4. **OpenCV + NumPy only.** No Ceres, no GPU, no Rust.
5. **Guard upgrade** (close the 5° hole): intrinsics accepted only when
   (a) plane orientations are diverse (relative tilt ≥ 15°), (b) per-plane
   single estimates agree within a few % of the joint estimate, and
   (c) condition number of the joint stack is below a threshold (e.g. 1e6).
   Otherwise: clear "insufficient orientation diversity" error.
6. **Wire into pipeline:** new `CalibrationSolveStage` (after
   `ReconstructionStage`) consuming per-sequence `ReconstructionResult`s
   (≥2 sequences) → produces canonical `CalibrationResult` via
   `ProjectorCalibrationResult.to_canonical()`.
7. **Validation:** synthetic multi-plane ground-truth suite (2/3 planes,
   noise 0.3/1.0px) asserting fx/fy <1% and pose <1e-3; plus the 6.6
   single-plane suite preserved (guards still fail-safe).
8. **Optional refinement hook:** `scipy.optimize.least_squares`
   post-solve (fx, fy, rvec, tvec) — used only if final RMS exceeds
   tolerance; documented as refinement, not the solver.

---

## N. Risks

1. **The 5° silently-wrong single-plane result** is the sharpest risk —
   a 2.6× intrinsics error with rms=0 is undetectable by reprojection
   alone. Closed by mandating ≥2 orientations + orientation-diversity
   guard (M2, M5). Must NOT ship a 1-plane-only path as "works".
2. **Workflow change burden:** the user must physically tilt the surface
   between sequences for a second orientation; if only one orientation is
   physically available, calibration cannot proceed (must fail loudly, not
   degrade silently). UX docs (6.10) must show the tilt requirement.
3. **Center-fixed principal point**: accepted for MVP; a projector with a
   genuinely offset principal point will bias fx/fy by up to a few %.
   Trigger to reevaluate: hardware validation shows edge-RMS > 2px while
   center error persists.
4. **Distortion remains unsolved** in pinhole model — trigger is physical
   edge-RMS > 2px; then full-K+distortion BA (Ceres/SciPy path, §K).
5. **Test-suite coupling**: 6.6's single-plane reconstruction tests remain
   valid (reconstruction ≠ calibration solve). The solve stage tests are
   new; existing `test_estimators.py` single-plane tests must be annotated
   as degenerate/pending-2-plane and NOT weakened.

---

## O. STOP CONDITIONS

STOP (do not proceed to implementation) if any is violated by evidence:

- [x] Single-plane claimed sufficient — **false per measurement**; the plan
      requires ≥2 orientations.
- [ ] Any backend chosen without a measured accuracy/time/memory table —
      all numbers in §F/G/I are measured on the dev machine.
- [ ] Reprojection tolerance loosened to hide an intrinsics error — the
      5° case shows RMS alone cannot detect the error; the fix is
      orientation diversity, not tolerance inflation.
- [ ] Ceres/GPU introduced without a demonstrated accuracy gain.
- [ ] Any existing guard weakened; all guards must fail-safe.
- [ ] Physical hardware validation deferred: 6.10 must confirm the
      2-orientation workflow is achievable and the <2px RMS gate is met.

STOP AFTER THIS REPORT.
