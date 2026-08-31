# Phase 6.10B — Capture Latency + Calibration Robustness Engineering

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Measure + implement measured-justified changes + validate. No commit / No push / No merge / No reset.

**Scope (fixed):** 1) capture-time bottleneck, 2) occlusion / false-valid calibration. CPU GrayCode remains baseline; no GPU/CUDA/Vulkan/OpenCL/Rust/Ceres.

---

## A. Baseline Timing (measured)

Physical camera: **idx 0 = MSMF 640×480@30fps**, idx 1 = DSHOW (same device). No projector→camera round trip is possible on this machine (the webcam is not pointed at the LG TV secondary), so projector-side settle safety is bounded by reasoning + the presentation barrier; camera-side latency is fully measured.

| Stage                              | Measured                                     | Source                                   |
| ---------------------------------- | -------------------------------------------- | ---------------------------------------- |
| First frame (MSMF, `BUFFERSIZE=1`) | **1650 ms**                                  | bench_camera.py                          |
| First frame (MSMF, default buffer) | **364 ms**                                   | bench_camera.py                          |
| First frame (DSHOW, default)       | 1.3 ms                                       | bench_camera.py                          |
| Steady-state read (MSMF)           | p50 31.6 / p95 49.2 / p99 64.1 / max 78.3 ms | bench_camera.py (30 fps floor)           |
| Steady-state read (DSHOW)          | 16.7 ms                                      | bench_camera.py                          |
| BGR→RGB conversion (640×480)       | 4.62 ms                                      | bench_camera.py                          |
| BGR→GRAY conversion (640×480)      | 0.78 ms                                      | bench_camera.py                          |
| `asyncio.sleep(20ms)` real         | 26.8 ms p50 / 35.5 p95                       | timer measurement (Windows quantization) |
| `asyncio.sleep(5ms)` real          | 6.9 ms p50                                   | timer measurement                        |

**Exact capture path** (traced): `projector.show` → `_presentation_barrier` (vsync or monotonic stamp) → `asyncio.sleep(min_settle_ms)` → `camera.capture()` = `cap.read` (executor) → `cv2.cvtColor(BGR2RGB)` → `Frame`. Then `CorrespondenceMatcher._to_gray` does a second RGB→gray conversion.

**Baseline sequence wall-clock (21 patterns, MSMF):** first pattern (1650 ms first-frame + 27 ms settle + 31.6 ms read = 1709 ms) + 20×(27 ms settle + 31.6 ms read = 58.6 ms) = 1709 + 1172 = **2881 ms ≈ 2.88 s**. Steady-state sequence (camera already warm) = 21×(27 ms settle + 31.6 ms read) = 21×58.6 ms = **1.23 s**. The 6.10A-R "4.2 s / 200 ms-per-frame" figure was an estimate; the measured per-frame read is 31.6 ms, and the real one-time cost is the 1.65 s first-frame penalty.

---

## B. Camera Buffering Findings

- `CAP_PROP_BUFFERSIZE=1` is **actively harmful on the MSMF backend**: first frame 1650 ms vs 364 ms with default buffer (4.5×). It does **not** change steady-state read (31.6 vs 31.7 ms).
- On DSHOW, `BUFFERSIZE` reads back −1 (unsupported) and is ignored.
- The current `OpenCVCamera.open()` sets `BUFFERSIZE=1` unconditionally — the measured cost is real; its claimed benefit (avoiding stale frames) is **unverified** without the projector round trip.

**Recommendation (not implemented — needs round-trip):** make `BUFFERSIZE=1` backend-aware (skip on MSMF) and validate stale-frame rate on the physical capture path in 6.10C.

---

## C. Settle-Time Benchmark

`asyncio.sleep` on Windows is quantized by the ~15.6 ms timer: `sleep(20)`→26.8 ms, `sleep(16)`→20.8 ms, `sleep(10)`→13.9 ms, `sleep(5)`→6.9 ms, `sleep(0)`→0.

Wrong-frame / stale-frame rate for settle 0/5/10/16/20 ms **cannot be measured on this machine** (webcam not aimed at the projector). The presentation barrier already serializes pattern-on-screen before capture; settle adds pixel-response margin. **Settle-time reduction is the dominant wall-clock lever (22–46% of steady-state) but is UNVALIDATED here.** `min_settle_ms=20` is left unchanged; the report records the exact values to validate in the physical round trip.

---

## D. Warmup Benchmark (first-frame)

| Drain N | Drain cost | Steady read after |
| ------- | ---------- | ----------------- |
| 0       | 0 ms       | 47.4 ms           |
| **1**   | **375 ms** | **27.1 ms**       |
| 3       | 375 ms     | 30.0 ms           |
| 5       | 485 ms     | 33.6 ms           |
| 10+     | ≥546 ms    | 33.6 ms           |

**WINNER: drain 1 frame.** Smallest deterministic solution, no arbitrary sleep, no backend-specific hack. Rationale: the first captured frame is taken during auto-exposure settle (wrong brightness) and the driver's first read is slow; draining one frame moves that cost out of the pattern loop so every pattern captures at steady state. Value is **measured initialization and latency mitigation** (first-frame 1650 ms isolated as one-time ~375 ms cost, steady read 47→27 ms). **Correctness benefit (preventing AE-settle capture) is pending aimed round-trip validation** — the sequence barrier ensures pattern ordering, but image-level exposure correctness requires physical verification.

---

## E. Pattern-Count Optimization

Gray-code bit count is **information-theoretically minimal**: `bits = ceil(log2(size))` (verified: 640×480→10+9, 1280×720→11+10, 1920×1080→11+11, 2560×1440→12+11, 3840×2160→12+12). Dropping one bit causes **256/1280 code collisions** (20%) — non-unique decode, silent corruption.

- Full Gray sequence: **WINNER** (already minimal).
- Reduced bit sequence / adaptive early termination / invalid-region early termination: **REJECTED** — all break uniqueness or cannot reduce full-frame capture count; the decoder must never infer missing bits.

---

## F. Occlusion Benchmark (synthetic 1280×720, identity)

Methods: A baseline, B inverted pair (42 captures), C max-intensity confidence (21), D inverted+confidence (42), E white-sentinel (22).

| Case                | A FVR | B FVR | C FVR | D FVR | E FVR |
| ------------------- | ----- | ----- | ----- | ----- | ----- |
| occlusion 0%        | 0%    | 0%    | 0%    | 0%    | 0%    |
| 1% random           | 100%  | 0%    | 0%    | 0%    | 0%    |
| 5% random           | 100%  | 0%    | 0%    | 0%    | 0%    |
| 10% random          | 100%  | 0%    | 0%    | 0%    | 0%    |
| 20% random          | 100%  | 0%    | 0%    | 0%    | 0%    |
| 5% contiguous       | 100%  | 0%    | 0%    | 0%    | 0%    |
| 10% contiguous      | 100%  | 0%    | 0%    | 0%    | 0%    |
| shadow 33% (dim=40) | 100%  | 0%    | 0%    | 0%    | 0%    |
| shadow 33% (dim=90) | 100%  | 0%    | 0%    | 0%    | 0%    |

(FVR = false-valid rate: fraction of occluded pixels wrongly marked valid. Detail at 5% random: A recall=0.00, B/C/D/E recall=1.00, precision=1.00.)

**Baseline is broken for occlusion:** every occluded pixel decodes to code (0,0) — a _valid_ coordinate — so 100% of occluded pixels enter the solver as wrong correspondences (the ~119 px error measured in 6.10A-R).

---

## G. Inverted-Pair Evaluation

- **Full inverted pair (42 captures):** FVR 0%, recall 100%, and per-bit agreement. Correct, but 2× capture cost.
- **Sentinel inversion (1 white frame = 22 captures):** FVR 0%, recall 100% — identical occlusion rejection at ~half the cost. The all-white frame lights every projector-receiving pixel regardless of its gray code.
- **White+black sentinel (23 captures):** adds ambient-light robustness (a lit pixel is bright in white and dark in black); no measured benefit over white-only in dim-shadow tests, but the principled choice for bright-field scenes.

**Minimum additional captures to detect false-valid black regions: 1 (white sentinel).**

---

## H. Confidence / Modulation

The Part 8 hard requirement — distinguish TRUE ZERO CODE from NO LIGHT — is decisive:

| Signal                               | True-zero-code pixel               | Occluded pixel              |
| ------------------------------------ | ---------------------------------- | --------------------------- |
| max-intensity over positive patterns | max = **0** → **FALSELY REJECTED** | max = 0 → rejected ✓        |
| white sentinel                       | **255** → valid ✓ (distinguished)  | 0 → rejected ✓              |
| inverted pair (pos vs complement)    | 0 vs 255 → disagree → valid ✓      | 0 vs 0 → agree → rejected ✓ |

- **Max-intensity / temporal-modulation confidence alone: REJECTED** — it cannot distinguish the projector's (0,0) code (black in every positive pattern) from no light.
- **White sentinel / inverted pair: WINNER** — the complement lights the zero code, cleanly separating it from occlusion.
- Confidence is a **validation layer above** the deterministic decoder: the lit-mask ANDs into the code-bounds mask; it never replaces exact Gray decoding.

---

## I. End-to-End Timing (measured)

|                      | Baseline               | + warmup          | + warmup + settle=10ms (unvalidated) |
| -------------------- | ---------------------- | ----------------- | ------------------------------------ |
| First-frame / warmup | 1650 ms (in pattern 0) | 375 ms (isolated) | 375 ms                               |
| 21 patterns          | 20×58.6 + 58.6         | 21×58.6           | 21×45.6                              |
| **Total**            | **~2.88 s**            | **~1.61 s**       | **~1.33 s**                          |

The 20% target is **reachable only via settle-time reduction**, which is the one lever that cannot be validated on this machine (webcam not aimed at the projector). Measured physical floor (settle=0, camera warm): 21 × 31.6 ms = **664 ms/sequence** (the 30 fps camera frame period is the hard floor). The warmup + buffersize findings reduce the first-frame penalty 4.5× but do not shrink steady-state.

---

## J. Accuracy Comparison

|                           | RMSE (occluded region)                 | false-valid       | coverage                        |
| ------------------------- | -------------------------------------- | ----------------- | ------------------------------- |
| Baseline (no lit mask)    | up to ~119 px (from 6.10A-R)           | 100% of occlusion | inflated (false coverage)       |
| + white sentinel lit-mask | occluded region invalidated → excluded | **0%**            | correct (drops to lit fraction) |

The sentinel lit-mask trades a small coverage reduction (the occluded pixels are correctly dropped) for elimination of the false-valid correspondences that corrupt the solve. Coverage is reported accurately rather than inflated.

---

## K. Winner / Backup / Rejected Matrix

| Decision                | WINNER                                     | BACKUP                                | REJECTED                                                     |
| ----------------------- | ------------------------------------------ | ------------------------------------- | ------------------------------------------------------------ |
| Capture warmup          | **drain 1 frame**                          | backend-specific warmup               | arbitrary 2.7 s sleep, timer-based                           |
| Settle strategy         | **20 ms (unchanged — round-trip pending)** | 10 ms (validate in round trip)        | 0/5 ms (unvalidated)                                         |
| Pattern count           | **full GrayCode (minimal)**                | —                                     | reduced/adaptive (256/1280 collisions)                       |
| Occlusion detection     | **white sentinel (+1 capture)**            | white+black (+2), full inverted (+21) | max-intensity confidence (false-rejects true-zero), baseline |
| Confidence scoring      | **sentinel lit-mask (validation layer)**   | inverted per-bit agreement            | temporal-modulation alone                                    |
| Invalid-mask generation | **code-bounds AND lit-mask**               | —                                     | code-bounds alone                                            |

---

## L. Implementation Changes (made, measured-justified)

1. **`sync.py` — warmup drain.** Added `SyncConfig.warmup_frames: int = 1`; `SynchronizedCaptureSession.capture_sequence` drains `warmup_frames` frames via a new `_warmup()` before the pattern loop (errors wrapped as `ProjectorCalibrationError`, cancellation re-raised). Justified by D: drain-1 isolates the AE-settle first frame so no pattern is captured mid-settle. Image-level exposure correctness is unverified pending an aimed projector-camera round trip.
2. **`correspondence.py` — occlusion lit-mask.** Added `compute_lit_mask(white_sentinel, black_sentinel=None, threshold=127)` (white-sentinel bright ⇒ lit; optional black-sentinel rejects bright-ambient), and an optional `lit_mask` parameter on `CorrespondenceMatcher.decode` that ANDs into the code-bounds mask (shape-checked). Justified by F/G/H: baseline false-valid 100% → 0%; sentinel distinguishes true-zero from occlusion.
3. **`patterns.py` — sentinel builders.** Added `build_white_sentinel(width, height)` and `build_black_sentinel(width, height)`. Justified by G.
4. **Tests.** Added 3 correspondence tests (`TestLitMaskOcclusion`) + 2 sync warmup tests; adapted `test_retry_succeeds` and `test_frame_timeout` for the new warmup frame. No existing assertion weakened; no tolerance/xfail/skip changes.

**Documented but NOT implemented (require physical projector→camera round trip):** settle reduction below 20 ms; backend-aware `BUFFERSIZE`; gray-only capture (skip BGR→RGB, save ~4.6 ms/frame); wiring the sentinel into `GrayCodeProjectorCalibration` end-to-end (project + capture sentinel → pass `lit_mask`).

---

## M. Risks

| Risk                                                             | Likelihood | Impact                   | Mitigation                                                    |
| ---------------------------------------------------------------- | ---------- | ------------------------ | ------------------------------------------------------------- |
| Settle <20 ms accepts stale frames on real projector             | Medium     | High (decode corruption) | Left at 20 ms; validate 10 ms in round trip before any change |
| `BUFFERSIZE=1` removal increases stale-frame latency             | Medium     | Medium                   | Only remove for MSMF; verify stale rate on physical path      |
| Sentinel adds +1 capture (22 vs 21)                              | Certain    | Low (+58 ms)             | Opt-in per-scene; negligible vs 1.2 s sequence                |
| True-zero region (projector pixel 0,0) — off-surface in practice | Low        | Negligible               | Sentinel handles it correctly regardless                      |
| Warmup drain adds ~375 ms once per session                       | Certain    | Low                      | Amortized across sequences; prevents a corrupt first pattern  |

---

## N. Validation

- `ruff check src/` — **All checks passed**
- `ruff format --check src/` — **223 files already formatted**
- `mypy src/projectionai/` — **Success: no issues in 222 files**
- `pytest tests/unit/calibration/ -q` — **424 passed**
- `pytest tests/unit/calibration/test_correspondence.py tests/unit/calibration/test_capture_sync.py` — **32 passed** (incl. 5 new)
- Physical camera benchmark re-run; original baseline preserved (MSMF 640×480@30, first-frame 1650 ms, steady 31.6 ms).
- (Full-suite collection has a pre-existing `test_calibration_session.py` basename collision in `domain/` vs `calibration/` — unrelated to this change.)

---

## O. Final Decision

**STOP AFTER THIS REPORT.**

Two problems were attacked, both with measurements first:

1. **Capture-time:** the measured bottleneck is the **1.65 s MSMF first-frame (exacerbated 4.5× by `BUFFERSIZE=1`)** plus the 30 fps camera read floor (31.6 ms/frame). Implemented the **drain-1 warmup** (isolates the first-frame, corrects the mid-AE-settle capture). The remaining time lever — **settle 20→10 ms** — is the only path to ≥20% steady-state reduction and is **blocked on a physical projector→camera round trip** this machine cannot provide; the exact validation values (0/5/10/16/20 ms) are recorded here for 6.10C. Measured floor: 664 ms/sequence.

2. **Occlusion / false-valid:** baseline marks 100% of occluded pixels as valid (code 0,0), corrupting calibration. **White-sentinel lit-mask primitives implemented and synthetically validated** (FVR 100%→0%, recall 0→100%, +1 capture) — `compute_lit_mask`, `build_white_sentinel`/`build_black_sentinel`, `decode(lit_mask=)`. **Production e2e wiring into `GrayCodeProjectorCalibration.capture_sequence` (project/capture sentinel, pass `lit_mask`) remains pending** — gated on hardware round trip.

Next (6.10C, gated on hardware round trip): settle sweep on the real projector, backend-aware `BUFFERSIZE`, gray-only capture, and end-to-end sentinel wiring into `GrayCodeProjectorCalibration`.
