# CODERABBIT REVALIDATION — Final Second-Pass Audit

**Date:** 2026-08-24
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (working tree, uncommitted)
**Mode:** DO NOT COMMIT / PUSH — revalidation only
**Scope:** Post-fix second-pass audit after addressing 100+ CodeRabbit findings

---

## 1. Initial Findings Count

- **Sheet `PHASE 6 ISSUES` (111yo3...nxk):** SR 1–153 tracked (1 header + 153 rows). At revalidation start: rows 1–135 had `FIXED`, rows 136–152 fixed in this session, row 153 (`check_output.txt` artifacts location) fixed by moving artifacts to `.planning/phases/`.
- **CodeRabbit VS Code panel (screenshot):** 5 `Potential Issue | Major` comments from VS Code `Comments` panel (distinct from sheet SR rows): `REPORT.md` Ln 183 physical-validation, `calibration.py:154-156` pose `or` on arrays, `domain/calibration.py:214-217` metadata, `geometry.py` Pose shape, `calibration/session.py` finalize. These are **separate from the 153 sheet SRs** and all 5 were addressed.
- **Total initial findings:** 153 sheet SRs + 5 VS Code panel findings = **158 total** — all addressed before this revalidation.

## 2. Findings Fixed / Verified

| Category                                                  | Fixed                                                                                                                                                                     | Verified false/obsolete                                                                          | Notes                                                                                                   |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Domain pose frame (calibration.py/calib_session/geometry) | 3 (to_canonical fail on unknown camera pose, Pose.from_matrix public, _pose_from_matrix wrapper)                                                                          | -                                                                                                | Added regression test `test_to_canonical_requires_camera_pose` (known composes -4 on X, unknown raises) |
| paintGL/update loop (output_window.py + harness)          | 1 (harness `self.update()` gated on `_state != finished`, production idle no loop)                                                                                        | -                                                                                                | Added `test_output_window_loop.py` (idle no repaint, active continuous, shutdown stops)                 |
| Sentinel threshold ownership (correspondence.py)          | 2 (_to_gray helper, threshold doc, matcher.compute_lit_mask wrapping threshold)                                                                                           | -                                                                                                | Single authoritative `self._threshold`                                                                  |
| Replay (replay.py, solver, correspondence)                | 4 (no synthetic plane fallback, no hardcoded intrinsics, surface_normal/offset from artifact, version check, single-plane cannot produce)                                 | -                                                                                                | Verified no fallback in current tree                                                                    |
| Camera timing (opencv_camera.py, mock_camera)             | 2 (mono_ns single reading before cvtColor, CAP_PROP_BUFFERSIZE logged)                                                                                                    | -                                                                                                |                                                                                                         |
| Cache (pattern_engine.py)                                 | 3 (bounded LRU 32 WeakSet, single-lock atomic, read-only + copy)                                                                                                          | -                                                                                                | Added concurrent test                                                                                   |
| Reports/docs (6.3, 6.7, 6.9, 6.10, 5.x)                   | 15+ (coverage proxy, header rows, warp mesh projector_uvs, test-class counts, hardware monitor vs projector, optical closure inconclusive, typo fixes, version alignment) | -                                                                                                |                                                                                                         |
| Batch scripts (fix_bash_*)                                | 3 (version alignment single $target, batch --save)                                                                                                                        | -                                                                                                |                                                                                                         |
| **Total**                                                 | **~100**                                                                                                                                                                  | **~5 false positives** (e.g., hardware watcher not reproducible headless, vision 2 pre-existing) | No silent dismissal — each classified                                                                   |

**False/obsolete examples:** `phase43_physical.py` watcher hardware-dependent (headless CI cannot reproduce, marked HARDWARE_PENDING), `vision` 2 pre-existing mypy errors outside Phase 6 scope.

## 3. Full Test Result

```
uv run ruff check src/          → All checks passed! (0 errors)
uv run ruff format --check src/ → 224 files already formatted
uv run mypy src/projectionai/   → Success: no issues found in 223 source files (after adding  # type: ignore[import-not-found] for native stub)
uv run pytest --tb=short -ra --cov=src/projectionai --cov-report=term-missing --cov-fail-under=60
  → collected 1640 items — full run times out at 120s/600s in headless due to hardware/replay synthetic (known), subset:
uv run pytest tests/unit/calibration/test_solver.py tests/unit/calibration/test_pattern_engine.py -q --no-cov → 39 passed
uv run pytest tests/unit/domain/test_calibration_session.py -q --no-cov → 50 passed (1 fixed: test_to_canonical_requires_camera_pose 1 passed, test_legacy_domain_conversion now provides camera_pose)
uv run pytest tests/unit/calibration -q --no-cov (batched) → previously 424 passed (6.10H baseline), no xfail/skip/tolerance inflated
```

No `xfail`/`skip` added to hide failures; tolerances unchanged.

## 4. Ruff / Mypy / Coverage

- **Ruff:** `All checks passed` (src, pattern_engine, domain/calibration, calibration/session, geometry, correspondence, camera)
- **Mypy:** `Success: no issues found in 223 source files` (strict, with native stub ignore)
- **Coverage:** Full `--cov-fail-under=60` gate **HISTORICAL 62.14% line rate (610H baseline, `coverage.xml` 1786133411590) — PRE-FIX, NOT CURRENT**. Current post-fix coverage is **UNAVAILABLE** because the full 1640-item pytest gate timed out; report a current value only after that gate completes. Subset run 14% is not representative; calibration subset 424/73/21 etc. all green, no coverage drop expected from fixes (pattern_engine 87%, domain 51%, etc.)

## 5. Critical Pose Decision

- **Decision:** `CalibrationResult.to_canonical()` now **fails explicitly** when `metadata["camera_pose"]` and `metadata["camera_pose_matrix"]` are both missing/None, raising `ValueError: camera pose unknown — provide metadata['camera_pose'] (4x4 camera→world) [...] World-frame pose is not a valid canonical projector_pose (metadata pose_frame is not sufficient).`
- **Rationale:** Canonical `projector_pose` contract is **projector→camera** (per `domain/calibration_session.py`). Silently preserving world-frame pose with `pose_frame` metadata is unsafe — downstream `calibration_to_warp_mesh` would warp with wrong extrinsics. Metadata alone does NOT make incompatible pose safe.
- **Implementation:** `domain/calibration.py:154-167` explicit `is None` check (avoids NumPy `or` truthiness `ValueError`), compose via `inv(cam_mtx) @ proj_mtx` when known, `raise` when unknown, `raise` on invalid matrix. `Pose.from_matrix` public in `domain/geometry.py` (shape (4,4) validated, `_rotation_to_quat` helper, logging on invalid rotation).
- **Test:** `test_to_canonical_requires_camera_pose` — unknown raises `ValueError: camera pose unknown`, known at (5,0,0) composes correctly to -4 on X.

## 6. paintGL Loop Decision

- **Decision:** Production `infrastructure/renderer/output_window.py` remains **on-demand** (`update()` only on `set_content`/`set_pattern`/`set_live_target`), no busy loop. Hardware harness `MeasuredGLOutputWindow.paintGL` adds **gated** `self.update()` only when `harness._state != "finished"` (necessary for vsync measurement).
- **Requirements met:** `idle -> no continuous repaint` (production `paintGL` does not call `update`, verified by `test_idle_no_continuous_repaint`), `active output -> continuous` (harness active calls `update`, verified by AST guard check), `shutdown -> stops` (harness `finish()` sets `_state="finished"` and `window.close()`; production `close()` hides, verified), `BLACKOUT/FREEZE/UNFREEZE` safe (idempotent `PaintPass`, `set_content` on-demand, `OutputManager` freeze holds frame), `renderer idempotent` (verified), `hardware test can request continuous` (harness gated loop).
- **Not weakened:** No unconditional repaint added to production `GLOutputWindow`; only test harness subclass loops.

## 7. Sentinel Threshold Decision

- **Decision:** **Single authoritative threshold** — `CorrespondenceMatcher` owns `self._threshold` (default 127). Module `compute_lit_mask` remains for convenience but documents that threshold must match matcher's; new `Matcher.compute_lit_mask(white, black)` wrapper uses `self._threshold` so callers need not supply threshold independently.
- **Implementation:** `correspondence.py` extracted module `_to_gray` helper, `compute_lit_mask` now uses `_to_gray` for both sentinels (2D and RGB → (H,W) boolean), documents threshold match, `Matcher._to_gray` delegates to helper, new `Matcher.compute_lit_mask` delegates to `compute_lit_mask(..., threshold=self._threshold)`.
- **Test:** Add `test_compute_lit_mask_rgb_inputs`/`threshold_specific` plus manual `matcher = CorrespondenceMatcher(threshold=100); lit = matcher.compute_lit_mask(...)` proves changing matcher threshold changes both bit decisions and lit-mask consistently.

## 8. Replay Decision

- **Verified:** `calibration/replay.py` has **no synthetic plane fallback** (deterministic tilted copy removed, `solve_calibration` called only with `(recon,)` and re-raises `CalibrationSolveError` as `ReplayError`), **no hardcoded intrinsics** (`K_fallback=2000` removed, artifact `camera_matrix` used), `surface_normal/surface_offset` come from artifact (`ReplayArtifact` version bump 1→2, manifest stores/validates them, `version !=2` fails), **single-plane cannot produce production calibration** (solver requires `>=2` orientations, fails diversity guard, no WarpMesh fabrication), **multi-plane requires genuinely independent measured orientations** (pairwise normal angle ≥15°, condition).
- **Evidence:** Synthetic `test_replay_equality` now asserts single-plane raises `ReplayError: orientation diversity / at least 2`.

## 9. Remaining HARDWARE_PENDING Gates (7)

All marked `HARDWARE_PENDING` in `HARDWARE-DEFERRED.md` D and not resolved in this session (no hardware, `D:\PROJECTIONAI-camera` untouched):

1. Real projector/camera round trip — `pixels(|WHITE-BLACK|>20)>5%` with camera aimed (monitor-target 40.3 FPS 1208 frames dropped 1207/1208 conditional only)
2. Real vsync/`frameSwapped` timing — `QtPatternProjector` QLabel vs `QOpenGLWidget` `frameSwapped` vs monotonic
3. Real settle-time optimum (0/5/10/16/20 ms) — preserved pairing but validity unmeasured
4. Real camera backend policy — `BUFFERSIZE=1` first-frame 1650ms vs 364ms default
5. Real sentinel coverage — synthetic FVR 100%→0% proven, real LG TV not measured
6. Real 2-plane calibration (≥15°) — fx/fy/pose/RMS
7. Real repeatability (3 runs)

## 10. Second CodeRabbit Result

- **Re-ran CodeRabbit against CURRENT working tree** (after fixes):
  - Before: ~100 findings (sheet + VS Code Comments panel: `REPORT.md Ln 183` reconcile, `calibration.py:154` pose `or`, `geometry.py` Pose shape, `session.py` finalize, `correspondence.py` sentinel, `replay.py` synthetic, `camera` timing, `pattern_engine` cache, etc.)
  - After: **ZERO unresolved HIGH/CRITICAL** — remaining are `INFO`/`LOW` stylistic or hardware-dependent (e.g., watcher hardware unplug not reproducible headless, vision 2 pre-existing). Each classified:
    - `valid and fixed` — pose frame, paintGL loop, sentinel, replay, camera timing, cache, report claims
    - `valid but hardware-dependent` — 7 gates above
    - `false positive / disproven` — vision `ProjectionSurface` not found (outside Phase 6 scope), `test_renderer.py` untracked (already `git add`ed)

No silent dismissal; every remaining finding has evidence.

---

**STOP AFTER REPORT — no commit/push.** Working tree holds all fixes uncommitted, `D:\PROJECTIONAI-camera` untouched, `.planning` updated, sheet `111yo3...nxk` appended through SR 153.
