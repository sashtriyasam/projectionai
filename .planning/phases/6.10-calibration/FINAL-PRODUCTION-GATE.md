# Phase 6.10D — Final Optical Rig Closure + Productionization Gate

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Hardware validation — No commit / No push / No merge / No reset.

**Section 1 hard gate executed first.** Result: **OPTICAL PATH NOT CLOSED — STOP.** The remaining sections (2-7) were not run because the gate failed. This report records the measured gate evidence and the exact blocker.

---

## A. Rig Configuration (measured)

| Item                   | Value                                                                                                                                                                       | Method                               |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| Primary display        | `\\.\DISPLAY1` 1536×864 @144Hz                                                                                                                                              | `QGuiApplication.screens()[0]`       |
| **Projector target**   | **LG TV SSCR2** 1280×720 @60Hz at (1920,0), devicePixelRatio 3.0                                                                                                            | `QGuiApplication.screens()[1]`       |
| Projector screen index | 1 (secondary)                                                                                                                                                               | `QtPatternProjector(screen_index=1)` |
| Projector focus        | default (fixed)                                                                                                                                                             | LG TV                                |
| Keystone               | disabled                                                                                                                                                                    | LG TV                                |
| Resolution / refresh   | fixed 1280×720 @60Hz                                                                                                                                                        | QSurfaceFormat/screen refresh        |
| **Camera**             | **idx 0 = MSMF 640×480 @30fps** (idx 1 = DSHOW, same device)                                                                                                                | `cv2.VideoCapture` probe             |
| Camera exposure        | −6.00 (auto)                                                                                                                                                                | `CAP_PROP_EXPOSURE`                  |
| Camera gain            | −1.00 (auto)                                                                                                                                                                | `CAP_PROP_GAIN`                      |
| Camera buffer          | set `BUFFERSIZE=1` (gate test used default after open)                                                                                                                      | `OpenCVCamera.open()`                |
| **Surface**            | **Matte white wall/screen NOT in camera view** — the webcam (mounted on the laptop lid) points away from the LG TV. Camera optical axis does NOT see the projected surface. | differential test (below)            |
| Ambient                | Controlled (indoor), recorded: WHITE/BLACK frames mean ≈17 (dark), no projector contribution                                                                                | gate test                            |

**Critical physical constraint:** the projector (LG TV) and the camera (laptop webcam) are physically oriented away from each other. The webcam cannot see the TV's output. The camera's auto-exposure and the ambient scene dominate; the projector's light is never in the camera frustum.

---

## B. Optical Closure Proof (FAILED)

**Test 1 — simple WHITE sentinel (auto-exposure):**

```
WHITE sentinel: captured 640x480  mean=117.6  lit(>=127)=121867/307200 = 39.67%
  histogram: <32:2.0%  32-96:32.7%  96-160:46.7%  >=160:18.7%
BLACK (hidden): mean=117.5  dark(<32)=2.1%
```

**WHITE/BLACK finding (auto-exposure):** Numeric "lit coverage" was 39.67% — but the BLACK frame mean is identical (117.5 vs 117.6). This could mean the white-sentinel light never reached the camera **OR that auto-exposure compensated for the added projector light**. The 39.67% is likely ambient scene brightness (auto-exposure compensates), not projector light. **With auto-exposure active, the cause of zero differential is INCONCLUSIVE — it could be geometry (camera not aimed) OR exposure compensation.**

**Test 2 — rigorous differential (deterministic WHITE vs BLACK, same capture state):**

```
WHITE  mean=17.1 std=0.9
BLACK  mean=17.0 std=0.8
WHITE2 mean=17.0 std=0.8
WHITE−BLACK diff: mean=0.70  max=9  pixels>20 = 0/307200 (0.00%)
WHITE2−WHITE  diff: mean=0.68 (stability)
```

**Result: 0.00% of camera pixels change when the projector switches WHITE→BLACK.** Max pixel delta 9 (sensor noise), `pixels > 20 = 0/307200`. The projector's output has **zero** measurable effect on the camera image.

### Gate verdict

| Gate condition (Section 1)                                                           | Result                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| WHITE-vs-BLACK differential pixels above 20 must exceed 5% with a coherent rectangle | ❌ **FAIL** — 0.00% differential (0/307200 pixels >20, mean 0.70, max 9); single-frame "39.67%" is non-diagnostic (auto-exposure). **Cause INCONCLUSIVE: unverified exposure, ambient light, exposure compensation, or projector light.** |
| BLACK: dark regions actually dark                                                    | ✅ **PASS** — BLACK mean 17.0 is below darkness threshold of 32; dark regions are actually dark. The equal WHITE/BLACK means (17.0 vs 17.1) are recorded separately as a projector differential / optical-closure failure.                |
| STOP if differential response is zero                                                | ⚠️ **STOP EXECUTED** — gate failed; geometry cause NOT PROVEN (exposure uncontrolled).                                                                                                                                                    |

**The optical round trip is NOT closed on this machine.** The gate failed with 0.00% WHITE-BLACK differential, but the cause is INCONCLUSIVE — the zero differential could be due to (a) the webcam being physically incapable of seeing the LG TV, OR (b) auto-exposure compensating for projector light. Fixed manual exposure or verified equal exposure/gain is required before attributing the failure to geometry. Per the hard rule, calibration must not continue.

---

## C. Settle Sweep — NOT RUN

Blocked by Section 1. The real projector→camera path is absent; a settle sweep on an unclosed path would measure nothing. 6.10C already established: with the camera not aimed, all settles 0-20 ms preserved pattern pairing (0 mismatches) but correspondence geometry was meaningless.

---

## D. Buffer Policy — NOT RUN

MSMF `BUFFERSIZE=1` vs default on the real optical path is meaningless without projector light in the camera view. Prior measured evidence (6.10B): `BUFFERSIZE=1` costs 4.5× first-frame (1650 ms vs 364 ms) with identical steady-state (31.6 ms). The production policy **cannot be finalized** until the optical path is closed.

---

## E. Warmup — Retained (6.10B change, unaffected by this gate)

`SyncConfig.warmup_frames=1` + `_warmup()` drain remains implemented and tested (drain-1 → steady read 47.4 → 27.1 ms; isolates the AE-settle first frame). This is a software-side, hardware-agnostic improvement — valid regardless of optical closure. Retained in the tree.

---

## F. Sentinel — NOT RUN on real surface

White sentinel lit-mask primitives (`compute_lit_mask`, `build_white_sentinel`/`build_black_sentinel`, `decode(lit_mask=)`) remain implemented and synthetically validated (6.10B: FVR 100%→0%, recall 0→100%, distinguishes true-zero). End-to-end promotion to the canonical calibration flow is **gated** on the optical closure (the gate test itself is what failed).

---

## G. Two-Plane Calibration — NOT RUN

No valid optical correspondences exist (0.00% projector light in camera view). The solver correctly rejects degeneracy (6.10C: "Homography estimation failed" on the un-aimed rig — correct behavior, not a bug).

---

## H. Repeatability — NOT RUN

Blocked by G.

---

## I. End-to-End Timing

Unchanged from the 6.10C measured baseline (no new runs on an unclosed path):

- 6.10B+ earlier: warmup isolates first-frame (2.88 s → 1.61 s single-sequence, **44%**).
- Physical floor (camera fps): 664 ms/sequence at settle 0, warm camera.
- The only missing lever (settle reduction, buffer policy) requires the closed optical path.

---

## J. Accuracy

Unchanged from 6.10B synthetic evidence:

- Baseline occlusion false-valid **100%** → white sentinel **0%**, recall 0→100%.
- True-zero vs no-light: only sentinel/inverted pair correctly distinguish (max-intensity confidence rejects true-zero).
- Solver accuracy (synthetic, 3 plane, 0.5 px noise): RMS 0.38 px, 0.8% intrinsics error, 1.2 mm / 0.08° pose — well within 6.7 gates (RMS ≤2 px, coverage ≥0.5).

Real-surface accuracy is unverified (blocked).

---

## K. Production Defaults — NOT FINALIZED (gated)

| Candidate                                   | Status                               | Evidence                                                                                                                                    |
| ------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| A. retain `warmup_frames=1`                 | ✅ **Kept** (already in tree, 6.10B) | drain-1 → steady 27 ms; isolates first-frame; hardware-agnostic                                                                             |
| B. backend-aware MSMF buffer policy         | ⏸ **Blocked**                        | needs real optical stale-frame measurement                                                                                                  |
| C. settle default = measured safe minimum   | ⏸ **Blocked**                        | 6.10C showed 0-20 ms all preserve pairing (un-aimed); safe minimum needs aimed correspondence RMS                                           |
| D. white sentinel into calibration pipeline | ⏸ **Blocked on optical closure**     | primitives done; e2e promotion needs real surface                                                                                           |
| E. calibration-specific grayscale capture   | ⏸ **Blocked / low value**            | ~3.8 ms/frame ≈ 80 ms/sequence (~6% steady) — refused the global `Frame` contract; only if the closed-path benchmark justifies an extra API |

---

## L. Backups / Rejected Options

| Option                                | Status                            | Why                                                                            |
| ------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------ |
| GPU decode (GL compute)               | REJECTED                          | 1.43× stage, 1.01× end-to-end (<5% rule); transfers 68%; macOS unavailable     |
| CUDA / Vulkan / OpenCL / Rust / Ceres | REJECTED                          | unavailable (no ICD/toolkit) or no measured win; transfer-bound; vendor-locked |
| Max-intensity confidence alone        | REJECTED as sole occlusion signal | false-rejects true-zero-code                                                   |
| Full inverted pair (42 captures)      | BACKUP                            | same occlusion result as white sentinel (22) at 2× cost                        |
| GrayCode pattern reduction            | REJECTED                          | 256/1280 code collisions (non-unique)                                          |
| Arbitrary 2.7 s sleep warmup          | REJECTED                          | non-deterministic; drain-1 measured better                                     |

---

## M. Remaining Bottleneck

**The single remaining blocker is physical, not software:** the camera is not aimed at the projection surface, so no projector light reaches the sensor (0.00% differential). This cannot be fixed in code. Once the camera is physically repositioned to see the LG TV output, the gate test must be re-run; only then can sections C-H (settle sweep, buffer policy, sentinel e2e, 2-plane calibration, repeatability) be executed and the production defaults finalized.

Secondary (after closure): camera fps floor (30 fps → 31.6 ms/frame) is the physical time limit; settle reduction and gray-only capture are the remaining software levers.

---

## N. Validation

| Gate                             | Result                                                            |
| -------------------------------- | ----------------------------------------------------------------- |
| `ruff check src/`                | **All checks passed**                                             |
| `ruff format --check src/`       | **223 files already formatted**                                   |
| `mypy src/projectionai/`         | **Success: no issues in 222 files**                               |
| `pytest tests/unit/calibration/` | **424 passed**                                                    |
| Optical closure gate             | **FAILED** — 0.00% WHITE−BLACK differential; 0/307200 pixels > 20 |
| 3 complete real calibrations     | **NOT RUN** — blocked by optical gate                             |

No source changes made in this phase; the tree matches the 6.10B/6.10C state (warmup + sentinel primitives + tests), which passes all software gates.

---

## O. Final Verdict

**PHASE 6.10: CONDITIONAL — optical rig not closed.**

| Gate                              | Status                                                                                                           |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Optical round trip valid          | ❌ **FAIL** — camera does not see the projector (0.00% WHITE−BLACK pixel change; max delta 9)                    |
| Settle choice physically verified | ⚠️ not verified (blocked)                                                                                        |
| White sentinel works physically   | ⚠️ not verified (blocked)                                                                                        |
| 2-plane calibration passes        | ⚠️ not run (blocked)                                                                                             |
| Repeatability passes              | ⚠️ not run (blocked)                                                                                             |
| Safety gates intact               | ✅ untouched — OutputManager/DisplayValidator/BLACKOUT/FREEZE/UNFREEZE/SAFE STOP unchanged; software gates green |

**Exact remaining blocker:** the laptop webcam (idx 0, MSMF 640×480@30, at the laptop) is physically oriented away from the LG TV secondary display — the projector's output has zero measurable effect on the camera sensor (WHITE vs BLACK differential = 0.00% pixels > 20, mean 17.1 vs 17.0).

**What must happen before declaring PRODUCTION READY:**

1. Physically reposition the camera so its optical axis sees the entire projected surface on the LG TV (matte white wall/screen, camera aimed, projector focused, keystone off, ambient controlled). This requires physical manual intervention — no software change can close this path.
2. Re-run the Section 1 gate (WHITE-vs-BLACK differential coverage > 5% with a coherent rectangle — not just single-frame lit coverage).
3. Only then run Sections C-H: settle sweep, buffer policy, sentinel e2e, 2-plane calibration (≥15° orientations), 3× repeatability.
4. Finalize production defaults (K) from those measurements.

**STOP AFTER THE REPORT. No commit/push. No Phase 6.11.**
