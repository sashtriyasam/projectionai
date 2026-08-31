# Phase 6.10H — Hardware Deferred / Software Baseline Freeze

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Software freeze — NO new optimization, NO hardware experiments, NO production default changes

**Verdict:** **SOFTWARE CALIBRATION STACK READY — PHYSICAL END-TO-END VALIDATION DEFERRED**

---

## A. What Is Fully Verified in Software

All 10 pipeline contracts verified via unit tests (no hardware required):

| #   | Component                      | Contract                                                                                                                                            | Tests                                                                            | Result       |
| --- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ------------ |
| 1   | Canonical `CalibrationResult`  | `domain/calibration_session.py` — typed `CalibrationResult`, `ReconstructionResult`, `CalibrationMethod`                                            | `tests/unit/calibration/test_calibration_session.py` (part of 79)                | ✅ 79 passed |
| 2   | `CalibrationSession` lifecycle | `calibration_session.py` — `CalibrationSessionStatus` (CREATED→CAPTURING→SOLVING→VALIDATING→COMPLETED/FAILED)                                       | same                                                                             | ✅           |
| 3   | `PatternEngine`                | `services/pattern_engine.py` — `CalibrationSequence` generation, `bits_for` minimality                                                              | `test_pattern_engine.py`                                                         | ✅           |
| 4   | `SynchronizedCaptureSession`   | `infrastructure/projector_calibration/sync.py` — `SyncConfig(warmup_frames=1)`, `_warmup` drain, `_presentation_barrier`, retry, mismatch detection | `test_capture_sync.py` (11) — including 2 new warmup tests, adapted flaky-retry  | ✅ 11+2      |
| 5   | `StructuredLightDecoder`       | `infrastructure/projector_calibration/correspondence.py` — `CorrespondenceMatcher.decode`, `gray_decode`, `compute_lit_mask` + `lit_mask` param     | `test_correspondence.py` (incl. 3 new lit-mask tests) + `_synthetic_scene`       | ✅ 14+3      |
| 6   | `ReconstructionBackend`        | `services/reconstruction.py` — `ReferenceReconstructionBackend` vs `NativeReconstructionBackend`, factory best-only rule                            | `test_reconstruction_stage.py`, `test_reconstruction_synth.py`                   | ✅           |
| 7   | Calibration solver             | `calibration/solver.py` — joint Zhang (`_homography_for_plane` + linear) + per-plane `solvePnP`, `_MIN_TILT_DEG=15`, `_MAX_COND=1e6`                | `test_solver.py` (21)                                                            | ✅           |
| 8   | `Calibration → WarpMesh`       | `services/calibration.py` `calibration_to_warp_mesh` → `create_planar_grid_warp_mesh`                                                               | `test_calibration_to_warp_mesh.py`, `test_warp_pipeline.py`, `test_warp_mesh.py` | ✅ 73        |
| 9   | `ProjectionPass`               | `infrastructure/renderer/passes/projection.py` — `ScreenTarget`, `ProjectionPass`, `Texture`                                                        | `test_projection_pass.py`, `test_output_content_projection.py`                   | ✅           |
| 10  | `OutputManager` safety         | `hardware/output_manager.py` — `arm(require_projector=True)`, `go_live`, `BLACKOUT`/`FREEZE`/`UNFREEZE`/`SAFE STOP`, `DisplayValidator`             | `test_output_manager.py` (37)                                                    | ✅ 37        |

**Validation gates (2026-08-23, uncommitted tree includes 6.10B warmup+sentinel primitives):**

- `ruff check src/` — **All checks passed**
- `ruff format --check src/` — **223 files already formatted**
- `mypy src/projectionai/` — **Success: no issues in 222 files**
- `pytest tests/unit/calibration/ -q --no-cov` — **424 passed**
- `pytest tests/unit/infrastructure/renderer/test_projection_pass.py` + `test_warp_mesh` + `test_calibration_to_warp_mesh` — **73 passed**
- `pytest tests/unit/domain/test_projection.py` — passed
- `pytest --ignore=tests/unit/domain/test_calibration_session.py` full suite — pre-existing collection error (duplicate basename `test_calibration_session.py` in `domain/` vs `calibration/`) — **unrelated to this phase**, 131 focused calibration tests all green.

No `xfail`, no `skip`, no tolerance changes.

---

## B. What Is Verified Synthetically

Synthetic ground truth (1280×720 identity, 640×480 camera, `synthetic_captures` in `tests/unit/calibration/_synthetic_scene.py`):

- **GrayCode decode:** bit-exact on perfect captures; integer codes 0.408 px RMS worst-case (0.5 px max) for uniform subpixel offset; threshold robust to ±30% brightness and ±5-40 gray-level noise (FVR 0% with lit-mask).
- **Occlusion lit-mask:** white sentinel `build_white_sentinel` + `compute_lit_mask(white, black)` reduces false-valid **100% → 0%**, recall **0% → 100%** at 1-20% random/contiguous occlusion and shadow (dim=40/90). Distinguishes true-zero-code (white sentinel bright → valid) from no-light (dark → invalid) — max-intensity alone false-rejects true-zero, inverted pair does not; white sentinel (+1 capture, 22 vs 21) achieves same FVR as full inverted pair (42) at half cost.
- **GPU decode (GL 4.6 compute, Intel UHD, moderngl):** 1.43× at 720p (150→105 ms), 1.69× at 4K, but **1.01× end-to-end** (45 ms of 4.5 s, <5% rule) — transfer dominates (H2D 16 ms + D2H 55 ms = 68% of GPU total). Bit-exact on 15/15 cases after fixing Intel GLSL doubling-loop.
- **Grid density:** headless `0.006 ms` for 8/16/32; 16×16 (289 verts, 170 tris, VBO 10.6 KB) remains recommended — sub-5 ms gen, negligible faceting.
- **Stability (synthetic/headless):** 0 dropped, max 0.045 ms, no context loss.

---

## C. What Is Physically Verified

- **Displays:** `\\.\DISPLAY1` 1536×864@144Hz (primary, Chimei Innolux) + `LG TV SSCR2` 1280×720@60Hz at (1920,0) (secondary, `qt-serial-16843009`) — enumerated via `QGuiApplication.screens()`, `QtPatternProjector(screen_index=1)` resolution correct, `GLOutputWindow` fullscreen verified (39.6 FPS stable for 300 s, 11889 frames, 300 s in 6.9-HW).
- **Camera:** `idx 0 = MSMF 640×480@30fps` (exp −6 auto, gain −1), also `idx 0 DSHOW` and `idx 1 DSHOW` same device family — probe shows `BUFFERSIZE=1` first-frame 1650 ms vs 364 ms default (4.5×), steady read p50 31.6 ms (30 fps period), `asyncio.sleep(20ms)` → 26.8 ms real (Windows timer quantization).
- **Optical path:** **NOT verified — 0.00% differential** (see D). `SynchronizedCaptureSession` warmup drain (6.10B) is software-verified but not validated on an aimed surface.

---

## D. What Remains Hardware-Dependent

Explicitly **HARDWARE_PENDING** — not resolved, not modified:

| Item                                       | Why pending                                                                                            | What must be measured                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Real projector/camera round trip           | Webcam does not see LG TV (0.00% WHITE−BLACK diff, max 5-14, 0/307200 >20)                             | WHITE-vs-BLACK differential pixels above 20 must exceed 5% with camera aimed                       |
| Real vsync / `frameSwapped` timing         | `QtPatternProjector` is `QLabel/QPixmap` (no `vsync()`); barrier falls back to `monotonic_ns`          | `frameSwapped` vs `monotonic` latency/jitter/missed frames on `QOpenGLWidget` path                 |
| Real settle-time optimum (0/5/10/16/20 ms) | 6.10C sweep preserved pairing (0 mismatches) but correspondence validity unmeasured (camera not aimed) | 3× sequences per settle with warmup, sentinel, real surface: pairing + coverage + RMS + retries    |
| Real camera backend policy                 | `BUFFERSIZE=1` harmful on MSMF first-frame but stale-frame benefit unmeasured on aimed path            | Default vs `BUFFERSIZE=1` on real optical path: first-frame, steady latency, stale-frame incidence |
| Real sentinel coverage                     | Synthetic FVR 100%→0% proven; real lit-mask on LG TV + wall not measured                               | White sentinel (+1) on real surface: valid coverage, RMS, false-valid                              |
| Real 2-plane calibration (≥15° normals)    | Requires two distinct surface orientations aimed at camera                                             | fx/fy, pose, RMS ≤2 px, coverage ≥0.5, WarpMesh validity                                           |
| Real repeatability (3 runs)                | Requires valid 2-plane calibrations                                                                    | mean/stddev/max deviation of fx/fy/pose/RMS/WarpMesh UVs                                           |

---

## E. Exact Hardware Setup Required Later

- **Projector:** LG TV secondary (`QtPatternProjector` index 1 or `GLOutputWindow` index 1), fixed 1280×720 @60Hz, `SwapInterval=1`, focus locked, keystone OFF, fixed refresh.
- **Camera:** Physical camera (not laptop lid webcam if it cannot see the TV) on **tripod/stable mount facing the LG TV**, optical axis centered so the TV's white rectangle fills **30-70%** of the camera frame with four corners visible, not clipped, not saturated.
- **Surface:** Matte white wall/screen that fills the camera image where the TV is imaged (or the TV panel itself if diffuse and camera can focus on it), stable mount, fills enough of camera FOV.
- **Ambient:** Controlled and recorded; no severe contamination; not saturated.

---

## F. Exact Test Sequence to Run When Hardware Is Available

**Gate first (DO NOT SKIP):**

```
WHITE (full-screen, 1280×720 white via QtPatternProjector index 1) → capture
BLACK (hide) → capture
WHITE2 → capture
→ differential abs(WHITE-BLACK): require pixels>20 >5% and coherent TV rectangle
```

**Then, in order (each with `warmup_frames=1`, full GrayCode, white sentinel):**

1. **Settle sweep:** 0/5/10/16/20 ms × 3 sequences × 21 patterns → record total time, per-pattern latency p50/p95/p99, mismatches/retries, correspondence coverage, RMS, reconstruction validity, calibration RMS. Winner = lowest safe settle.
2. **Backend:** MSMF default vs `BUFFERSIZE=1` (and DSHOW) on real optical path: first-frame, steady p50/p95/p99, stale-frame incidence, wrong-pattern rate.
3. **Sentinel e2e:** 21 vs 21+1 (white) — false-valid rate, precision/recall, coverage, RMS.
4. **Two-plane calibration:** orientation A + B (normal angle ≥15°) → joint Zhang + per-plane `solvePnP` → `CalibrationResult` (fx/fy, pose, RMS, coverage, WarpMesh).
5. **Repeatability:** 3 complete calibrations → mean/stddev/max deviation.

---

## G. Production Readiness Status

**SOFTWARE CALIBRATION STACK READY — PHYSICAL END-TO-END VALIDATION DEFERRED**

- **Software:** ✅ All 10 pipeline contracts green, 424 calibration tests passed, synthetic occlusion/sentinel validated, 6.10B primitives (`warmup_frames`, `compute_lit_mask`, `build_white/black_sentinel`) present and tested.
- **Physical:** ⚠️ **DEFERRED** — optical round trip not closed (0.00% WHITE−BLACK differential, camera not aimed). The 7 hardware-dependent items above are explicitly marked `HARDWARE_PENDING`.

**No production-default changes that depend on hardware have been made:** `min_settle_ms` stays 20, `BUFFERSIZE=1` stays as set in `OpenCVCamera.open()`, `Frame` remains RGB, sentinel remains opt-in primitives (not yet wired into `GrayCodeProjectorCalibration.capture_sequence` end-to-end). The only committed behavioral change is the additive, hardware-agnostic `warmup_frames=1` drain (smallest deterministic warmup).

**Physical floor (measured, not assumed):** camera frame period 31.6 ms @30fps → 21×31.6 = 664 ms/sequence floor; with current `BUFFERSIZE` + settle, steady sequence ≈1.23 s; first-frame 1650 ms (BUFFERSIZE=1) vs 364 ms (default) is the dominant one-time cost.

---

_No new optimization, no CUDA/Vulkan/OpenCL/Rust/Ceres, no second renderer. Baseline preserved. Follow the test sequence in F when the rig is correctly aimed._
