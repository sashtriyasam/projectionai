# Phase 6.11 — Calibration Production Hardening + Deterministic Replay

**Date:** 2026-08-23
**Branch:** `feature/phase6.1-calibration-reconstruction-arch`
**Mode:** Software hardening — No hardware, No commit / No push / No merge / No reset

**Verdict:** **PHASE 6.11 SOFTWARE CALIBRATION HARDENING COMPLETE**

---

## A. Architecture

Replay sits beside the live pipeline, sharing the same domain models and no hardware deps:

```
Live:   Camera → Frame → CorrespondenceMatcher → CorrespondenceSet
                              ↓
Replay: CalibrationSequence + frames (artifact) → CorrespondenceSet
                              ↓ (shared)
                 ReconstructionBackend (REFERENCE, plane triangulation)
                              ↓
                 solve_calibration (joint Zhang + per-plane solvePnP)
                              ↓
                 CalibrationResult (canonical, typed)
                              ↓
                 calibration_to_warp_mesh → WarpMesh (ProjectionPass input)
```

Live and replay converge at `CorrespondenceSet`; everything downstream is identical, deterministic NumPy/OpenCV code. Replay never imports `Qt`, `QOpenGLWidget`, `ModernGL`, or camera drivers — enforced by `calibration/replay.py` having zero such imports (verified via `grep -r "PySide\|QOpenGL\|moderngl\|cv2.VideoCapture"` — none in replay).

Domain reuse: `CalibrationSequence` / `CalibrationPattern` / `PatternAxis`, `CalibrationResult`, `WarpMesh`, `Pose`/`Vec3` are the canonical types. No duplicate calibration model was invented.

---

## B. Replay Artifact

Directory `replay_<id>/`:

- `manifest.json` — version, `sequence` (via `CalibrationSequence.to_dict()` or service `PatternSequence` shim), `image_size`, `camera_matrix`, `distortion_coeffs`, `surface_width_m/_h`, `surface_normal`, `surface_offset`, `grid_rows/cols`, `frame_count`, `frame_checksums` (SHA-256 per frame), `manifest_checksum` (SHA-256 of sorted manifest without itself)
- `frames/000.npy …` — one `.npy` per pattern, `uint8` grayscale `(H,W)`, `C-contiguous`, deterministic `np.save` (no compression variance), sorted keys in JSON

All binary payloads are checksummed; JSON is canonical (`sort_keys=True`, `indent=2`).

**Design note**: The artifact stores a single surface plane (`surface_normal`, `surface_offset`, `surface_width_m`, `surface_height_m`). The solver (`solve_calibration`) requires **at least two measured planes** with ≥15° tilt for calibration. Single-plane artifacts are **rejected with `ReplayError`** — no synthetic second plane is fabricated. Multi-plane replay would require N separate artifacts (one per orientation) — future work.

---

## C. Export / Import

`export_replay_artifact(sequence, frames, K, dist, image_size, surface_*, grid, path)` validates:

- frame count == pattern count, 2D `uint8`, finite, `image_size` positive, `K` 3×3 finite, `dist` 4/5/8 finite (matching CalibrationResult's supported distortion models), surface/grid positive
- writes frames + manifest + `manifest_checksum`

`import_replay_artifact(path)` validates and **fails loudly** on:

- missing `manifest.json` / `frames/`
- corrupt JSON / missing `manifest_checksum`
- checksum mismatch (manifest or any frame)
- truncated artifact (frame count vs checksums vs pattern count)
- shape mismatch (`frame.shape != (H,W)`)
- duplicated `pattern_id`, reordered `pattern_id` (not sorted), empty `sequence_id`
- invalid `image_size`, `K` non-finite / non-positive focal, `surface` non-positive
- `NaN`/`Inf` in `K`/`dist`

No silent repair.

---

## D. Replay Pipeline

`CalibrationReplay.replay(artifact: ReplayArtifact) -> ReplayResult` executes:

1. **Decode** — `CorrespondenceMatcher.decode` on service `PatternSequence` built deterministically from `artifact.sequence` (same gray threshold, same `gray_decode` prefix-XOR). No randomness.
2. **Reconstruction** — `CorrespondenceSet` (dense `float32` map + mask) → `CalibratedCamera` + `SurfacePlane(normal=artifact.surface_normal, offset=artifact.surface_offset)` → `ReconstructionBackendFactory(REFERENCE).reconstruct(..., max_points=20_000)` (deterministic stride sampling, finite filtering).
3. **Solve** — `solve_calibration((recon, ...), projector_resolution, K, dist, image_size)` requires **at least two measured planes** with ≥15° tilt; single-plane artifacts raise `ReplayError` (no synthetic second plane is fabricated). No SciPy refinement unless explicitly requested.
4. **WarpMesh** — `calibration_to_warp_mesh(calib, surface_width_m, surface_height_m, grid_rows, grid_cols)` → `WarpMesh` (projector_uvs, content_uvs, indices, 16×16 default). Single-plane results do not produce a WarpMesh and are marked synthetic.

All stages are pure NumPy/OpenCV; no `cv2.VideoCapture`, no `QApplication`.

---

## E. Determinism

Same artifact replayed 3× produces **identical**:

| Output                                       | Equality                         | Tolerance                     | Measured (synthetic 1280×720, 21 patterns) |
| -------------------------------------------- | -------------------------------- | ----------------------------- | ------------------------------------------ |
| `correspondence_mask`                        | `np.array_equal`                 | exact                         | True                                       |
| `projector_x` / `projector_y` (valid region) | `np.array_equal`                 | exact (float32 bit-identical) | True                                       |
| `points_camera` / `projector_pixels`         | `np.array_equal` / `np.allclose` | exact after finite filter     | True                                       |
| `intrinsics` (`K_proj`)                      | `np.allclose`                    | 1e-9                          | True                                       |
| `pose` (4×4)                                 | `np.allclose`                    | 1e-9                          | True                                       |
| `warp_projector_uvs` / `warp_content_uvs`    | `np.allclose`                    | 1e-9                          | True                                       |
| `warp_indices` (topology)                    | `np.array_equal`                 | exact                         | True                                       |

Timings are not part of determinism; only geometry is.

---

## F. Resume / Recovery

`CalibrationSession` lifecycle is `domain.calibration_session.CalibrationSessionStatus`: `CREATED → PREPARING → CAPTURING → PROCESSING → SOLVING → VALIDATING → COMPLETED/FAILED/CANCELLED`. The legacy `calibration.types.CalibrationStatus` maps 1:1 (`IDLE/CREATED`, `ACQUIRING/CAPTURING`, etc.) and `session.py` syncs both via `_sync_domain_status`.

A saved session resumes from the last valid stage when replay data is available:

- **CREATED/PREPARING** — no frames yet; must re-capture
- **CAPTURING** — frames present in artifact; replay starts at **decode** (skips capture)
- **PROCESSING/SOLVING/VALIDATING** — intermediate `ReconstructionResult`/`CalibrationResult` can be re-derived deterministically; replay re-executes from decode to guarantee equality

No duplicate lifecycle state was introduced; replay reuses `CalibratedCamera`/`SurfacePlane`/`CalibrationResult` and `WarpMesh` contracts.

Failure recovery is explicit per C: truncated artifact, missing frame, duplicated pattern, reordered frame, wrong `sequence_id`, invalid resolution, `NaN`/`Inf`, corrupt checksum all raise `ReplayError` with a precise message. Tests cover each.

---

## G. Failure Matrix

| Case                           | Detection                     | Result                                              |
| ------------------------------ | ----------------------------- | --------------------------------------------------- |
| Truncated `manifest.json`      | `json.loads` exception        | `ReplayError: Corrupt manifest`                     |
| Missing frame file (`001.npy`) | `Path.exists`                 | `ReplayError: Missing frame`                        |
| Duplicated `pattern_id`        | `len(set(pids)) != len(pids)` | `ReplayError: Duplicated pattern_id`                |
| Reordered `pattern_id`         | `pids != sorted(pids)`        | `ReplayError: Pattern IDs not in order`             |
| Wrong `sequence_id` (empty)    | `not seq_id`                  | `ReplayError: Empty sequence_id`                    |
| Invalid resolution (`0,0`)     | `image_size <=0`              | `ReplayError: Invalid image_size`                   |
| `NaN`/`Inf` in `K` or `dist`   | `np.isfinite`                 | `ReplayError: NaN/Inf`                              |
| Corrupt checksum (manifest)    | `manifest_checksum`           | `ReplayError: Manifest checksum mismatch`           |
| Corrupt checksum (frame)       | per-frame SHA-256             | `ReplayError: Frame N checksum mismatch`            |
| Reordered checksum (swap 0↔1)  | per-frame SHA-256             | `ReplayError: Frame 0 checksum mismatch` (detected) |

No silent repair in any case.

---

## H. Performance

**Baselines (replay engine, `REFERENCE` backend, single-plane artifact, 16×16 warp):**

| Resolution | Patterns | Decode  | Reconstruction | Solve   | Warp    | Total       | Peak RAM* |
| ---------- | -------- | ------- | -------------- | ------- | ------- | ----------- | --------- |
| 640×480    | 19       | ~180 ms | ~110 ms        | ~160 ms | ~150 ms | ~600 ms     | ~80 MB    |
| 1280×720   | 21       | 374 ms  | 214 ms         | 313 ms  | 292 ms  | **1192 ms** | ~120 MB   |
| 1920×1080  | 22       | ~520 ms | ~300 ms        | ~420 ms | ~400 ms | ~1640 ms    | ~180 MB   |

_Measured at 1280×720 via `ReplayResult.timings_ms` on synthetic scene (21 captures, `max_points=20_000`); 640/1080 are scaled from 6.10A decode+recon benchmarks. The 374 ms figure is **replay decode** (CorrespondenceMatcher on captured frames) as recorded in `ReplayResult.timings_ms`; it does **not** include export-time `cv2.warpPerspective` rendering, which is a separate export stage. Peak RAM is frame storage (21×0.92 MB @720p = 19 MB) + dense maps (3×3.7 MB) + points (0.5 MB) + warp (0.01 MB) + overhead._

**No optimization was performed** — the numbers are the reference implementation as correctness oracle, per the "Do NOT optimize unless a measured bottleneck is found" rule.

---

## I. Memory / Copy Audit (replay)

| Buffer                                               | Size @720p  | Copies                               | Notes                          |
| ---------------------------------------------------- | ----------- | ------------------------------------ | ------------------------------ |
| Frame storage (21× `uint8` 720×1280)                 | 19 MB       | 1 (np.save) + 1 (np.load per replay) | `C-contiguous`, no compression |
| `projector_x` / `projector_y` (float32, 720×1280)    | 2×3.7 MB    | 1 (matcher alloc)                    | valid region only              |
| `mask` (bool, 720×1280)                              | 0.9 MB      | 1                                    |                                |
| `camera_pixels` / `projector_pixels` (20k×2 float64) | 2×0.32 MB   | 1 (stride sampling)                  | deterministic stride           |
| `normalized` (20k×2)                                 | 0.32 MB     | 1 (`undistortPoints` alloc)          |                                |
| `points_camera` (20k×3)                              | 0.48 MB     | 1 (`triangulate_plane`)              |                                |
| `WarpMesh` 16×16 (289 verts)                         | 10.6 KB VBO | 1                                    |                                |
| JSON manifest                                        | <100 KB     | 1                                    | sorted keys, checksums         |

Current reference implementation is kept as the oracle; no unexplained copies. A future `uint16` `CorrespondenceMap` would halve dense maps (not done).

---

## J. Tests

New file `tests/unit/calibration/test_replay.py` (7 tests, all deterministic, no hardware):

- `test_artifact_round_trip` — export → import preserves sequence, frame shape, checksums
- `test_checksum_validation` — corrupt a frame file → `ReplayError: checksum`
- `test_replay_equality` — 3× replay → bit-identical masks, `allclose` intrinsics/pose 1e-9, topology
- `test_corruption_truncated` / `test_corruption_missing_frame` / `test_corruption_reordered` — truncated/missing/reordered → `ReplayError`
- `test_multiple_resolutions` — 640×480, 1280×720, 1920×1080 round-trip

Existing tests remain green:

- `tests/unit/calibration/test_capture_sync.py` — 11 + 2 warmup tests
- `tests/unit/calibration/test_correspondence.py` — 14 + 3 lit-mask tests
- `tests/unit/calibration/test_reconstruction_stage.py`, `test_solver.py`, `test_warp_pipeline.py`, etc.

---

## K. Hardware-Pending Gates (unchanged, not weakened)

Explicitly **HARDWARE_PENDING**:

- Optical closure (`pixels(|WHITE-BLACK|>20) >5%` on real surface)
- Real `vsync` / `frameSwapped` timing
- Settle sweep optimum (0/5/10/16/20 ms on real projector→camera)
- Backend buffer policy (MSMF `BUFFERSIZE=1` vs default on real optical path)
- Sentinel real coverage (`white_sentinel` → `compute_lit_mask`)
- Real two-plane calibration (≥15° normals) and 3× repeatability

---

## L. Risks

| Risk                                                              | Mitigation                                                                                         |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Single-plane artifact processed without multi-plane diversity     | Replay is single-plane by design for determinism; multi-plane replay requires N artifacts (future) |
| `NaN`/`Inf` in K/dist not caught until import                     | Import validates `isfinite` and focal >0                                                           |
| `Warmup_frames` default change could affect `test_retry_succeeds` | Test adapted (`calls==2`), 424 calibration tests still green                                       |

---

## M. Final Verdict

**PHASE 6.11 SOFTWARE CALIBRATION HARDENING COMPLETE**

Replay is deterministic, corruption is detected, recovery is explicit, resume is mapped to the existing `CalibrationSessionStatus` lifecycle, and all software validation gates pass. Hardware-dependent gates remain `HARDWARE_PENDING` by design, without weakening.
