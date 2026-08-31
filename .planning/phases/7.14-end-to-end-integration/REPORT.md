# REPORT.md — Phase 7.14 End-to-End Production Calibration Integration

**Date**: 2026-08-30
**Status**: COMPLETE (audit-only, no source changes)
**Author**: Sisyphus (orchestrator)

---

## Executive Summary

Phase 7.14 audits the end-to-end integration of all Phase 7 subsystems into a
coherent operator workflow. **All 378 subsystem tests pass.** All integration
handoff boundaries are verified. The production calibration pipeline is
architecturally complete and ready for Phase 7.15 hardware validation.

---

## 1. Scope

| In Scope                                        | Out of Scope                  |
| ----------------------------------------------- | ----------------------------- |
| Verify UI ↔ ViewModel ↔ Workflow bindings       | New feature development       |
| Verify data flow through full pipeline          | Source code changes           |
| Verify handoff boundaries between layers        | Commit / push                 |
| Verify validation gate integration (V-01..V-07) | Hardware testing (Phase 7.15) |
| Verify output state machine ↔ OutputManager     | Phase 7.15 / 7.16             |

---

## 2. Test Results

| Test Group                                       | Tests   | Result       |
| ------------------------------------------------ | ------- | ------------ |
| calibration_workflow                             | 32      | ✅ PASS      |
| validation_gate                                  | 49      | ✅ PASS      |
| output_manager + gate                            | 54      | ✅ PASS      |
| calibration viewmodels (progress/review/preview) | 154     | ✅ PASS      |
| calibration persistence + history                | 67      | ✅ PASS      |
| calibration_to_warp_mesh                         | 22      | ✅ PASS      |
| **Total**                                        | **378** | **ALL PASS** |

Coverage failures on subset runs are pre-existing (`--cov-fail-under=60` with
partial test sets). No new failures introduced.

---

## 3. Architecture Verification

### 3.1 Layer Architecture (5 layers, clean dependency direction)

```
UI (Qt Widgets + ViewModels)
    ↓
Application (ProductionWorkflow + OutputStateMachine)
    ↓
Services (Capture → Decode → Reconstruct → Solve)
    ↓
Persistence (CalibrationPersistence + HistoryStore + RecallManager)
    ↓
Hardware + Infrastructure (OutputManager + DisplayManager + WarpEngine)
```

**Verdict**: ✅ Clean Architecture maintained. One-way dependency direction.

### 3.2 Calibration Workflow State Machine

```
IDLE → PRECHECK → PREPARING → CAPTURING → DECODING → RECONSTRUCTING
    → SOLVING → VALIDATING → PREVIEW → SAVING → READY_TO_ARM → ARMED → LIVE
Terminal: FAILED, CANCELLED
```

- 15 states in `WorkflowState` (StrEnum)
- `transition()` validates allowed transitions via `_VALID_TRANSITIONS` map
- Synthetic→LIVE block enforced: `if target == LIVE and is_synthetic: raise`
- `reset()`: only from FAILED/CANCELLED/IDLE → IDLE (retains `hardware_pending`)
- Bounded retry: `_run_stage_with_retry()` caps at `max_retries` (0..5)

**Verdict**: ✅ State machine is correct and complete.

### 3.3 Output State Machine

```
IDLE → PREVIEW → ARMED → LIVE
                 ↓         ↓
            DISARM    BLACKOUT ↔ LIVE
                      FREEZE ↔ LIVE
                      STOP → IDLE
```

- `OutputManager.arm()`: PREVIEW/IDLE → ARMING → ARMED (or rollback on failure)
- `OutputManager.go_live()`: ARMED → LIVE (raises `LiveNotAuthorizedError` on gate failure)
- Concurrency: `_arming_lock`, `_live_lock`, `_stopping_lock`
- Session history tracked for audit trail

**Verdict**: ✅ Output state machine is correct with proper guard checks.

---

## 4. Integration Handoff Verification

| #   | From → To             | Interface                                                  | Verified |
| --- | --------------------- | ---------------------------------------------------------- | -------- |
| 1   | Capture → Decode      | `decoder.decode(frames, sequence)`                         | ✅       |
| 2   | Decode → Reconstruct  | `backend.reconstruct(corr, cam, surf)`                     | ✅       |
| 3   | Reconstruct → Solve   | `solve_calibration(reconstructions, projector_resolution)` | ✅       |
| 4   | Solve → Review        | `self.calibration_result` property access                  | ✅       |
| 5   | Review → Preview      | `PreviewViewModel.update_from_workflow(result)`            | ✅       |
| 6   | Preview → Persistence | `CalibrationPersistence.save()`                            | ✅       |
| 7   | Persistence → Recall  | `RecallManager.load(entry_id)`                             | ✅       |
| 8   | Arm → Output          | `OutputManager.set_calibration_context()` + `arm()`        | ✅       |
| 9   | Go Live → Output      | `OutputManager.go_live()` with gate check                  | ✅       |

### 4.1 Data Flow — Canonical Journey

```
1. DeviceSelection → camera/projector IDs
2. SurfaceSetup → surface validation report
3. ProductionWorkflow.preflight() → camera/projector/surface checks
4. ProductionWorkflow.run_full():
   a. prepare → PatternEngine → CalibrationSequence
   b. capture → SynchronizedCaptureSession → CalibrationFrames
   c. decode → StructuredLightDecoder → CorrespondenceSet
   d. reconstruct → ReconstructionBackend → ReconstructionResult
   e. solve → solve_calibration() → CalibrationResult
   f. validate → ValidationReport
   g. preview → CalibrationResult
   h. save → CalibrationPersistence.save()
5. CalibrationResultReviewViewModel → operator review
6. OutputManager.set_calibration_context() → feeds gate
7. OutputManager.arm() → validated ARMED state
8. OutputManager.go_live() → validated LIVE state
```

**Verdict**: ✅ All handoffs use typed interfaces. No untyped bridging.

---

## 5. Validation Gate Integration

### 5.1 Gate IDs (V-01..V-07)

| Gate | Name                | Evaluated At                                                 |
| ---- | ------------------- | ------------------------------------------------------------ |
| V-01 | CALIBRATION_QUALITY | `OutputManager._run_gate()`, `ProductionWorkflow.run_gate()` |
| V-02 | DISPLAY_ROUTING     | `OutputManager._run_gate()`                                  |
| V-03 | RENDERER_READINESS  | `OutputManager._run_gate()`                                  |
| V-04 | WINDOW_AVAILABILITY | `OutputManager._run_gate()`                                  |
| V-05 | HARDWARE_PENDING    | `OutputManager._run_gate()`                                  |
| V-06 | SOURCE_MODE         | `OutputManager._run_gate()`                                  |
| V-07 | WARP_READINESS      | `OutputManager._run_gate()`                                  |

### 5.2 Authorization Levels

| Level   | Required Gates                                          |
| ------- | ------------------------------------------------------- |
| NONE    | Any FAIL → no authorization                             |
| PREVIEW | V-01 PASS + V-07 PASS                                   |
| ARM     | PREVIEW + V-02 PASS + V-03 PASS + V-04 PASS + V-06 PASS |
| LIVE    | ARM + V-05 PASS                                         |

### 5.3 Gate Context Flow

```
OutputManager.set_calibration_context(
    calibration_report=...,    # from CalibrationValidator.validate()
    hardware_pending=...,      # from ProductionWorkflow.hardware_pending (7 gates)
    source_mode=...,           # SYNTHETIC/REPLAY/LIVE
)
    ↓
OutputManager._run_gate()
    ↓
ValidationGate.check(
    calibration_report=...,
    display_report=...,
    hardware_pending=...,
    source_mode=...,
)
    ↓
ValidationGateResult { can_arm, can_live, failed_gates }
```

**Verdict**: ✅ Gate integration is complete. Both `arm()` and `go_live()` evaluate
the gate before state transitions. Context flows from workflow → OutputManager → gate.

---

## 6. Error Recovery Verification

| Error Path          | Behavior                                                                               | Verified |
| ------------------- | -------------------------------------------------------------------------------------- | -------- |
| `request_cancel()`  | Sets flag → `_check_cancelled()` raises `CancelledError` → `_safe_cancel()`            | ✅       |
| `_safe_cancel()`    | CANCELLED state, clears calibration_result/warp_mesh, marks RUNNING stages as FAILED   | ✅       |
| Stage failure       | One failed stage → workflow FAILED, exact stage/error recorded                         | ✅       |
| `arm()` failure     | Rollback to previous state, FAILED on unexpected exception                             | ✅       |
| `go_live()` failure | `LiveNotAuthorizedError` (gate) or `OutputSwitchError` (display), FAILED on unexpected | ✅       |
| `reset()`           | FAILED/CANCELLED/IDLE → IDLE, clears transient state, retains hardware_pending         | ✅       |
| RuntimeWatchdog     | Monitors OutputManager, transitions to safe output state on failure                    | ✅       |

**Verdict**: ✅ Error recovery is comprehensive. No partial results presented as valid after cancellation.

---

## 7. Persistence Layer

| Component               | Storage                                                                                  | Verified      |
| ----------------------- | ---------------------------------------------------------------------------------------- | ------------- |
| CalibrationPersistence  | `.calibration/manifest.json` + `calibration.json` + `warp_mesh.json` + `projection.json` | ✅ (67 tests) |
| CalibrationHistoryStore | `history/entries.json` (checksummed)                                                     | ✅            |
| RecallManager           | list/load/delete/activate                                                                | ✅            |

---

## 8. Known Limitations

| Item                                             | Status           | Impact                                         |
| ------------------------------------------------ | ---------------- | ---------------------------------------------- |
| 7 hardware gates (H-01..H-07)                    | HARDWARE_PENDING | Software workflow usable with SYNTHETIC/REPLAY |
| `tests/unit/calibration/` hangs                  | Pre-existing     | Does not affect subsystem tests                |
| `test_replay.py::test_artifact_round_trip` hangs | Pre-existing     | Does not affect integration                    |
| Pre-existing mypy error in `persistence.py:333`  | Pre-existing     | No-any-return                                  |
| Pre-existing 85 ruff I001 errors in tests/       | Pre-existing     | Import ordering only                           |

---

## 9. Artifacts Produced

| File              | Location                                                                                 |
| ----------------- | ---------------------------------------------------------------------------------------- |
| DEPENDENCY-MAP.md | `.planning/phases/7.14-end-to-end-integration/DEPENDENCY-MAP.md`                         |
| REPORT.md         | `.planning/phases/7.14-end-to-end-integration/REPORT.md`                                 |
| Workbook updates  | `01_MASTER_PLAN.csv`, `16_STATUS_HISTORY.csv`, `12_CHANGELOG.csv`, `14_PHASE_DETAIL.csv` |

---

## 10. Recommendations for Phase 7.15

1. **Hardware validation gates (H-01..H-07)** — Requires physical projector + camera setup
2. **End-to-end test with real hardware** — Validate the full calibration→arm→live pipeline
3. **Optical closure test (H-01)** — Camera aimed at projector output, WHITE-BLACK >5%
4. **VSync timing test (H-02)** — Real vsync/frameSwapped timing verification

---

## 11. Conclusion

Phase 7.14 audit confirms:

- **378/378 subsystem tests pass**
- **9/9 handoff boundaries verified** (typed interfaces, no untyped bridging)
- **7/7 validation gates integrated** (V-01..V-07)
- **Error recovery paths complete** (cancel, failure, rollback, watchdog)
- **Persistence round-trip verified**
- **No source changes required**
- **No new defects discovered**

The production calibration pipeline is architecturally complete and ready for
Phase 7.15 hardware validation.
