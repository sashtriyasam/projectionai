# Phase 6.10E — Optical Closure Check

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Hardware precondition — NO source modification, NO commit

---

## A. Camera Physical Position

- Device: `idx 0 = MSMF 640×480@30fps`, laptop integrated webcam
- Position: fixed on laptop lid, optical axis points **away from** LG TV (toward user / room interior)
- Mount: laptop chassis, not tripod, not aimed at projection surface
- Resolution: 640×480 (default), 640×480 (MSMF probe), backend `MSMF`
- Exposure: auto (`CAP_PROP_EXPOSURE -6`, `CAP_PROP_AUTO_EXPOSURE 0` = auto)
- Gain: `-1` (auto)
- Stability: camera is stable but **not viewing the LG TV**

## B. Projector / Display Physical Position

- Device: `LG TV SSCR2` secondary display `\\.\DISPLAY1` → `LG TV SSCR2`
- Index: 1 (via `list_displays()` / `QtPatternProjector(screen_index=1)`)
- Resolution: 1280×720 @60Hz at geometry (1920,0) — extended desktop
- Focus: LG TV panel focused, keystone OFF, refresh fixed 60Hz
- Presentation: `QtPatternProjector` via `QLabel/QPixmap` on LG TV, `WHITE` / `BLACK` (hide) verified via `show()` / `hide()` with 300ms settle

## C. Surface

- Target: LG TV panel itself (self-illuminating, not diffuse wall) — but camera does **not** view it
- Intended surface for closure: matte white wall/screen that **fills enough of the camera image** — not present in current rig
- Camera view: room interior / user, **no matte target**, ambient only
- Result: projected white/black has **zero** measurable effect on camera (see D)

## D. WHITE / BLACK Differential (closure gate)

**Gate requirement:** `pixels(|WHITE-BLACK| > 20) > 5%` and visual confirmation that changed region is the projected surface. Auto-exposure "lit%" alone is NOT evidence — use differential.

**Run 1 (6.10D, with auto-exposure settling):**

- WHITE mean 17.1 std 0.9, BLACK mean 17.0 std 0.8, WHITE2 17.0
- WHITE-BLACK diff mean 0.70, max 9, `pixels>20 = 0/307200 (0.00%)` → **FAIL**

**Run 2 (6.10E re-check, same rig, fresh):**

- WHITE mean 16.7 std 0.7, BLACK mean 16.8 std 0.7, WHITE2 16.8
- WHITE-BLACK diff mean **0.60**, max **5**, `pixels>20 = 0/307200 (0.00%)` → **FAIL**
- WHITE2-WHITE stability mean 0.60 (sensor noise floor)

**Verdict on differential:** **0.00%** in both runs. The projector's state change produces **no** measurable change in the camera image. The earlier "39.67% lit" from `compute_lit_mask` on a single WHITE frame was an auto-exposure artifact (mean 117 → bright ambient scene, not projector light).

**Illuminated pixel percentage:** 0.00% (WHITE-BLACK differential), not the single-frame "lit%".

## E. Camera Image Geometry

- WHITE frame: 640×480, mean 16.7, std 0.7, dark scene
- BLACK frame: 640×480, mean 16.8, std 0.7, dark scene (identical)
- Projector image expected region: LG TV 1280×720 at (1920,0) → when viewed by camera, should occupy a quadrilateral in the camera image. **Not visible** — no corners, no clipping to assess, no saturation (entire frame dark).
- No severe clipping / no saturation across entire frame — **entire frame is uniformly dark**, consistent with camera pointing away.

## F. Ambient / Exposure State

- Ambient: indoor, controlled, dark scene (mean ~17/255)
- Exposure: auto (`CAP_PROP_AUTO_EXPOSURE 0`), compensates to keep mean ~17; auto-exposed WHITE/BLACK comparisons are **not definitive evidence of blocked geometry** — similar captured images (mean delta 0.60) could be AE masking. Fixed manual exposure (`CAP_PROP_AUTO_EXPOSURE 0.25` / manual) or per-frame exposure/gain verification is required before concluding the optical loop is geometrically blocked.
- Current measurements show only that WHITE and BLACK captures are similar under auto exposure (0.00% >20), not proof of blocked loop.

## G. Closure Verdict

**OPTICAL LOOP STATUS: INCONCLUSIVE UNDER AUTO EXPOSURE — REQUIRES FIXED EXPOSURE VERIFICATION**

- WHITE vs BLACK differential under auto exposure shows similar images (0.00% pixels >20, max delta 5-9, mean delta 0.60-0.70) — this is not definitive proof that projector light does not reach the camera; it shows only similar captures that could be AE-masked.
- The webcam (MSMF 640×480 on laptop) **may** not be aimed at the LG TV, but without fixed/verified exposure this cannot be concluded as the exact blocker.
- No settle, buffer, sentinel, or calibration optimization can be validated until repeat with fixed manual exposure and verified equal exposure/gain shows `pixels>20` differential.

## H. Exact Evidence (reproducible)

```
# Gate test:
<user>\AppData\Local\Temp\opencode\phase610d_diff.py
# Projector: QtPatternProjector(screen_index=1) → LG TV SSCR2, WHITE 1280×720 vs hide()
# Camera: cv2.VideoCapture(0, CAP_MSMF), 640×480@30, BUFFERSIZE=1, drain 1, sleep 300ms

Run 2 (6.10E):
  WHITE  mean=16.7 std=0.7
  BLACK  mean=16.8 std=0.8
  WHITE2 mean=16.8 std=0.8
  WHITE-BLACK diff: mean=0.60 max=5 pixels>20=0/307200 (0.00%)
  => FAIL: 0.00% < 5% threshold — STOP
```

**Required physical action (exact, minimal):**

1. Mount the camera on a tripod / stable support facing the LG TV.
2. Center the LG TV's projected white area in the camera view so that **entire projected area is visible** and fills ~30-70% of the camera image (not clipped, not tiny).
3. Fix projector focus, disable keystone, fix 1280×720 @60Hz.
4. Place a matte/diffuse white target (wall/screen) where the camera can see the projection, if LG TV is self-emissive and creates specular issues.
5. Re-run ONLY the closure test above; expect `pixels>20 > 5%` and a coherent bright rectangle in the absolute-difference image. The `mean WHITE-BLACK > ~20` is diagnostic data only — not a formal gate — unless formally approved as an additional criterion.

**STOP AFTER REPORT.** No source change, no commit. Next phase may run only after this gate passes.
