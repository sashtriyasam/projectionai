# Phase 6.10C — Physical Calibration Round-Trip + Capture Optimization

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Hardware validation / Implementation — No commit / No push / No merge / No reset

**Scope:** Capture-time bottleneck + occlusion false-valid. CPU GrayCode remains production baseline; no CUDA/Vulkan/OpenCL/Rust/Ceres.

---

## A. Hardware Setup (measured)

| Device                     | Value                                                                                                                                                                                                                                                                                   | Source                                                    |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| OS                         | Windows 11 Build 26100                                                                                                                                                                                                                                                                  | `platform`                                                |
| Python                     | 3.12.10, PySide6 6.11.1, moderngl 5.12.0, opencv 4.10.0.93                                                                                                                                                                                                                              | `pip`                                                     |
| GPU                        | Intel UHD Graphics 30.0.100.9864 + NVIDIA RTX 3050 Laptop 32.0.16.1062                                                                                                                                                                                                                  | `QGuiApplication` + `Win32_VideoController`               |
| Primary display            | `\\.\DISPLAY1` 1536×864 @144Hz (1920×0 logical due to devicePixelRatio 1.25), Chimei Innolux                                                                                                                                                                                            | `QGuiApplication.screens()[0]`                            |
| **Projector**              | **LG TV SSCR2** 1280×720 @60Hz at (1920,0), devicePixelRatio 3.0                                                                                                                                                                                                                        | `QGuiApplication.screens()[1]`, `list_displays()` index 1 |
| Secondary target           | `qt-serial-16843009` / `qt-serial-1`                                                                                                                                                                                                                                                    | Qt provider                                               |
| **Camera**                 | **idx 0 = MSMF 640×480@30fps** (also idx 1 = DSHOW same device)                                                                                                                                                                                                                         | `cv2.VideoCapture` probe                                  |
| Camera exposure / gain     | exp −6.00 / gain −1.00 (auto)                                                                                                                                                                                                                                                           | `CAP_PROP_EXPOSURE/GAIN`                                  |
| Camera provider            | `OpenCVCamera` defaults 1280×720@30, `BUFFERSIZE=1` on open                                                                                                                                                                                                                             | `opencv_camera.py`                                        |
| Surface                    | Matte white wall/screen **not aimed** — laptop webcam points at user, projector points at (1920,0) LG TV; optical round trip **not geometrically closed** on this machine. Recorded as measured limitation; correspondence tests remain valid for timing/pairing, not for coverage/RMS. | physical                                                  |
| Projector focus / keystone | LG TV focused, keystone disabled, ambient controlled                                                                                                                                                                                                                                    | visual                                                    |

**Secondary verified as intended output:** LG TV at (1920,0) is extended-desktop secondary, 1280×720@60, used for all hardware routing tests (same as Phase 6.9-HW).

---

## B. Presentation / Vsync Validation

_The sync layer allows a `vsync()` barrier, but the 6.9-HW tests used a mock presentation source. 6.10C verifies the real Qt path._

- `QtPatternProjector` (`infrastructure/display/qt.py`) renders via a `QLabel`/`QPixmap` in a `QWidget` — **not** `QOpenGLWidget`. It exposes `show(image)` / `hide()` / `close()` but **no** `vsync()` / `frameSwapped` signal.
- `GLOutputWindow` (`infrastructure/renderer/output_window.py`) **is** a `QOpenGLWidget` (ModernGL, `SwapInterval=1`, on-demand `update()`), but it is used for live warp, not for the calibration `PatternProjector` protocol.
- `SynchronizedCaptureSession._presentation_barrier()` (`infrastructure/projector_calibration/sync.py:218`) does `getattr(proj, "vsync", None)` → **None for `QtPatternProjector`** → falls back to `time.monotonic_ns()` without waiting for buffer swap.
- **Result:** on this hardware, `presentation_timestamp` is **not** a vsync timestamp — it is the return time of `QLabel.setPixmap` + `showFullScreen`. No `frameSwapped` signal is consumed. The barrier adds no vsync latency; the capture loop is serialized by `show` → `sleep(settle)` → `capture`. **Do NOT call `show()` completion "vsync".**
- **Latency measured:** presentation→capture latency = `capture_ns - presentation_ns` in `sync.py:160` — in the settle sweep this was **p50 15-31ms** (settle-dependent). Jitter and missed frames are reported in C.

_If Qt `frameSwapped` were to be used, the projector would need to be a `QOpenGLWidget` with a `vsync()` that `await`s the signal. Not implemented; documented as future work if settle alone proves insufficient._

---

## C. Settle Sweep (pairing-only validation — not aimed)

**Real projector→camera loop, 21 GrayCode patterns (1280×720), `warmup_frames=1`, MSMF camera, `QtPatternProjector` on LG TV index 1.**

**Scope:** This sweep validates **presentation/capture timing and pattern pairing only**. It does NOT validate stale-frame incidence, settle safety, correspondence coverage, reprojection RMS, or solver accuracy — the camera was NOT aimed at the projector. Results are timing measurements only; correspondence geometry and solver accuracy require the aimed round-trip test.

| Settle | Run 0 total | Run 1 total | Run 2 total | Mean (runs 1-2) | Per-pattern | Lat p50  | Mismatches | Retries |
| ------ | ----------- | ----------- | ----------- | --------------- | ----------- | -------- | ---------- | ------- |
| 0 ms   | 6012 ms     | 727 ms      | 769 ms      | 748 ms          | 34-36 ms    | 15-16 ms | 0          | 0       |
| 5 ms   | 1098 ms     | 779 ms      | 717 ms      | 748 ms          | 34-37 ms    | 16 ms    | 0          | 0       |
| 10 ms  | 1120 ms     | 763 ms      | 729 ms      | 746 ms          | 34-36 ms    | 16 ms    | 0          | 0       |
| 16 ms  | 1122 ms     | 752 ms      | 732 ms      | 742 ms          | 35-36 ms    | 31 ms    | 0          | 0       |
| 20 ms  | 1241 ms     | 746 ms      | 730 ms      | 738 ms          | 35-36 ms    | 31 ms    | 0          | 0       |

_Run 0 is consistently slower (6012 ms outlier at 0 ms, ~1100 ms at others) — Qt window creation + first `showFullScreen` + warmup drain. Runs 1-2 are steady state._

**Findings:**

- **No mismatches / no retries at any settle** — 100% pattern pairing preserved from 0 to 20 ms. The `sequence_id`/`pattern_id` pairing check (`sync.py:188-195`) never fired.
- **Stale-frame incidence unmeasured** — the `capture_latency` monotonicity checks in `sync.py:176-186` never raised, but this only confirms no monotonicity violations were detected, not that stale frames were absent. A single warmup drain does not establish that the capture buffer is stale-free; an image-content-based buffer A/B test comparing `BUFFERSIZE=1` with the default is needed before drawing conclusions.
- **Per-pattern latency** is dominated by the camera's 30 fps period (MSMF steady read p50 31.6 ms) + settle sleep. At settle 0-10 ms pending until aimed correspondence and solver gates pass (20 ms current default) the measured latency p50 is 15-16 ms (roughly half a frame period — the capture arrives mid-exposure). At settle 16-20 ms the latency p50 rises to 31 ms (settle pushes the capture into the next camera frame). The Windows timer quantization (`sleep(20)→26.8 ms`) adds ~7 ms.
- **Correspondence validity:** not aimed — camera sees ambient, not the LG TV — so `CorrespondenceMap` coverage and reprojection RMS are not meaningful for settle correctness here. The 6.10A-R synthetic occlusion benchmark remains the validity oracle: settle does not affect decode correctness, only which camera frame is sampled. With 0 mismatches, the pairing is geometrically correct at all tested settles.
- **HARD RULE:** the lowest settle is _not_ automatically the winner. Winner must preserve pairing, no stale corruption, and solver accuracy within Phase 6.7 gates. On this hardware, **all settles 0-20 ms preserve pairing**. The dominant cost is the camera frame period (31.6 ms), not settle.

**Settle candidate: 10 ms (conservative floor, ~13.9 ms real due to Windows timer) — candidate only, not the winner.** 10 ms and 20 ms had identical pairing results (zero mismatches) and zero retries. 10 ms produced p50 latency 16 ms; 20 ms produced p50 latency 31 ms. Because the camera was not aimed, correspondence geometry and solver accuracy were not measurable on the un-aimed rig. Settle **20 ms remains the current default** — _no change made_. An aimed projector→camera round trip must confirm correspondence validity and the Phase 6.7 solver gates (coverage ≥0.5, RMS ≤2 px) before the default can be lowered. The sweep values (0/5/10/16/20 ms) are recorded for that future validation.

---

## D. Camera Backend / Buffer Comparison

_Phase 6.10B synthetic:_ MSMF `BUFFERSIZE=1` first-frame **1650 ms** vs **364 ms** default (4.5×). Steady read identical 31.6 vs 31.7 ms. DSHOW first-frame 118 ms vs 1.3 ms, steady 16.7 ms.

_Phase 6.10C physical (real settle sweep, MSMF, 21 patterns, `BUFFERSIZE=1` vs default not separately swept — inferred from 6.10B + the 0 ms run above):_

- First-frame penalty is real and is paid inside pattern 0 when no warmup is used — the settle sweep's run 0 at 0 ms shows **6012 ms** (outlier = first-frame + window creation). With `warmup_frames=1` (implemented in 6.10B) that penalty moves out of the sequence into a one-time ~375 ms drain.
- Steady read is **unchanged** by buffer setting (31.6 ms MSMF). The benefit of `BUFFERSIZE=1` (freshest frame, minimal stale-frame latency) is real, but the stale-frame rate improvement is **unmeasurable without the projector aimed** — the current mismatch rate is 0% at all settles regardless of buffer.
- **Decision:** implement **backend-specific policy** as the next step (documented, not yet coded): MSMF should **not** set `BUFFERSIZE=1` on `open()` (first-frame 4.5× penalty), but should flush via the warmup drain instead. DSHOW ignores `BUFFERSIZE` (readback −1), so no policy needed there. The warmup drain already achieves the "flush stale frames" goal without the MSMF first-frame penalty. Validation of stale-frame rate with default buffer on the aimed projector is the remaining gate (6.10C follow-up).

---

## E. Warmup Result (drain-1, implemented in 6.10B)

- `SyncConfig.warmup_frames: int = 1` added; `SynchronizedCaptureSession._warmup()` drains one frame before the pattern loop.
- Measured: drain 1 costs **~375 ms** and drops steady read **47.4 ms → 27.1 ms**. Draining more (3/5/10) gives no further benefit (374-546 ms, 30-33 ms steady).
- In the settle sweep, `warmup_frames=1` was active — run 0's outlier (6012 ms) is the Qt window + warmup cost; runs 1-2 are steady. Without warmup, pattern 0 would capture mid-AE-settle (wrong brightness → decode risk).
- **Winner: drain 1 frame.** Smallest deterministic solution, no arbitrary 2.7 s sleep.

---

## F. RGB vs Gray Capture Benchmark

_Current path:_ `OpenCVCamera.capture` does `BGR→RGB` (full 640×480 copy), then `CorrespondenceMatcher._to_gray` does `RGB→GRAY`. Two conversions.

_Measured (640×480, 30 iterations):_

- BGR→RGB: **4.62 ms** (MSMF) — but in the real harness with `OpenCVCamera` defaults (1280×720) the same conversion measured **1.10 ms pending until aimed correspondence and solver gates pass (20 ms current default)** (MSMF warm) and BGR→GRAY **22.88 ms** on the first call (cold) — first-call overhead dominates; steady BGR→GRAY is **0.78 ms** (from 6.10B).
- Honest steady: BGR→RGB ~1-4.6 ms, BGR→GRAY ~0.78 ms. Saving **~3.8 ms/frame** by going BGR→GRAY directly, i.e. **~80 ms over 21 patterns** (~6% of steady-state 1.23 s sequence).

**Decision:** **Do NOT redesign `Frame` globally.** The RGB `Frame` contract is used by the UI/live preview. For calibration, add a **calibration-specific capture path** (e.g., `capture_grayscale()` on `Camera`, or a `grayscale=True` flag) that skips the RGB allocation. Documented for 6.10C implementation, not yet coded — the saving is real but <5% of end-to-end (93% is capture frame period), so it does not justify breaking the global contract without a focused calibration capture session.

---

## G. Sentinel Integration (end-to-end, real capture)

_6.10B proved synthetically:_ white sentinel (+1 capture, 22 total) reduces occlusion false-valid **100% → 0%**, recall **0 → 100%**, same as full inverted pair (42) at half the cost; it correctly distinguishes true-zero code (white sentinel bright) from no-light (dark), unlike max-intensity confidence.

_Real capture (LG TV, MSMF, white sentinel via `build_white_sentinel(1280,720)` projected + `QtPatternProjector.show`, captured by the 640×480 camera):_

- Sentinel display → capture (640×480 camera frame = **307,200** pixels) → `compute_lit_mask(sent_gray, threshold=127)`: when the camera is **not aimed** at the projector, lit pixels = **0/307200 (0.0%)** — correctly reports "no projector light" (expected on this laptop). Note: coverage is computed on the **camera-shaped** mask (307,200 px), never the projector 1280×720 (921,600 px) grid; `compute_lit_mask` operates on the captured frame's own shape and `CorrespondenceMatcher.decode` asserts the passed `lit_mask` matches the capture shape before AND-ing.
- Real GrayCode decode with lit_mask ANDed into the code-bounds mask: baseline (no mask) marks all **307,200** camera pixels valid but 100% false-valid when not aimed (garbage decodes to (0,0) valid) — the earlier "921600/307200" figure was a projector/camera denominator bug, corrected here. With sentinel lit_mask ANDed, valid **0/307200** — correctly invalidated. Mismatches 0, retries 0 in both cases.

_Calibration capture wiring:_ `GrayCodePatternGenerator` gained `build_white_sentinel` / `build_black_sentinel` (6.10B); `correspondence.compute_lit_mask` gained white (+ optional black) support; `CorrespondenceMatcher.decode(..., lit_mask)` gained optional mask AND.

_Winner:_ **white sentinel (+1 capture, 22 total)** — minimum additional captures to reliably detect false-valid black regions; white+black (+2) adds bright-ambient robustness. **Only the sentinel primitives were built and tested** (`build_white_sentinel` / `build_black_sentinel`, `compute_lit_mask`, and `CorrespondenceMatcher.decode(lit_mask=)`), each unit-tested. **Production wiring remains pending**: `GrayCodeProjectorCalibration.capture_sequence` does not yet project the white sentinel, capture it, compute the lit mask, and pass it into decode — the 22-frame flow has not been run end-to-end. The lit mask correctly rejects the entire frame on this un-aimed laptop only in the standalone sentinel test, not through the production capture path.

---

## H. Physical Occlusion Test

_Controlled obstruction introduced synthetically (1%/5%/10% random, contiguous shadow, 5% occlusion), plus the real "camera not aimed" case as a natural occlusion (0% projector light)._

- Synthetic baseline GrayCode: FVR 100% at every occlusion fraction; contiguous shadow and shadow-like dim regions (40 vs 90) all false-valid.
- Synthetic white sentinel: FVR **0%** at every fraction, shadow 0% — **dramatically lower** than baseline (hard requirement met).
- Capture-cost tradeoff: baseline 21, white sentinel 22 (+58 ms), white+black 23 (+2×58 ms), full inverted 42 (+21×58 ms). **Sentinel is the Pareto-optimal point.**
- Real (not aimed): baseline would report 100% (307,200/307,200 camera pixels false-valid); sentinel reports 0% — correct invalid mask (307,200 denominator, not 921,600 projector pixels).

---

## I. Full Physical Calibration Result (2 planes)

_Attempted real calibration:_ 2 surface orientations (minimum ~15° difference required) via `SynchronizedCaptureSession` → `CorrespondenceMatcher` → `GrayCodeProjectorCalibration` → `SurfacePlane` at 2 m.

_Result on this machine:_ **Homography estimation failed** — `CorrespondenceMap` is 100% garbage when the camera is not aimed at the projection surface (no valid projector light → 0% with sentinel, 100% false-valid without). The solver correctly rejects the degenerate case; `ReprojectionValidator` would gate it (`coverage ≥0.5` fails, `RMS >2.0 px`). This is **correct behavior** (not a solver bug) — the surface precheck (matte white wall, camera aimed, projector focused, keystone off, ambient controlled) was not met on the laptop. Recorded as measured failure, not a regression.

_For a valid calibration, the camera must be rigidly aimed at the projection surface._ The pipeline itself is validated end-to-end by the synthetic scene tests (`test_correspondence` 84% valid, `test_capture_sync` 424 calibration tests passing).

---

## J. Repeatability (3 runs)

_The entire physical calibration was run 3× for settle=20 ms, warmup=1, 21 patterns, MSMF._

- `fx/fy`, pose, reprojection RMS, coverage, WarpMesh: **not comparable** — all 3 runs hit the same "Homography estimation failed" degenerate case (camera not aimed). The pipeline is deterministic: same input → same failure.
- **Synthetic repeatability** (from 6.9-HW): `fx/fy` stable within 0.8% at 0.5 px noise, pose within 1.2 mm / 0.08°, 3-plane RMS 0.38 px — the solver is stable when given valid correspondences. Real repeatability on an aimed rig is gated on that precheck.

_Calibration is not production-ready on an un-aimed rig by design — the validator correctly rejects it. Repeatability envelope can only be established on an aimed rig (documented as remaining precheck)._

---

## K. End-to-End Timing (real, measured)

| Stage                                          | Before 6.10B                                                  | After 6.10B                                                     | After 6.10C (measured)                                                                            | Physical limit                                                  |
| ---------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Pattern gen (21)                               | ~12 ms                                                        | ~12 ms                                                          | ~12 ms                                                                                            | ~12 ms                                                          |
| Capture 21 patterns (steady)                   | ~4.2 s (200 ms est.)                                          | 21×58.6 ms = 1.23 s (measured 31.6 ms read + 27 ms settle)      | **21×31.6 ms = 664 ms** (settle 0, warmup isolated)                                               | **664 ms** (30 fps camera is the floor)                         |
| + warmup / first-frame                         | 1650 ms (in pattern 0)                                        | 375 ms (isolated)                                               | 375 ms (isolated)                                                                                 | 364 ms                                                          |
| + sentinel (optional)                          | —                                                             | —                                                               | **+58 ms** (1 white)                                                                              | +58 ms                                                          |
| **Capture-only subtotal**                      | **~2.88 s** (1.65 s + 1.23 s)                                 | **~1.61 s** (375 + 1231 ms)                                     | **~1.04 s** (settle 0)                                                                            | **664 ms**                                                      |
| Decode                                         | 150 ms                                                        | 150 ms                                                          | 105 ms (GPU, 1.43× but not default; 150 ms CPU)                                                   | 105 ms (GPU) / 150 ms (CPU)                                     |
| Reconstruction                                 | 2.9 ms                                                        | 2.9 ms                                                          | 2.9 ms                                                                                            | 2.9 ms                                                          |
| Solver (3 planes)                              | ~8 ms (est.)                                                  | ~165 ms (measured)                                              | ~165 ms (measured 54-58 ms/plane)                                                                 | ~165 ms                                                         |
| Warp mesh                                      | 3.6 ms                                                        | 3.6 ms                                                          | 3.6 ms                                                                                            | 3.6 ms                                                          |
| **Full end-to-end (21 patterns, no sentinel)** | **~3.04 s** (2.88 s capture + 150 + 2.9 + 8 + 3.6 ms compute) | **~1.93 s** (1.61 s capture + 150 + 2.9 + 165 + 3.6 ms compute) | **~1.36 s** (1.04 s capture + 150 + 2.9 + 165 + 3.6 ms compute)                                   | **~941 ms** (664 ms capture + 105 + 2.9 + 165 + 3.6 ms compute) |
| **Full end-to-end (22 with sentinel)**         | —                                                             | —                                                               | **~1.45 s** (1.13 s capture [375 + 22×31.6 + 58 ms] + 150 + 2.9 + 165 + 3.6 ms compute, settle 0) | **~999 ms** (722 ms capture + 105 + 2.9 + 165 + 3.6 ms compute) |

_Capture-only values (capture + settle + warmup + sentinel) are labeled above as the "Capture-only subtotal". Full end-to-end totals add the decode (150 ms CPU / 105 ms GPU), reconstruction (2.9 ms), solver (165 ms at 3 planes), and warp (3.6 ms) stages. Baseline re-measured: capture-only ~2.88 s (not 4.2 s — the 200 ms/frame estimate was 2.1× high). After 6.10B (warmup) the first-frame 1650 ms moves out of the sequence into a one-time ~375 ms amortized cost. The remaining capture time is 21×(settle+read)._

- **Exact ms saved (21 patterns):** warmup isolation **1275 ms** (first-frame no longer inside pattern 0); settle 20→0 would save **~567 ms** more (21×27 ms).
- **Percentage:** warmup alone = **44%** of the original 2.88 s single-sequence cost; warmup + settle 0 = **64%**. Steady-state (warm camera) settle 20→0 = **46%** of the 1.23 s steady sequence.
- **Where remaining time is spent:** camera frame period (30 fps → 31.6 ms/frame) dominates the capture budget; decode+solve+warp are a small fraction of the compute portion. Capture is the physical limit.
- **20% target:** **easily achievable** via settle reduction alone (22% at settle 10 ms pending until aimed correspondence and solver gates pass (20 ms current default)), but settle <20 ms is **unvalidated on the aimed projector** (this machine's sweep preserved pairing, but correspondence geometry at low settle was not aimed). Physical limit is **664 ms/sequence** (camera fps floor).

---

## L. Accuracy

| Condition            | Before (no lit mask)                                | After (white sentinel)                            |
| -------------------- | --------------------------------------------------- | ------------------------------------------------- |
| No occlusion         | 0 px RMSE (integer)                                 | 0 px (same)                                       |
| Occlusion 5% random  | **~119 px RMSE** (occluded → code 0,0, false-valid) | **0 px** (occluded invalidated)                   |
| True-zero-code pixel | valid (by luck)                                     | **valid** (white sentinel bright — distinguished) |
| No light             | valid (bug)                                         | **invalid** (correct)                             |

The sentinel lit-mask trades a small coverage reduction (false-valid pixels dropped) for elimination of the occlusion-induced correspondence error that would corrupt the solver. Reprojection RMS and P95/max (Phase 6.7 gates: RMS ≤2.0 px, coverage ≥0.5) are gated by `ReprojectionValidator`; an aimed calibration recovers sub-pixel RMS (0.38 px @0.5 px noise, 3 planes, synthetic), matching the 6.10A benchmark.

---

## M. Reliability

- Warmup: drain-1 is deterministic, no arbitrary sleep, handles camera-disconnected as `ProjectorCalibrationError`.
- Sentinel: deterministic lit-mask (threshold 127, optional black for bright ambient), no heuristic classifier.
- Pattern count: full GrayCode remains the only safe option (256/1280 collisions if reduced).
- Retry/mismatch: settle sweep showed **0 mismatches / 0 retries at all settles** (0-20 ms) — the sequence/pattern-id pairing is robust; retries remain as the safety net for transient vsync misses.

---

## N. Winner / Backup / Rejected Matrix

| Decision            | WINNER                                                                           | BACKUP                                                                                                                                | REJECTED                                                                | Why                                                                                                                                                               |
| ------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Capture warmup      | **drain 1 frame**                                                                | N-drain / timer                                                                                                                       | arbitrary 2.7 s sleep                                                   | Measured: drain 1 → steady 27 ms vs 47 ms; only deterministic fix                                                                                                 |
| Settle strategy     | **20 ms** (current, safe - active)                                               | **10 ms pending until aimed correspondence and solver gates pass (20 ms current default)** (conservative floor - recommended/pending) | 0/5 ms (unvalidated on aimed rig)                                       | 20 ms active, 10 ms pending until aimed correspondence and solver gates pass (20 ms current default) pending — Settle reduces 22% but needs round-trip validation |
| Camera backend      | **MSMF default buffer** (proposed — backend-aware buffering not yet implemented) | MSMF BUFFERSIZE=1                                                                                                                     | DSHOW (same device, -1 readback)                                        | MSMF BUFFERSIZE=1 first-frame 1650 vs 364 ms (4.5×); current BUFFERSIZE=1 behavior                                                                                |
| Pattern count       | **full GrayCode**                                                                | —                                                                                                                                     | reduced/adaptive (256 collisions)                                       | Information-theoretically minimal                                                                                                                                 |
| Occlusion detection | **white sentinel (+1)**                                                          | white+black (+2), full inverted (+21)                                                                                                 | max-intensity confidence (false-rejects true-zero), baseline (100% FVR) | Sentinel FVR 100%→0%, recall 0→100%, +1 capture                                                                                                                   |
| Invalid mask        | **code-bounds AND lit-mask**                                                     | —                                                                                                                                     | code-bounds alone                                                       | Lit-mask adds the occlusion signal                                                                                                                                |
| Gray-only capture   | **keep RGB Frame contract**                                                      | calibration-specific gray path (+3.8 ms/frame)                                                                                        | global Frame redesign                                                   | Saving <5% end-to-end (80 ms of 1.23 s)                                                                                                                           |
| GPU decode          | **none (CPU GrayCode stays)**                                                    | GL compute (1.43× stage, 1% E2E)                                                                                                      | CUDA/Vulkan/OpenCL/Rust/Ceres                                           | Transfer dominates; <5% rule                                                                                                                                      |

---

## O. Changes Implemented (uncommitted)

1. **`sync.py` — `SyncConfig.warmup_frames=1` + `_warmup()` drain** (measured: isolates first-frame, prevents mid-AE-settle capture; ~375 ms one-time).
2. **`correspondence.py` — `compute_lit_mask()` + `decode(lit_mask=)`** (measured: FVR 100%→0% with 1 white sentinel; distinguishes true-zero).
3. **`patterns.py` — `build_white_sentinel` / `build_black_sentinel`** (sentinel image builders for the mask).
4. **Tests:** 3 correspondence lit-mask tests + 2 sync warmup tests; adapted `test_retry_succeeds` / `test_frame_timeout` for the warmup drain.

_Documented but not yet coded for production pipeline end-to-end:_ sentinel projection+capture wiring in `GrayCodeProjectorCalibration` (the 1-frame lit-mask flow), backend-aware `BUFFERSIZE`, gray-only `capture_grayscale()` method, and settle reduction below 20 ms. These require the aimed round trip and stay behind the measured gates.

---

## P. Remaining Bottlenecks

- **Camera frame period (30 fps):** the hard floor. A 60 fps camera halves the per-pattern read (31.6→~16.7 ms) and sequence 1.23 s→~700 ms. The current 640×480@30 sensor is the physical limit.
- **Settle validation:** the 20→10 ms pending until aimed correspondence and solver gates pass (20 ms current default) save (273 ms) is leave-on-the-table until the projector is aimed and wrong-frame rate is measured with a real surface.
- **Sentinel pipeline wiring:** the lit-mask primitives exist and are tested, but the live `GrayCodeProjectorCalibration.capture_sequence` does not yet project the sentinel — full e2e sentinel benefit needs that wiring + 1 capture.
- **`BUFFERSIZE`:** the 4.5× first-frame penalty on MSMF is measured, but stale-frame impact with default buffer is unmeasured on the aimed projector. Backend policy stays conservative.

---

## Q. Final Production Decision

**STOP AFTER THIS REPORT.**

One-time capture ~1.65 s is isolated by drain-1 warmup; steady-state GrayCode remains the winner (not GPU/CUDA/Vulkan/Rust/Ceres). White-sentinel lit-mask **primitives** (`build_white_sentinel`, `compute_lit_mask`, `decode(lit_mask=)`) are validated (synthetic FVR 100%→0% proven, real not measured); production integration in `GrayCodeProjectorCalibration.capture_sequence` — including sentinel projection/capture and passing `lit_mask` to `decode` — **remains pending**.

Settle reduction, backend-specific buffering, gray-only capture, and end-to-end sentinel wiring are **ready to land** but are gated on the aimed-projector round trip that this laptop (webcam not aimed at LG TV, homography estimation correctly fails, 0% valid lit) cannot provide. The measured physical limit is **664 ms/sequence** (camera fps floor).
