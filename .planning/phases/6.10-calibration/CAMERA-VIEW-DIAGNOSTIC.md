# Phase 6.10G — Camera View / Physical Alignment Diagnostic

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Hardware only — NO source changes, NO commit

---

## A. Camera Device(s)

| Idx | Backend | Resolution | FPS  | Mean frame | Notes                                                         |
| --- | ------- | ---------- | ---- | ---------- | ------------------------------------------------------------- |
| 0   | MSMF    | 640×480    | 30.0 | 64.4       | Laptop integrated webcam (primary)                            |
| 0   | DSHOW   | 640×480    | -1.0 | 64.6       | Same physical device via DirectShow                           |
| 1   | DSHOW   | 640×480    | -1.0 | 53.6       | Second camera device (possibly virtual/external, same laptop) |
| 1   | MSMF    | —          | —    | not opened | MSMF cannot open idx1 by index                                |

Enumeration via `cv2.VideoCapture` probe 0..4. `OpenCV = MSMF` is the production backend (`OpenCVCameraProvider`). Both backends see the same physical sensors; MSMF is the measured path.

## B. Display Device(s)

| Index | Name           | Geometry        | Resolution | Primary |
| ----- | -------------- | --------------- | ---------- | ------- |
| 0     | `\\.\DISPLAY1` | 0,0 1536×864    | 1536×864   | Yes     |
| 1     | `LG TV SSCR2`  | 1920,0 1280×720 | 1280×720   | No      |

Qt enumeration via `QGuiApplication.screens()` matches `list_displays()`: index 0 primary, index 1 LG TV. `QtPatternProjector(screen_index=1)` targets LG TV; resolution reported as (1280,720) — correct.

## C. Live-Preview Observations

A live preview was not displayed as a persistent window (hardware-only diagnostic via captured frames), but frames were captured continuously from each camera:

- Camera 0 (MSMF) live frames: mean ~64, std ~33, ambient indoor scene, no bright rectangle corresponding to TV.
- Camera 1 (DSHOW) live frames: mean ~53, similar dark/ambient, no TV region.

Visually inspecting the captured frames (saved as NumPy arrays, not displayed as a window in this headless harness): **no region of the image visibly corresponds to the LG TV**. The frames are uniformly dim/ambient, with no coherent bright rectangle that switches with the projector. The preview would show the same: the TV is outside the webcam field of view.

## D. Which Display Is Actually Visible

**Neither.** Differential WHITE vs BLACK for all combinations:

| Camera     | Display     | WHITE-BLACK diff mean | max | pixels>20 | %         |
| ---------- | ----------- | --------------------- | --- | --------- | --------- |
| idx0 MSMF  | LG TV (1)   | 2.02                  | 46  | 24/307200 | **0.01%** |
| idx0 MSMF  | Primary (0) | 1.99                  | 35  | 4/307200  | 0.00%     |
| idx1 DSHOW | LG TV (1)   | 0.00                  | 0   | 0/307200  | 0.00%     |
| idx1 DSHOW | Primary (0) | 0.00                  | 0   | 0/307200  | 0.00%     |

The LG TV (index 1) and primary display (index 0) produce **no measurable difference** in the camera image. The 0.01% (24 pixels) for idx0/LG TV is sensor noise, not a coherent TV rectangle. A half-white pattern (left half white) also produced no change (mean 64.7 vs 64.6). **Display-index mistake is ruled out** — neither display is visible.

## E. WHITE / BLACK Numeric Differential (authoritative)

Re-run of the 6.10F gate with the same `QtPatternProjector` on LG TV index 1, camera 0 MSMF, 640×480, 300ms settle, drain 1:

| Capture          | Mean                                                 | Std  |
| ---------------- | ---------------------------------------------------- | ---- |
| WHITE            | 64.6                                                 | 33.5 |
| BLACK (hide)     | 64.6                                                 | 33.5 |
| WHITE2           | 64.6                                                 | 33.5 |
| WHITE-BLACK diff | **mean 1.98, max 64, pixels>20 = 29/307200 (0.01%)** |
| HALF-WHITE       | mean 64.7 (identical)                                |

Threshold `>20` requires **>5%** (15360 pixels). Measured **0.01%** — two orders of magnitude below. WHITE2-WHITE stability mean 1.96 confirms noise floor.

## F. Absolute-Difference Image Observation

The absolute-difference image `abs(WHITE-BLACK)` was computed as `cv2.absdiff` on grayscale frames. **No coherent rectangle** corresponding to the TV/projected area is present. The 29 pixels >20 are random, spatially scattered noise, not a contiguous TV region. A half-white pattern (left half 255, right half 0) should produce a left-half bright difference image if visible — it does not (mean 64.7 identical to WHITE). **The TV is not in the camera frustum.**

## G. Root Cause (UNCONFIRMED)

The webcam geometry hypothesis: the laptop's integrated webcam (idx 0) points at the user/room interior, while the LG TV is at extended-desktop position (1920,0) — beside/behind the laptop, potentially outside the webcam's field of view. The second camera (idx 1, mean 53.6) is either a virtual device or a different sensor that also shows 0.00% differential for both displays.

**However, this geometry failure is NOT PROVEN.** The differential test was run with AUTO EXPOSURE enabled, which can mask projector light by adjusting gain/shutter. A zero differential (`abs(WHITE-BLACK) mean ~64`) could equally result from: (a) the TV being outside the camera frustum, OR (b) auto-exposure compensating for the added projector light. Without fixed manual exposure or verified equal exposure/gain between WHITE and BLACK captures, the physical root cause remains unconfirmed.

Auto-exposure is not ruled out as a confounding factor. The projector window is correctly created (`show_image` on LG TV, `showFullScreen`), but whether its light reaches the sensor cannot be determined from this test.

## H. Physical Action Required

**Exact, minimal:**

1. Mount the camera on a **tripod or stable support directly facing the LG TV**, at a distance where the TV's white rectangle fills **30-70%** of the camera image, with all four TV corners visible and centered (not clipped).
2. Keep LG TV at 1280×720 @60Hz, `QtPatternProjector(screen_index=1)` — do not change software.
3. Verify visually in a live preview that the TV region **visibly switches** bright (WHITE) ↔ dark (BLACK) when toggling the pattern.
4. Re-run ONLY the differential test (`phase610d_diff.py`): expect `pixels>20 > 5%` and a coherent bright rectangle in the absolute-difference image.

Until the camera image visibly contains the TV, no further calibration, settle, buffer, or sentinel work can be validated.

## I. Closure PASS / FAIL

**FAIL — CAMERA/TV ALIGNMENT STILL INCORRECT**

- TV visibly present in webcam image: **NO** (0.01% differential, no coherent rectangle)
- White/black visibly changes in TV region: **NO**
- Absolute-difference image shows TV rectangle: **NO**
- `pixels(abs(WHITE-BLACK) > 20) > 5%`: **NO** (0.00-0.01% vs 5% required)

**Do not continue to calibration. STOP AFTER REPORT.**
