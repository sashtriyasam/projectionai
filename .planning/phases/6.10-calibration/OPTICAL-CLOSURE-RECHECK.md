# Phase 6.10F — Optical Closure Recheck

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Hardware precondition — NO source modification, NO commit (recheck only)

**Precondition:** Laptop physically repositioned so built-in webcam faces LG TV per 6.10E instructions.

---

## Camera Configuration

- Device: `idx 0 = MSMF 640×480@30fps` (also `idx 1 = DSHOW` same physical device)
- Backend: `MSMF` (probe shows `CAP_MSMF` 640×480 fps 30.0, exposure -6.00 auto, gain -1.00 auto)
- Resolution: 640×480 (requested and readback 640×480)
- Exposure: auto (0 / -6), gain auto, brightness 0, contrast 50
- Buffersize: 1 (set in `OpenCVCamera.open()`, previous phases), warmup drain 1 used in gate harness

## Display Configuration

- Projector target: `LG TV SSCR2` 1280×720 @60Hz at (1920,0), index 1 via `QtPatternProjector(screen_index=1)`
- `WHITE` pattern: `np.full((720,1280),255,uint8)` full-white via `QtPatternProjector.show()`
- `BLACK`: `hide()` (black 1×1 pixmap)

## Measured WHITE / BLACK / WHITE2 Statistics

| Capture                             | Mean                                                        | Std  | Lit(>=127)                                                              | Histogram <32 / 32-96 / 96-160 / >=160   |
| ----------------------------------- | ----------------------------------------------------------- | ---- | ----------------------------------------------------------------------- | ---------------------------------------- |
| WHITE                               | 64.6                                                        | 33.5 | 121867/307200 (39.67% lit) — single-frame lit% (ambient, auto-exposure) | 2.0% / 32.7% / 46.7% / 18.7% (first run) |
| BLACK                               | 64.6                                                        | 33.5 | —                                                                       | 2.1% dark (<32)                          |
| **WHITE** (recheck)                 | **64.6**                                                    | 33.5 | —                                                                       | —                                        |
| **BLACK** (recheck)                 | **64.6**                                                    | 33.5 | —                                                                       | —                                        |
| **WHITE2**                          | **64.6**                                                    | 33.5 | —                                                                       | —                                        |
| **Differential recheck (rigorous)** | WHITE 64.6 std33.5, BLACK 64.6 std33.5, WHITE2 64.6 std33.5 |      |                                                                         |                                          |

**Authoritative differential (WHITE vs BLACK, same camera settings, 300ms settle):**

| Metric                                | Value                     |
| ------------------------------------- | ------------------------- |
| WHITE mean                            | 64.6                      |
| BLACK mean                            | 64.6                      |
| WHITE2 mean                           | 64.6                      |
| WHITE-BLACK absolute difference: mean | **1.95**                  |
| WHITE-BLACK absolute difference: max  | **14**                    |
| pixels with `abs(WHITE-BLACK) > 20`   | **0 / 307200 (0.00%)**    |
| WHITE2-WHITE stability mean           | 1.96 (sensor noise floor) |

## Differential Statistics

- `abs(WHITE-BLACK) > 20` is the closure gate (threshold 20 gray levels, >5% required).
- **Result: 0.00%** — **no pixel** changes by >20 when the projector switches WHITE→BLACK.
- Mean delta 1.95 is indistinguishable from inter-frame sensor noise (WHITE2-WHITE mean 1.96).
- Max delta 14 < threshold 20.

The single-frame "lit percentage" (39.67%) is **not** evidence — it reflects auto-exposure behavior, not projector light. Under auto-exposure, the 0.00% changed-pixel result only shows the captures were similar; the projector-light result remains inconclusive.

## Projected-Area Visibility

- LG TV is enumerated as secondary display (index 1, 1280×720 @60Hz at 1920,0) and `QtPatternProjector` reports resolution (1280,720).
- **Camera image:** 640×480 dark/ambient scene, mean ~64, no bright region corresponding to TV. No projected corners visible, no region where WHITE vs BLACK produces a coherent bright rectangle. The TV is not discernible in the camera frame.
- **Clipping:** not assessable — no projected region visible.
- **Saturation:** no — entire frame well below saturation (mean 64, max <160 for 82% of pixels).
- **Ambient contamination:** camera view is ambient-dominated; projector contribution is below noise floor.

## Closure Gate

**PASS condition:** `pixels(|WHITE-BLACK| > 20) > 5%` **AND** changed region corresponds to projected surface, WHITE2 consistent, no exposure-only artifact, **with fixed manual exposure or verified equal exposure/gain for WHITE and BLACK**.

**Result:** **INCONCLUSIVE (exposure not verified/fixed) → FAIL pending recheck**

- Pixels >20 : 0.00% (required >5%)
- Changed region: none (0 pixels)
- WHITE2 consistency: pass (stable), but irrelevant when WHITE never differed from BLACK
- Exposure artifact: **not ruled out** — both frames used auto exposure (0 / -6) without per-frame exposure/gain verification; differential 0 could be AE masking. Gate requires fixed exposure (`CAP_PROP_AUTO_EXPOSURE 0.25` / manual) or verified equal exposure/gain before interpreting 0.00% as geometry failure. Repeat closure test under fixed/verified exposure; if not met, classify as inconclusive rather than proof of absent light/geometry.

## Verdict

**OPTICAL LOOP STATUS: INCONCLUSIVE — HARDWARE INTERVENTION REQUIRED, EXPOSURE UNVERIFIED**

The differential WHITE vs BLACK result is 0.00% changed pixels, but **this does not prove zero projector light reaches the camera sensor**. The test was run with auto-exposure active on both frames. The zero differential could equally result from: (a) the webcam being physically incapable of seeing the LG TV, OR (b) auto-exposure compensating for the added projector light. Without fixed manual exposure or verified equal exposure/gain between WHITE and BLACK captures, the physical root cause remains UNCONFIRMED.

**Exact blocker (provisional):** The MSMF webcam (640×480) optical axis may not see the LG TV projected surface, OR auto-exposure may be masking the projector light. The physical repositioning described in 6.10E has not produced an observable change in the camera image (WHITE vs BLACK differential remains at noise floor, mean ~64 identical). **This is INCONCLUSIVE — it could be physical geometry (camera not aimed) OR exposure compensation masking the light.** Only after fixed manual exposure or verified equal exposure/gain can the zero differential be attributed to camera geometry or absent projector light.

**Required physical action (minimal, exact):**

1. Place the camera on a tripod or stable mount **directly facing the LG TV**, so that the TV's white rectangle fills ~30-70% of the camera image (centered, not clipped).
2. Fix projector focus, disable keystone, keep 1280×720 @60Hz.
3. **Mandatorily** fix exposure (`CAP_PROP_AUTO_EXPOSURE 0.25` / manual) to prevent AE masking, then re-run ONLY `C:\Users\Shivam\AppData\Local\Temp\opencode\phase610d_diff.py` (differential WHITE vs BLACK). Results without fixed/verified equal exposure/gain remain INCONCLUSIVE and must not be attributed to camera geometry or absent projector light.
4. Expect: `pixels>20 > 5%` and a coherent bright rectangle in the absolute-difference image.

## Validation

- No source changes in this phase: `git diff --name-only` shows only the uncommitted changes from 6.10B/C (warmup, lit-mask, sentinel builders); **no new production source modifications in 6.10F** (recheck only, temp scripts in `C:\Users\Shivam\AppData\Local\Temp\opencode\phase610*`).
- No commit/push/merge/reset/checkout/stash/clean performed.
- `D:\PROJECTIONAI-camera` untouched.

## Next Gate

**STOP AFTER THIS REPORT.** Do not run calibration, settle sweeps, or production changes until the differential gate passes.

Next phase may run only after the report shows:

```
OPTICAL LOOP CLOSED — READY FOR FINAL 6.10 CALIBRATION GATE
```

with `pixels(|WHITE-BLACK| > 20) > 5%` and visual confirmation.

STOP AFTER REPORT.
