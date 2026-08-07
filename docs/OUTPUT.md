# OUTPUT — Alpha-002: Gray-Code Projector Calibration (MVP)

> Status: **Implemented and verified.** Validated against the repository's standard gates (`pytest`, `mypy`, `ruff check`, `ruff format`); refer to CI for the current build status.

## What Was Built

A complete gray-code structured-light projector calibration pipeline: the app calibrates a **projector relative to an already-calibrated camera** by projecting a sequence of gray-code stripe patterns onto a known planar surface, capturing them, decoding dense camera-to-projector correspondences, and solving for the projector's intrinsic matrix and pose.

The pipeline lives in `src/projectionai/infrastructure/projector_calibration/`:

| Module              | Responsibility                                                            |
| ------------------- | ------------------------------------------------------------------------- |
| `patterns.py`       | Gray-code stripe pattern generation (`GrayCodePatternGenerator`)          |
| `capture.py`        | Project/capture orchestration (`PatternCaptureSession`)                   |
| `correspondence.py` | Decodes captures into a dense `CorrespondenceMap`                         |
| `estimators.py`     | Intrinsics (Zhang), pose (solvePnP), corners, plane triangulation         |
| `validation.py`     | Reprojection RMS / coverage quality gate (`ReprojectionValidator`)        |
| `gray_code.py`      | Composed `GrayCodeProjectorCalibration` implementing the service contract |

Orchestration: `CalibrationManager.run_projector_calibration` (projector path), `CalibrationComplete`/`CalibrationFailed` events, append-only `CalibrationHistory`, and background execution via `JobManager` (`enqueue_projector_calibration`).

## Math & Coordinate Chains

All frames are OpenCV convention: camera at the origin looking along `+z`, `y` down, `x` right. No lens distortion in the MVP model.

### Scene geometry

- Surface plane: `normal · p + offset = 0` (`SurfacePlane`). For the synthetic scene: `z = 1500 mm`.
- Projector pose `T` maps **projector-local → camera frame**: `p_cam = R · p_proj + t`. `R` from `rvec` via `cv2.Rodrigues`.

### Plane homography (projector pixel → camera pixel)

The two-view plane homography (Hartley & Zisserman), with the camera as view 2 (`R2 = I, t2 = 0`) and the projector as view 1:

```
H = K_cam · (R + t·n1ᵀ / d1) · K_proj⁻¹
```

where `n1 = Rᵀ·n` (plane normal in the projector frame) and `d1 = d − nᵀ·t` (plane offset in the projector frame), `d = −offset`. This drives the synthetic scene renderer and is the forward model the solver must invert.

### Gray-code correspondence

- Each projector column/row coordinate bit is encoded as a full-screen stripe pattern: `bits = gray_encode(coords) = x XOR (x >> 1)`; the displayed pixel is white where the bit is 1.
- `bits_x = ceil(log2(width))`, `bits_y = ceil(log2(height))` → **21 patterns** at 1280×720 (11 + 10).
- Decoding: per camera pixel, threshold each capture against the pattern's declared `bit_value` (so **inverted sequences decode identically**), assemble the gray code, then recover the binary coordinate by prefix-XOR: `binary = gray XOR (gray>>1) XOR (gray>>2) ...`.
- Result: for every camera pixel, the projector pixel `(x, y)` that illuminated it, plus a validity mask.

### Triangulation & solving

- **Triangulate**: each camera ray `r = (x, y, 1)` uses **normalized (undistorted) camera coordinates**, not raw pixels: the measured pixel correspondence `(u, v)` is first mapped to normalized coordinates via `K_cam⁻¹·(u, v, 1)` (implemented as `cv2.undistortPoints(..., P=np.eye(3))`). The ray is then intersected with the plane — `p = t·r`, `t = −offset / (n·r)`.
- **Intrinsics (Zhang, single view)**: with `K = diag(fx, fy, 1)` and the principal point fixed at the projector centre, the two orthogonality/norm constraints on the plane→projector homography columns `h1, h2` are exactly enough to recover `fx, fy`:

```
h1ᵀ K⁻ᵀ K⁻¹ h2 = 0
h1ᵀ K⁻ᵀ K⁻¹ h1 = h2ᵀ K⁻ᵀ K⁻¹ h2
```

The homography is fitted with **deterministic least squares** (`cv2.findHomography(..., 0)`), not RANSAC — correspondences are already mask-filtered and the validator gates the result.

- **Extrinsics**: `cv2.solvePnP` with the projector modelled as an inverse camera (`K_proj`, camera-frame 3D points → projector pixels), then inverted to yield the projector-local → camera pose.
- **Validation**: reproject triangulated points through the estimated model, compute RMS / mean / max error in projector pixels, plus coverage (fraction of projector pixels backed by a correspondence). `confidence = clamp(1 − RMS/(2·max_rms), 0, 1) · coverage`.

## Verification Results (synthetic ground truth)

Scene: camera `f = 4500` (resolves projector pixels), projector `f = 2000` at `t = (70, 140, 800)`, plane `z = 1500`.

| Metric               | Result                                    |
| -------------------- | ----------------------------------------- |
| Patterns             | 21 (11 column + 10 row bits)              |
| Correspondences      | 921,422 / 921,600 (100.0%)                |
| `fx`                 | 1999.02 vs 2000.00 (**0.049%** rel err)   |
| `fy`                 | 1998.95 vs 2000.00 (**0.053%** rel err)   |
| `cx, cy`             | 640.00 / 360.00 — exact                   |
| Pose `rvec`          | [0.1998, −0.09995, 0.03001] vs truth      |
| Pose `tvec`          | [69.94, 139.81, 800.31] vs [70, 140, 800] |
| Pose max abs diff    | 0.3127                                    |
| Reprojection RMS     | **0.4084 px**                             |
| Coverage             | 0.8461                                    |
| Confidence           | 0.7597                                    |
| Max per-point error  | 0.708 px (19,605 samples)                 |
| Unlit frame fraction | 0.0002                                    |

## Performance

A calibration run on the synthetic scene now takes ~**0.2 s** total (intrinsics 103 ms, extrinsics 72 ms).

**Root cause fixed (748×):** `plane_basis` called `np.linalg.svd(points − centroid)` with the default `full_matrices=True`. For an (N, 3) point cloud with N ≈ 19,605 that computes a full N×N `U` matrix (~3 GB allocation) — minutes of work, and the subsequent (2N, 9) DLT homography solve failed outright with `MemoryError` (`init_gesdd failed init`). Switching to the thin SVD (`full_matrices=False`) keeps only the 3×3 right singular vectors needed for the plane basis:

- Intrinsics step: **77,273 ms → 103.2 ms** (748× speedup, identical accuracy).
- `cv2.findHomography` LSQ was _not_ the hot spot (176 ms standalone) — the earlier "RANSAC pathological" suspicion was superseded once the SVD was instrumented.

## Test Coverage

7 new test files under `tests/unit/calibration/` (220 calibration tests, 564 total in the suite):

| File                                    | Covers                                                    |
| --------------------------------------- | --------------------------------------------------------- |
| `test_patterns.py`                      | bit counting, gray encode/decode, sequence construction   |
| `test_correspondence.py`                | decode, inverted sequences, validation errors             |
| `test_estimators.py`                    | intrinsics/extrinsics/transform/corners + math primitives |
| `test_validation.py`                    | RMS/coverage/inlier metrics, thresholds                   |
| `test_gray_code_calibration.py`         | composed algorithm end-to-end + component injection       |
| `test_projector_stages.py`              | pipeline stages (decode, pose)                            |
| `test_calibration_manager_projector.py` | manager integration, events, history, background jobs     |

A shared `_synthetic_scene.py` renders what a calibrated camera sees when a projector displays patterns onto a known plane (plus-form homography, ground-truth intrinsics/pose).

## MVP Limitations (documented, by design)

1. **Single planar surface orientation.** The Zhang constraints on one homography recover exactly `fx` and `fy` (principal point fixed at centre, zero skew/distortion). A full intrinsic model requires multiple surface orientations or the full Zhang solve.
2. **Pinhole projector model** — no projector lens distortion.
3. **Known plane.** The surface must be detected/determined before calibration (out of MVP scope).
4. **Unlit region handling.** Pixels outside the lit quad are rendered mid-gray (≥ decoder threshold) so they decode out-of-range and are masked — a stand-in for the all-white/all-black reference mask of production gray-code pipelines.

## Integration Points

- **Warping**: `ProjectorCornerEstimator` projects known 3D surface corners into projector pixels — the basis for warp-mesh generation and coverage visualization (warp engine integration is a follow-up).
- **Application**: `CalibrationManager.run_projector_calibration(camera_id, algorithm, projector, ...)`; emits `CalibrationStarted` / `CalibrationProgress` / `CalibrationComplete` / `CalibrationFailed`; persists to `CalibrationHistory`; `enqueue_projector_calibration` runs it as a background `Job`.
- **Service contract**: `ProjectorCalibrationAlgorithm` (build_sequence → decode → calibrate) is injectable, so phase-shift or binary-code families slot in as alternative `StructuredLightPatternGenerator`s.
