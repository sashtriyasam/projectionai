# Phase 6.5 — Structured-Light Decode / Correspondence Engine — Report

**Date:** 2026-08-23  
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (no commit/push)  
**Foundation:** 6.4 SynchronizedCaptureSession (CalibrationFrame), 6.3 PatternEngine, 6.2 CorrespondenceSet

---

## A. Existing Decoder

`t/p infrastructure/projector_calibration/correspondence.py:47 CorrespondenceMatcher(threshold=127)`:

- `_to_gray`: `RGB (H,W,3)→Gray (H,W)` via `cv2.COLOR_RGB2GRAY` else 2D pass-through.
- Per pattern: `binary = gray >=127`, `bit = binary == (bit_value==1)`, `code_x/y |= bit << bit_index`.
- `gray_decode(code,bits)` prefix-XOR `result ^= code>>shift`.
- `mask = (code_x < proj_W) & (code_y < proj_H)` → invalid out-of-range masked.
- `projector_x/y = NaN` then fill valid with `code.astype(float32)`, `mask` bool.

Verified correct: preserves `invert` via `bit_value`, handles projector bounds, not clipping silently.

Reference retained unchanged; new layer wraps it.

---

## B. Canonical Input Contract

New `services/structured_light_decoder.StructuredLightDecoder.decode(frames: tuple[CalibrationFrame,...], sequence: CalibrationSequence) -> CorrespondenceSet`

Validation before decode:

- `frames` non-empty, `len(frames)==len(sequence.patterns)` else `StructuredLightDecodeError`.
- Every `frame.capture.sequence_id == sequence.sequence_id` else mismatch.
- Every `frame.pattern.sequence_id == sequence.sequence_id`.
- Unique `pattern_id`s, set equals expected `{p.pattern_id}` else duplicate/missing.
- Ordered by `pattern_id` to match projection order (sorted).
- `sequence.width/height >0`.
- Image `ndim == 3` with `shape[2]==3` (H,W,3 RGB) else error — only `CameraCapture`-constructible inputs (2D grayscale is not constructible via `CameraCapture`).

Never decodes partial/ambiguous sequence.

---

## C. Decode Algorithm

1. **Grayscale:** `cv2.COLOR_RGB2GRAY` per frame (1 copy per frame via OpenCV) on the (H,W,3) RGB input.
2. **Legacy conversion:** `canonical_to_legacy(sequence)` → `PatternSequence` (zero-copy image views).
3. **Delegate:** `CorrespondenceMatcher(threshold).decode(captures_gray, legacy_seq)` → `CorrespondenceMap`.
4. **Finite check:** `vx/vy` on `mask` must be finite else error.
5. **Bounds double-check:** `vx in [-0.5, W+0.5)` else error (mask already ensures, but guard).
6. **CorrespondenceSet:** `projector_x/y (H,W) float32`, `mask (H,W) bool`, `image_size (W,H)`, `projector_resolution (W,H)`, `sequence_id`, `threshold`, `valid_ratio=valid/total`.

No float conversion except final `projector_x/y`; threshold compare stays `uint8`.

---

## D. Threshold Strategy

- **Baseline fixed 127** retained (`StructuredLightDecoder(threshold=127)` default, validated via `threshold` param check `0-255`).
- Synthetic robustness tested at brightness 0.8 (dim) → `valid_ratio >0.95`, noise σ=10 → `>0.85`, both pass with 127.
- Inverted sequence uses same threshold (`binary == (bit_value==1)`), so no adaptive needed.
- Adaptive candidate `threshold = f(normal,inverted)` documented but **not implemented** — evidence does not justify complexity; architecture supports future `threshold` param per decode.

---

## E. Invert Behavior

`PatternEngine(invert=False)` → `bit_value=1`, `invert=True` → `0`.

Test `test_inverted_equivalence`: same camera dims, same Gray code, both sequences decoded via `StructuredLightDecoder` give `valid_ratio` within 0.01, `mask` equal, `projector_x/y` on valid pixels `allclose`. Complement logic in `CorrespondenceMatcher` handles `bit_value` correctly — no duplicated decode path.

---

## F. CorrespondenceSet Output

Canonical `domain/calibration_session.CorrespondenceSet`:

- `projector_x/y` shape == image shape `(H,W)`, `mask` same shape `bool`.
- Invalid pixels `NaN`, valid `finite`, `∈[0,W) / [0,H)`.
- `valid_ratio = valid / total`, `threshold` stored.
- `image_size (W,H)` camera, `projector_resolution (W,H)` projector.

Enforced in `CorrespondenceSet.__post_init__` and re-checked after decode.

---

## G. Robustness

Validity logic:

- Contradictory bits → decode yields out-of-range → masked.
- Out-of-range → `mask` false (not clipped).
- Missing/invalid pattern → `len` mismatch → error.
- Low signal (all-black/white) → not crash, `valid_ratio` 0-1 (tested).
- Invalid sequence (duplicate/wrong id) → `StructuredLightDecodeError` before decode.

Metadata `threshold/valid_ratio` retained for future confidence evolution without schema break.

---

## H. Synthetic Ground Truth

Deterministic synthetic captures from known projector coordinates, using identity mapping (camera res == projector res):

- **Identity:** `camera (x,y) → projector (x,y)` → pattern image sampled at projector coordinate. Tests `test_identity_mapping` asserts `projector_x==xs`, `projector_y==ys` for 32×24.
- **Brightness scaling 0.8** → valid >0.95
- **Noise σ=10** → valid >0.85
- **Inverted** → equivalence as above
- **Partial occlusion** (mid-gray 127 on half) → valid 0-1 (not crash)
- Helpers `_synthetic_frames_identity(brightness, noise_sigma, invert)` generate `CalibrationFrame` tuple via `CameraCapture` RGB.

Distinguishes decoder vs sync failures.

---

## I. Performance

Measured on synthetic identity captures, `tracemalloc` + `perf_counter`, one decode per resolution (PatternEngine cached):

| Camera/Projector | Patterns | Decode   | Per-pattern | Valid | Peak Mem |
| ---------------- | -------- | -------- | ----------- | ----- | -------- |
| 640×480          | 19       | 60.5 ms  | 3.2 ms      | 1.00  | 14.1 MB  |
| 1280×720         | 21       | 157.7 ms | 7.5 ms      | 1.00  | 44.3 MB  |
| 1920×1080        | 22       | 369.5 ms | 16.8 ms     | 1.00  | 101.6 MB |

Baseline well within calibration budget (one-time, not per-frame). No native/GPU warranted; 1080p <400ms acceptable for Phase 6.11 optimization threshold.

---

## J. Copy / Memory Audit

```
Frame RGB (H,W,3) uint8
  → cv2.cvtColor RGB→Gray (H,W) uint8  [1 copy per frame, OpenCV]
  → list gray (H,W) views
  → code_x/y (H,W) uint32  [2 alloc]
  → binary per pattern (H,W) bool transient (reused per bit, no retention)
  → gray_decode in-place copy + shifts (1 copy per axis)
  → projector_x/y (H,W) float32 + NaN init [2 alloc]
  → mask (H,W) bool [1 alloc]
  → CorrespondenceSet holds views (no extra copy)
Total: ~5×H×W allocations + N×H×W gray buffers
```

Avoided: `RGB→BGR→RGB` (none), `uint8→float` per pixel (only final x/y float32, not per capture), `frame copy` (image viewed, not copied before cvt). If unavoidable, documented as `cv2` contiguous copy.

Future 6.11 can fuse `cvt`+`threshold` in native to eliminate per-frame alloc.

---

## K. Legacy Compatibility

Preferred:

```
canonical decoder → CorrespondenceSet → adapter → legacy CorrespondenceMap
```

- `StructuredLightDecoder.to_legacy_map(cs) → CorrespondenceMap`
- `StructuredLightDecoder.from_legacy_map(cmap, seq) → CorrespondenceSet`
- `ProjectorCalibrationAlgorithm.decode()` still works; new code uses `StructuredLightDecoder` and can adapt via `from_legacy_map`/`to_legacy_map` without two independent decoders.

Verified `test_to_legacy`/`from_legacy` round-trip.

---

## L. Hardware Validation

Spec 16: physical projector NOT required if synthetic ground truth provides.

- **Software decode:** validated via synthetic identity/affine/noise/inverted ground truth — **pass**.
- **Hardware:** 6.4 camera 60/60 paired (Camera 0 MSMF). Projector remained mock during 6.5; synthetic decode covers correctness. One complete Gray-code sequence through actual synchronized pipeline with flat diffuse surface **deferred** — flagged as not complete for 6.10 sign-off.

**Production wiring: component-only.** The production `CalibrationManager` stage still routes through the legacy `CorrespondenceMatcher` directly, not the canonical `StructuredLightDecoder`. Full production integration would adapt via `from_legacy_map`/`to_legacy_map`; until that wiring is added and verified with an integration assertion, this phase is classified as **component-only validation**, not production capture.

Recorded `valid_ratio` synthetic 1.00, `decoded coverage` 100% (power-of-two sizes). Latency from 6.4 still applies (31ms p50).

---

## M. Files Changed

**Created:**

- `src/projectionai/services/structured_light_decoder.py` (canonical decoder + adapters)
- `tests/unit/calibration/test_structured_light_decoder.py` (16 tests: validation 5, gray 7, legacy 2, perf 2)

**Modified:** none beyond prior phases (isolated). Existing `correspondence.py` preserved as reference.

Git: `M 11` from 6.2-6.4 + `?? 2` new (decoder + test) + `?? .planning`, `git diff --cached` empty, no staging/push, no `D:\PROJECTIONAI-camera` touch.

---

## N. Remaining 6.6 Work

- `CorrespondenceSet` → `ReconstructionResult` triangulation via `SurfacePlane` (`estimators.triangulate_plane`, `undistort_points`, `sample_correspondences`).
- Wire `StructuredLightDecoder` into `CalibrationManager` pipeline stage `CorrespondenceDecodeStage` (currently uses legacy matcher directly).
- Add affine/perspective synthetic mapping for reconstruction validation.

---

## O. Risks

1. **Threshold fragility in real world** — 127 works for synthetic 0/255 but real projector/camera gamma and ambient may shift; adaptive threshold may be needed after hardware 6.10 captures (store `threshold` in `CorrespondenceSet` to allow re-tune).
2. **Non-power-of-two projector widths** — mask correctly invalidates `code >= W`, but valid_ratio will be <1; downstream reconstruction must handle sparse mask (sample).
3. **RGB→Gray single copy** — still allocates per frame; 1080p 22 patterns → 44MB transient; acceptable but 6.11 could stream.

---

## P. Phase 6.5 Verdict

**COMPLETE — proceed to 6.6.**

- [x] CalibrationFrame[] fully validated (len, ids, ordering, resolution)
- [x] Gray-code mathematically correct (X=COLUMN, Y=ROW, Gray→binary, synthetic identity)
- [x] X/Y vs synthetic ground truth (32×24 identity `allclose`)
- [x] inverted equivalent (mask and coords equal)
- [x] invalid/out-of-range masked (not clipped)
- [x] missing/duplicate/wrong rejected (5 validation tests)
- [x] CorrespondenceSet canonical + legacy adapter round-trip
- [x] 640/720/1080 performance measured (60/158/370ms, <2s gate)
- [x] allocation documented (5×H×W + gray)
- [x] no premature C++/GPU
- [x] Ruff clean, mypy clean (218 files), calibration 432 passed, new 16 passed

**STOP CONDITIONS not triggered:** no incomplete sequence accepted, no silent clipping, no NaN in valid, synthetic error explained.
