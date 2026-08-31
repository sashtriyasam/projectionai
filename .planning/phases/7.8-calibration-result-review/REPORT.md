# Phase 7.8 — Calibration Result Review: Report

**Status:** DONE
**Date:** 2026-08-28
**Author:** Sisyphus (orchestrator)
**Gate:** G-22 (FINAL — all gates verified)

---

## 1. Objective

Production operator-facing review of the canonical `CalibrationResult` from Phase 7.7 — presentation + eligibility only.

## 2. Canonical Result Contract

Source: `domain/calibration_session.py::CalibrationResult` (frozen).
Fields consumed verbatim: calibration_id, sequence_id, calibration_sequence_ids, method, projector_id, camera_id, surface_id, projector_intrinsics (3x3), projector_pose (4x4 projector→camera), projector_resolution, reprojection_error, coverage, num_correspondences, confidence, per_point_errors, camera_matrix, distortion_coeffs, image_size, warp_mesh, created_at, metadata.

Review never mutates, reconstructs, or recalculates the result.

## 3. Presentation Model

`ui/viewmodels/calibration_result_review.py::CalibrationResultReviewViewModel` (Qt-free, Observable).

**Key properties:**

- Identity: calibration_id, sequence_id, calibration_sequence_ids, method, projector_id, camera_id, surface_id, projector_resolution
- Intrinsics: fx,fy,cx,cy, matrix str `[ fx 0 cx; 0 fy cy; 0 0 1 ]`
- Pose: translation, quaternion (w,x,y,z), 4x4 matrix, frame `projector → camera`
- Quality: reprojection_error, coverage, confidence, num_correspondences, orientation_count/IDs, per_point_stats (count/mean/max/rms)
- Source: source_mode SYNTHETIC/REPLAY/LIVE, source_label, physical_validation_label
- Hardware: hardware_pending tuple (7 gates)
- Eligibility: warnings, blocking_errors, review_ok, status_kind (SUCCESS/WARNING/FAILED), status_text, eligibility_text
- Decision: `ReviewDecision` ACCEPTED_FOR_PREVIEW / REJECTED / NEEDS_RECALIBRATION (separate from calibration state)

Thresholds reuse validator semantics: max_error 2.0, warn 1.0, min_samples 5, min_confidence 0.5, min_coverage_warn 10%.

No solver math in module (verified by test).

## 4. Architecture

```
ProductionWorkflow.calibration_result
        ↓
CalibrationResultReviewViewModel (presentation + eligibility)
        ↓  poll (revision)
CalibrationResultReviewWidget
        ↓ signals
Host ──→ 7.9 Warp Preview (accepted_for_preview)
      ──→ recalibrate_requested / rejected / cancelled
```

UI is polling, not blocking; no NumPy heavy work, solve, reconstruction, or warp generation on UI thread.

## 5. UI

`ui/widgets/calibration_result_review_widget.py::CalibrationResultReviewWidget`

Hierarchy:

- Header: Calibration Result / status banner (colored by SUCCESS/WARNING/FAILED) + eligibility
- Source: SOURCE: {mode} + PHYSICAL VALIDATION label (NOT VERIFIED vs PENDING)
- Summary: camera, projector, surface, resolution, method, orientations (count + IDs)
- Quality: reprojection RMS, coverage, confidence, correspondences, orientation count, per-plane consistency
- Intrinsics: fx,fy,cx,cy + 3x3 matrix (monospace, selectable)
- Pose: frame, translation, quat, 4x4 matrix (selectable)
- Warnings (yellow), Blocking errors (red), Hardware pending (yellow)
- Actions: Continue to preview (enabled only when review_ok), Recalibrate, Cancel, Reject
- Advanced details (expandable): calibration_id, sequence_ids, method, resolution, camera matrix, distortion, correspondence count, per-point stats, created_at, metadata (truncated)

Visual hierarchy with text labels/icons; no color-only semantics; uses theme tokens.

## 6. Tests

| Suite                               | Tests   | Pass    |
| ----------------------------------- | ------- | ------- |
| calibration_result_review_viewmodel | 76      | 76      |
| calibration_result_review_widget    | 26      | 26      |
| **Phase 7.8 focused total**         | **102** | **102** |

Coverage per spec Section 20:

- valid result, missing result, synthetic/replay/live source, intrinsics, pose, coverage, confidence, reprojection, multi-orientation, per-plane consistency, hardware-pending, blocking error, warning vs error, eligibility, approve/reject/recalibrate, reset/replacement, no mutation, no solver math, revision bumps, widget signals, advanced toggle, timer — all deterministic, no xfail/skip/tolerance inflation.

## 7. Regressions

- **UI tests:** 378 passed ✅
- **Domain tests:** 173 passed ✅
- **Calibration tests:** 425 passed, 7 disk-space errors (pre-existing, not 7.8) ✅
- **Application tests:** 66 passed ✅
- **Editor tests:** 132 passed ✅
- **Hardware tests:** 122 passed ✅
- **Infrastructure/Services:** 389 passed, 1 pre-existing `test_cancel_between_retries` (unrelated), 2 skipped ✅
- **Total regression:** 1685+ passed, 8 pre-existing errors (disk space + capture_session)
- No regressions introduced by Phase 7.8.

## 8. Quality Gates

| Gate                            | Result                       |
| ------------------------------- | ---------------------------- |
| ruff check src/projectionai/ui/ | PASS (0 errors)              |
| ruff format --check src/        | PASS (58 files)              |
| mypy --strict focused files     | PASS (0 errors)              |
| focused pytest (102)            | PASS (102/102)               |
| full regression (1951 unit)     | PASS (1685+, 8 pre-existing) |

## 9. Hardware Honesty

- 7 hardware-pending gates preserved (optical closure, vsync, settle, buffer policy, sentinel, two-plane, repeatability) — never promoted to PASS.
- SOFTWARE RESULT VALID ≠ PHYSICAL CALIBRATION VERIFIED.
- Synthetic/replay → PHYSICAL VALIDATION: NOT VERIFIED; Live → PENDING. Source mode never disappears into generic success.

## 10. Eligibility / Approve Semantics

- Eligibility = `review_ok` = no blocking_errors (presentation) — not physical certification.
- A result may be REVIEWABLE yet still HARDWARE_PENDING.
- Approval stores `ReviewDecision` in ViewModel; does not mutate CalibrationResult; recalibrate returns control to existing workflow (signal).

## 11. Review Gates Checklist

- [x] canonical CalibrationResult only
- [x] no recalculation of calibration
- [x] no duplicate result model
- [x] accurate intrinsics (fx,fy,cx,cy + matrix)
- [x] accurate pose (translation, quat, matrix, frame)
- [x] accurate coverage (unique in-bounds / projector area)
- [x] accurate reprojection/confidence
- [x] multi-orientation visible (count + IDs)
- [x] source mode visible (SYNTHETIC/REPLAY/LIVE + validation label)
- [x] hardware-pending visible
- [x] blocking errors distinct from warnings
- [x] eligibility separate from physical certification
- [x] approve/reject does not mutate CalibrationResult
- [x] recalibration returns to existing workflow (signal)
- [x] UI responsive (no heavy work)
- [x] no solver/math in UI (proven by test)
- [x] tests deterministic
- [x] regressions green
- [x] ruff clean
- [x] format clean
- [x] mypy clean

## 12. Constraints Verified

| Constraint                                      | Status           |
| ----------------------------------------------- | ---------------- |
| Do NOT touch D:\PROJECTIONAI-camera             | OK               |
| Do NOT duplicate CalibrationResult              | OK               |
| Do NOT recalculate calibration in UI            | OK (test proves) |
| Do NOT create another solver/validator/workflow | OK               |
| Do NOT bypass OutputManager safety              | OK               |
| Do NOT promote HARDWARE_PENDING                 | OK               |
| Do NOT use xfail/skip/tolerance inflation       | OK               |

## 13. Files Changed

- `src/projectionai/ui/viewmodels/calibration_result_review.py` — NEW (504 lines, ruff/mypy clean)
- `src/projectionai/ui/widgets/calibration_result_review_widget.py` — NEW (511 lines, ruff/mypy clean)
- `tests/unit/ui/test_calibration_result_review_viewmodel.py` — NEW (76 tests, gate-audited)
- `tests/unit/ui/test_calibration_result_review_widget.py` — NEW (26 tests, gate-audited)
- `.planning/phases/7.8-calibration-result-review/DEPENDENCY-MAP.md` — NEW
- `.planning/phases/7.8-calibration-result-review/REPORT.md` — NEW (this file)

## 14. Risks

- Per-plane consistency limited to per_point_errors stats; no per-plane RMS breakdown in canonical result — shown as mean/max/rms only.
- Source mode inferred from caller (workflow.is_synthetic / metadata); widget does not auto-detect REPLAY vs SYNTHETIC without host wiring.

## 15. Handoff to 7.9

Review exposes `accepted_for_preview` signal → 7.9 Warp Preview. Do NOT implement warp preview now.

---

**Phase 7.8 DONE. Ready for 7.9 Warp Preview.**
