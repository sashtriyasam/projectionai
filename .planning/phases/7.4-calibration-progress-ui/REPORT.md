# Phase 7.4 — Calibration Progress UI — REPORT

**Status:** DONE
**Date:** 2026-08-28
**Author:** Sisyphus agent

---

## 1. Architecture Audit

### Presentation Model

`CalibrationProgressViewModel` is a thin, Qt-free wrapper over `ProductionWorkflow`:

- Inherits `Observable` (existing project pattern)
- Does NOT duplicate workflow state — reads from `_workflow` on every `refresh()`
- Derives all display text via `_derive_display()` (complete strings, warning/error messages, hardware-pending label)
- Exposes `set_workflow()` to swap the observed workflow on reset
- Emits `changed()` only when `revision` increments (avoids spurious UI updates)

**No direct QT imports.** Pure Python dataclass-like behavior.

### Widget

`CalibrationProgressWidget(QWidget)` consumes the viewmodel:

- Polls via `QTimer` at 200ms interval (configurable)
- Maps workflow stages → widget rows using `_WORKFLOW_TO_WIDGET_STAGE` dict (8 stages, 1:1 with `_WORKFLOW_STAGE_ORDER`)
- Reads `devices_vm.camera_status` / `devices_vm.projector_status` for hardware-pending gates
- Cancel / retry buttons emit Qt signals; workflow actions dispatched via `on_cancel` / `on_retry` callbacks
- Stage labels use `● STATUS` text; progress bars use color-coded stylesheets
- Freeze test: timer interval 200ms < 500ms freeze threshold (verified in test)

### Dependency Chain

```
ProductionWorkflow (7.1, read-only)
    ↓ state/progress/hardware_pending/warnings/errors
CalibrationProgressViewModel (Qt-free, Observable)
    ↓ changed() → revision
CalibrationProgressWidget (QTimer poll, 200ms)
    ↓ on_cancel/on_retry signals
CalibrationWorkflow.cancel()/.retry()
```

---

## 2. Review Gate Findings

### Gate 1: Architecture Review — PASS

- ViewModel is Qt-free, wraps ProductionWorkflow, does not duplicate state
- Widget is presentation-only — no calibration/solver/math logic

### Gate 2: Stage Semantics — FAIL then FIXED

**Finding:** Widget originally had 9 stages including "PRECHECK" mapped to "preflight". But "preflight" is NOT in `ProductionWorkflow._WORKFLOW_STAGE_ORDER` (which has 8 stages: prepare, capture, decode, reconstruct, solve, validate, warp, persist). PRECHECK is a `WorkflowState`, not an execution stage.

**Fix:** Removed invented PRECHECK stage. Widget now has exactly 8 stages matching `_WORKFLOW_STAGE_ORDER`:

- prepare → PREPARING
- capture → CAPTURING
- decode → DECODING
- reconstruct → RECONSTRUCTING
- solve → SOLVING
- validate → VALIDATING
- warp → PREVIEW
- persist → SAVING

### Gates 3-9: PASS

- Integration readiness: widget accepts parent, clean parent/unparent
- Timer lifecycle: QTimer parented to widget, Qt auto-destroys child QObjects
- UI responsiveness: refresh() only reads from viewmodel — no camera, OpenCV, solver
- Progress/ETA: progress clamped [0.0, 1.0], ETA returns None when insufficient data
- Hardware-pending: gates pass through verbatim — never transformed to PASS/VERIFIED
- Failure/cancellation: can_retry only when FAILED, can_cancel checks _CANCELLABLE_STATES
- Viewmodel contract: refresh() bumps revision, widget short-circuits on stale revision

### Gate 10: Tests — 9 review-mandated tests added

| Test                                         | Purpose                                              |
| -------------------------------------------- | ---------------------------------------------------- |
| `test_stage_mapping_matches_workflow_stages` | Verifies widget stages exactly match workflow stages |
| `test_embedded_widget_lifecycle`             | Parent/unparent works cleanly                        |
| `test_timer_stops_on_close`                  | QTimer cleaned up on widget destruction              |
| `test_no_post_destroy_refresh`               | refresh() after destroy doesn't crash                |
| `test_hardware_pending_not_transformed`      | Gates pass through verbatim                          |
| `test_cancellation_display`                  | Cancelled state renders correctly                    |
| `test_failure_identifies_failed_stage`       | Failed stage visible, retry enabled                  |
| `test_workflow_swap_updates_view`            | set_workflow updates display                         |
| `test_revision_only_bumps_on_change`         | Revision tracking works                              |

---

## 3. UI Integration Point

The widget is **standalone** — not yet wired into `CalibrationSessionsPanel` or `MainWindow`. This is intentional:

- Phase 7.4 scope is "build and test the widget" — integration is a separate concern
- The widget is importable and can be placed in any layout via `CalibrationProgressWidget(workflow, devices_vm)`
- A follow-up phase (7.5+) would embed it into the panel

---

## 4. Files Created / Modified

| File                                                         | Action | Lines | Purpose                          |
| ------------------------------------------------------------ | ------ | ----- | -------------------------------- |
| `src/projectionai/ui/viewmodels/calibration_progress.py`     | NEW    | ~130  | Qt-free presentation model       |
| `src/projectionai/ui/widgets/calibration_progress_widget.py` | NEW    | ~390  | Qt widget with 8-stage pipeline  |
| `tests/unit/ui/test_calibration_progress_viewmodel.py`       | NEW    | ~220  | 14 deterministic viewmodel tests |
| `tests/unit/ui/test_calibration_progress_widget.py`          | NEW    | ~310  | 19 widget tests (headless Qt)    |

**No existing files modified.** No `D:\PROJECTIONAI-camera` touched.

---

## 5. Test Coverage

| File                                     | Tests  | Status         |
| ---------------------------------------- | ------ | -------------- |
| `test_calibration_progress_viewmodel.py` | 14     | ALL PASS       |
| `test_calibration_progress_widget.py`    | 19     | ALL PASS       |
| **Total**                                | **33** | **33/33 PASS** |

### Test Categories

| Category               | Count | Notes                                    |
| ---------------------- | ----- | ---------------------------------------- |
| Initial state          | 2     | Idle rendering for viewmodel and widget  |
| Stage transitions      | 2     | RUNNING → COMPLETE rendering             |
| Progress bars          | 1     | Overall progress mapping                 |
| Warnings/errors        | 2     | Display when present                     |
| Hardware pending       | 2     | Gate label rendering + no transform      |
| Cancellation flags     | 3     | Cancel/retry availability                |
| Retry availability     | 1     | retry_available flag                     |
| ETA display            | 2     | Unavailable / available                  |
| Workflow reset         | 2     | Clear display, swap workflow             |
| Timer polling          | 1     | QTimer active and interval               |
| Revision bumping       | 1     | refresh() increments revision            |
| Stage mapping          | 1     | Widget stages match workflow stages      |
| Widget lifecycle       | 2     | Embedded parent/unparent + timer cleanup |
| Post-destroy safety    | 1     | refresh() after destroy doesn't crash    |
| Cancellation display   | 1     | Cancelled state renders correctly        |
| Failure identification | 1     | Failed stage visible, retry enabled      |

---

## 6. Quality Gates

| Gate                  | Result                             |
| --------------------- | ---------------------------------- |
| `ruff check`          | PASS — 0 errors                    |
| `ruff format --check` | PASS — already formatted           |
| `mypy`                | PASS — no issues in 2 source files |
| `pytest`              | PASS — 33/33 tests passing         |

### Pre-existing LSP Warnings (NOT from this phase)

- `setup.py`, `push_to_sheets.py`, `format_sheets.py`: Missing `pybind11`, `google`, `pytest` imports in LSP venv
- PySide6 imports show as unresolvable in LSP (expected — no PySide6 in LSP venv)
- `test_calibration_workflow.py`, `test_output_window_loop.py`: Pre-existing

---

## 7. Risks & Known Limitations

| Risk                                                         | Mitigation                                        | Status   |
| ------------------------------------------------------------ | ------------------------------------------------- | -------- |
| Widget not wired into main window                            | Intentional — integration is 7.5+ scope           | ACCEPTED |
| No integration test with live workflow                       | Deterministic tests use mock `ProductionWorkflow` | ACCEPTED |
| `devices_vm` fixture creates real `DevicesViewModel`         | Works in headless mode (no hardware)              | VERIFIED |
| 200ms poll interval may be too frequent for low-end hardware | Configurable; can be tuned                        | LOW      |

---

## 8. Commit History

| Commit    | Description                                                                            |
| --------- | -------------------------------------------------------------------------------------- |
| (pending) | feat(ui): add CalibrationProgressViewModel and CalibrationProgressWidget with 33 tests |

---

## 9. Next Steps (Phase 7.5+)

1. Embed `CalibrationProgressWidget` into `CalibrationSessionsPanel`
2. Wire `on_cancel` / `on_retry` to `CalibrationWorkflow.cancel()` / `.retry()`
3. Add hardware detection callbacks for camera/projector status
4. Integration test with live `ProductionWorkflow` (mock hardware)
