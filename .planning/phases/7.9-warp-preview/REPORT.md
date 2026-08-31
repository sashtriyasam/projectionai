# Phase 7.9 — Warp Preview: Report

**Status:** DONE
**Date:** 2026-08-28
**Author:** Sisyphus (orchestrator)

---

## 1. Objective

Production warp preview — consumes accepted `CalibrationResult` from Phase 7.8, routes through canonical `WarpMesh → ProjectionMapping → ProjectionPass → preview display`. Self-contained state machine with safety boundaries (no OutputManager coupling).

## 2. Deliverables

### 2.1 Dependency Audit

**File:** `.planning/phases/7.9-warp-preview/DEPENDENCY-MAP.md`

Audited canonical path: `CalibrationResult → calibration_to_warp_mesh() → WarpMesh → create_projection_mapping() → ProjectionMapping → ProjectionPass`. Identified `calibration_to_warp_mesh()` signature requiring `surface_width_m`/`surface_height_m`. Verified `OutputManager` safety machine boundaries.

### 2.2 PreviewViewModel

**File:** `src/projectionai/ui/viewmodels/preview.py`

Qt-free observable ViewModel with:

- **State machine:** `PreviewState` (StrEnum) — IDLE → LOADING → READY → RUNNING ⇄ FROZEN, RUNNING/FROZEN/READY ⇄ BLACKOUT, ERROR → IDLE, terminal: CLOSED. 8 states, 14 valid transitions.
- **Content types:** `PreviewContent` (StrEnum) — IDENTITY, CHECKERBOARD, GRID, CROSSHAIR, BORDER, CORNER_MARKERS, COLOR_BARS, GRADIENT. 8 types.
- **MeshDiagnostics:** Vertex/face counts, grid dimensions, NaN/Inf checks, UV range validation, generation method. `.is_valid` / `.summary()`.
- **PreviewViewModel:** Observable (revision counter + subscribe/unsubscribe). Actions: `update_from_workflow(calibration_result, surface_width_m=, surface_height_m=)`, `start()`, `stop()`, `freeze()`, `unfreeze()`, `blackout()`, `unblackout()`, `reset()`, `set_content()`, `cycle_content()`, `close()`.
- **Safety:** No OutputManager import, no `go_live()` / `arm()` calls. Verified by test.

### 2.3 PreviewWidget

**File:** `src/projectionai/ui/widgets/preview_widget.py`

PySide6 QWidget with:

- Status banner (state label, color-coded)
- Mesh diagnostics panel (vertices, faces, grid, UV range, method, validity)
- Content selector (current type + Cycle button)
- Error display (conditional)
- Action buttons (Start, Stop, Freeze, Blackout, Reset, Close) — enabled/disabled per state
- Signals: `preview_started`, `preview_stopped`, `preview_closed`
- QTimer-based polling via `revision` counter (200ms interval)

## 3. Test Results

**79 tests passing (0 failures, 0 errors)**

### test_preview_viewmodel.py — 59 tests

| Test Class              | Count | Coverage                                                            |
| ----------------------- | ----- | ------------------------------------------------------------------- |
| TestPreviewState        | 4     | Initial state, revision, content, label                             |
| TestStateTransitions    | 11    | All valid + invalid transitions, terminal state                     |
| TestTransitionCallbacks | 4     | Subscribe, unsubscribe, multiple handlers, close idempotent         |
| TestStart               | 3     | Ready→Running, Idle fail, Running fail                              |
| TestStop                | 4     | Running/Frozen/Blackout→Ready, Idle fail                            |
| TestFreeze              | 2     | Running→Frozen, Ready fail                                          |
| TestUnfreeze            | 2     | Frozen→Running, Running fail                                        |
| TestBlackout            | 4     | Running/Frozen/Ready→Blackout, Idle fail                            |
| TestUnblackout          | 2     | Blackout→Running, Running fail                                      |
| TestReset               | 2     | Error→Idle, Idle fail                                               |
| TestContent             | 3     | Set, cycle, wrap-around                                             |
| TestIsActive            | 5     | Idle/Ready/Running/Frozen/Blackout                                  |
| TestIsDisplayable       | 2     | Idle=false, no-mesh=false                                           |
| TestMeshDiagnostics     | 5     | Valid, NaN invalid, empty, summary OK, summary INVALID              |
| TestUpdateFromWorkflow  | 4     | None→Error, mesh failure→Error, ignored when not idle, reset clears |
| TestSafetyBoundaries    | 2     | No OutputManager import, label/color types                          |

### test_preview_widget.py — 20 tests

| Test Class        | Count | Coverage                                                                 |
| ----------------- | ----- | ------------------------------------------------------------------------ |
| TestConstruction  | 4     | Creates, initial state label, content label, error hidden                |
| TestButtonStates  | 5     | Idle/Ready/Running/Frozen/Error button enable/disable                    |
| TestButtonActions | 7     | Start/Stop/Freeze/Blackout/Reset/Close/Cycle signals + state             |
| TestRefresh       | 4     | Diag labels populated, error displayed, no-diag when None, revision skip |

## 4. Safety Boundaries

- **OutputManager not imported** — verified by test (`test_no_output_manager_import`)
- **No `go_live()` / `arm()` calls** — source inspection confirms zero references
- **State machine is self-contained** — preview does NOT drive hardware output
- **Hardware gates from Phase 7.8 preserved** — preview consumes, not creates

## 5. Files Changed

| File                                                  | Action                  |
| ----------------------------------------------------- | ----------------------- |
| `src/projectionai/ui/viewmodels/preview.py`           | Created                 |
| `src/projectionai/ui/widgets/preview_widget.py`       | Created                 |
| `tests/unit/ui/test_preview_viewmodel.py`             | Created                 |
| `tests/unit/ui/test_preview_widget.py`                | Created                 |
| `.planning/phases/7.9-warp-preview/DEPENDENCY-MAP.md` | Created                 |
| `.planning/phases/7.9-warp-preview/REPORT.md`         | This file               |
| `01_MASTER_PLAN` row 44                               | IN_PROGRESS → DONE      |
| `16_STATUS_HISTORY`                                   | Appended completion row |
| `12_CHANGELOG`                                        | Appended CH-079         |

## 6. Constraints Verified

| Constraint                                               | Status                          |
| -------------------------------------------------------- | ------------------------------- |
| Preview MUST NOT call OutputManager.go_live()            | PASS                            |
| Preview MUST NOT call OutputManager.arm()                | PASS                            |
| Do NOT create another CalibrationResult / WarpMesh model | PASS                            |
| Do NOT recalculate calibration in preview                | PASS                            |
| Do NOT rerun decoder/reconstruction/solver               | PASS                            |
| Do NOT silently enter LIVE                               | PASS                            |
| Do NOT bypass DisplayValidator / OutputManager           | PASS                            |
| Reuse existing WarpMesh, ProjectionMapping               | PASS                            |
| Reuse Phase 7.2 selected display                         | PASS (pending 7.10 integration) |
| Qt-free ViewModel                                        | PASS                            |

## 7. Ready for STOP-AT-REVIEW

All code written, all tests green, Google Sheet updated to DONE. Phase 7.9 is complete and ready for review. Phase 7.10 NOT started.
