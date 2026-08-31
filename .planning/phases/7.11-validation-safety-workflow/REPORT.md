# Phase 7.11 — REPORT: Validation & Safety Workflow

## Status: DONE

## Goal

Unified validation gate answering "Is the system authorized to arm/go-live?" — a single orchestrator that evaluates calibration quality, display readiness, hardware pending gates, source mode, and warp readiness to produce explicit authorization levels (NONE / PREVIEW / ARM / LIVE).

## Deliverables

### New Modules

| Module                                            | Lines | Purpose                                                                                                                          |
| ------------------------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------- |
| `src/projectionai/calibration/validation_gate.py` | 497   | `ValidationGate`, `GateId`, `GateStatus`, `GateResult`, `ValidationGateResult`, `AuthorizationLevel` — unified gate orchestrator |

### Modified Files

| File                                                              | Change                                                                                                                                                        |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/projectionai/calibration/__init__.py`                        | Added exports for gate classes                                                                                                                                |
| `src/projectionai/hardware/output_manager.py`                     | Added `validation_gate` param, `run_gate()`, `set_calibration_context()`, `gate_result`, `can_arm`, `can_live` properties; gate-gated `arm()` and `go_live()` |
| `src/projectionai/application/calibration_workflow.py`            | Added `run_gate()` method                                                                                                                                     |
| `src/projectionai/ui/viewmodels/calibration_result_review.py`     | Gate-aware `eligibility_text`, `gate_failure_summary`, `is_gate_stale`, `gate_age_seconds`; gate failures wired into `warnings`/`blocking_errors`             |
| `src/projectionai/ui/widgets/calibration_result_review_widget.py` | Added `_gate_failures_label` and `_stale_gate_label` in constructor; populated in `refresh()`                                                                 |

### New Tests

| File                                              | Tests | Status   |
| ------------------------------------------------- | ----- | -------- |
| `tests/unit/calibration/test_validation_gate.py`  | 47    | ALL PASS |
| `tests/unit/hardware/test_output_manager_gate.py` | 14    | ALL PASS |

**Total new tests: 61**

### Bug Fix (during testing)

| File                                                  | Issue                                               | Fix                                    |
| ----------------------------------------------------- | --------------------------------------------------- | -------------------------------------- |
| `src/projectionai/calibration/validation_gate.py:293` | `issue.passed` attribute error on `ValidationIssue` | Changed to `issue.severity == "error"` |

---

## Gate Model Architecture

### Gate Taxonomy (V-01 through V-07)

| Gate ID | Name                | Source               | Status when OK | Status when BLOCKED |
| ------- | ------------------- | -------------------- | -------------- | ------------------- |
| V-01    | Calibration Quality | CalibrationValidator | PASS           | FAIL                |
| V-02    | Display Routing     | DisplayValidator     | PASS           | FAIL                |
| V-03    | Renderer Readiness  | DisplayValidator     | PASS           | FAIL                |
| V-04    | Window Availability | DisplayValidator     | PASS           | FAIL                |
| V-05    | Hardware Pending    | ProductionWorkflow   | PASS / PENDING | PENDING             |
| V-06    | Source Mode         | ValidationGate       | PASS / PENDING | PENDING             |
| V-07    | Warp Readiness      | WarpPipeline         | PASS           | FAIL                |

### Authorization Levels

| Level   | Meaning             | Requirements                                                                      |
| ------- | ------------------- | --------------------------------------------------------------------------------- |
| NONE    | No authorization    | Any gate FAIL                                                                     |
| PREVIEW | Software preview OK | V-01 PASS + V-07 PASS + no FAILs; PENDING allowed; source SYNTHETIC/REPLAY        |
| ARM     | Physical arm OK     | PREVIEW + V-02 PASS + V-03 PASS + V-04 PASS + V-05 PASS + V-06 PASS (source LIVE) |
| LIVE    | Full go-live        | ARM (all gates PASS, no hardware pending)                                         |

### Key Design Decisions

1. **HARDWARE_PENDING ≠ PASS**: V-05 status is PENDING when hardware gates exist, PASS when tuple is empty. Never collapses into a single boolean.
2. **can_preview ≠ can_arm ≠ can_live**: Three explicit authorization decisions. Synthetic source → caps at PREVIEW. Hardware pending → caps at PREVIEW.
3. **Source mode preserved**: SYNTHETIC/REPLAY/LIVE — software validation ≠ physical readiness proof.
4. **Gate is optional**: OutputManager works with or without a gate (legacy behavior preserved).
5. **Stale gate detection**: 300s (5 min) threshold; UI displays age warning.

---

## Gate Audit (29 gates)

### GATE 1 — Architecture / Duplication

**Verdict: PASS**

Single `validation_gate.py` module (497 lines). No competing gate implementations. Existing `DisplayValidator` remains authoritative for display checks — gate reads its output.

### GATE 2 — Canonical Source of Truth

**Verdict: PASS**

No second models created. `ValidationGate` composes existing validators (`CalibrationValidator`, `DisplayValidator`). Gate taxonomy uses V-01..V-07 for software authorization gates; physical hardware gates use H-01..H-07 (see 10_VALIDATION_GATES).

### GATE 3 — Gate Completeness (all 7 gates)

**Verdict: PASS**

All 7 gates evaluated in `check()`: calibration, display routing, renderer, window, hardware pending, source mode, warp readiness.

### GATE 4 — HARDWARE_PENDING ≠ PASS

**Verdict: PASS** (3 sub-tests)

| Sub-test | Description                 | Result |
| -------- | --------------------------- | ------ |
| 4a       | PENDING is not PASS         | PASS   |
| 4b       | PENDING does not enable ARM | PASS   |
| 4c       | Only empty tuple allows ARM | PASS   |

### GATE 5 — Source Mode Caps

**Verdict: PASS**

SYNTHETIC and REPLAY both cap at PREVIEW. Only LIVE source allows ARM/LIVE authorization.

### GATE 6 — OutputManager Gate Integration

**Verdict: PASS**

- `run_gate()` evaluates gate with current context
- `arm()` checks `gate_ok` before transitioning
- `go_live()` raises `OutputSwitchError` when gate blocks
- Legacy behavior (no gate) preserved: `can_arm`/`can_live` default to True

### GATE 7 — ReviewViewModel Gate Wiring

**Verdict: PASS**

- `eligibility_text` updated to be gate-aware
- `gate_failure_summary` property surfaces failed gate details
- `is_gate_stale` / `gate_age_seconds` detect stale evaluations
- Gate failures wired into `warnings` and `blocking_errors`

### GATE 8 — Widget Gate Display

**Verdict: PASS**

- `_gate_failures_label` added to widget constructor (between errors and hardware pending)
- `_stale_gate_label` added for stale gate warning
- `refresh()` populates both labels from ViewModel properties

### GATE 9 — Authorization Semantics

**Verdict: PASS**

Three explicit authorization decisions preserved: `can_preview`, `can_arm`, `can_live`. No boolean collapse.

### GATE 10 — Cal Report Issue Handling

**Verdict: PASS** (fixed during testing)

Bug: `issue.passed` → `issue.severity == "error"` in `_check_calibration()`. Verified: calibration report with failed issues → V-01 FAIL with detail.

### GATE 11 — Gate Timestamp

**Verdict: PASS**

`evaluated_at` set to `time.time()` on each `check()` call. `is_gate_stale` returns True when age > 300s.

### GATE 12 — Gate Result Tuples

**Verdict: PASS**

`failed_gates`, `passed_gates`, `pending_gates` tuples properly computed from gate results.

### GATE 13 — Gate Summary

**Verdict: PASS**

`summary` property returns human-readable authorization summary with failure/pending counts.

### GATE 14 — Gate Lookup

**Verdict: PASS**

`gate(gate_id)` returns specific `GateResult` or None. `gate_passed()`, `gate_failed()` helpers work correctly.

### GATE 15 — Test Coverage (gate model)

**Verdict: PASS**

47 tests covering: enums, GateResult properties, ValidationGateResult predicates, check() orchestrator, hardware pending invariant, source mode caps, warp readiness, timestamp, tuples.

### GATE 16 — Test Coverage (OutputManager integration)

**Verdict: PASS**

14 tests covering: init without gate, calibration context, source mode normalization, gate result property, arm with gate, arm blocked (no calibration, hardware pending, synthetic source), go_live blocked, legacy arm/go_live.

### GATE 17 — Regression

**Verdict: PASS**

1329 tests passed, 1 skipped (pre-existing `test_replay.py` hang), 0 failed.

### GATE 18 — Code Quality

**Verdict: PASS**

No type suppressions (`as any`, `@ts-ignore`). No bare excepts. `from __future__ import annotations` active.

### GATE 19 — Constraint Compliance

**Verdict: PASS**

| Constraint                        | Status |
| --------------------------------- | ------ |
| No second CalibrationResult model | PASS   |
| No second WarpMesh model          | PASS   |
| No second replay format           | PASS   |
| STOP AT REVIEW (no 7.12)          | PASS   |
| HARDWARE_PENDING ≠ PASS           | PASS   |
| Gate wiring ≠ gate passing        | PASS   |

### GATE 20 — No Concurrency Framework

**Verdict: PASS**

No large concurrency framework introduced. Gate evaluation is synchronous.

### GATE 21 — Existing Validators Preserved

**Verdict: PASS**

`DisplayValidator`, `CalibrationValidator` remain authoritative for their domains. Gate reads their output, does not replace them.

### GATE 22 — No Second Output State Machine

**Verdict: PASS**

No parallel output safety state machine introduced. Gate adds authorization check on top of existing `OutputState` transitions.

### GATE 23 — Synthetic ≠ Physical Proof

**Verdict: PASS**

SYNTHETIC source mode explicitly caps at PREVIEW. Software validation ≠ physical readiness proof.

### GATE 24 — Live Source Requires Physical Evidence

**Verdict: PASS**

LIVE source requires empty hardware pending tuple AND calibration pass AND display validation pass.

### GATE 25 — Gate Does Not Override Display Validation

**Verdict: PASS**

Gate runs AFTER display validation. Display errors cause FAIL regardless of gate. Gate cannot promote past display validation failures.

### GATE 26 — Test Quality

**Verdict: PASS**

61 new tests. No `xfail`, no arbitrary skip, no tolerance inflation. All tests verify actual behavior.

### GATE 27 — Documentation

**Verdict: PASS**

DEPENDENCY-MAP.md created documenting 10-file audit. Gate taxonomy, authorization levels, and design decisions documented.

### GATE 28 — Phase Boundary

**Verdict: PASS**

Phase 7.11 answers "Is the system authorized?" — 7.12 owns "How do we arm/go-live?". No 7.12 functionality implemented.

### GATE 29 — Report Completeness

**Verdict: PASS** (this document)

All 29 gates documented with verdicts and evidence.

---

## Audit Summary

| Verdict   | Count | Gates |
| --------- | ----- | ----- |
| PASS      | 29    | 1-29  |
| SOFT FAIL | 0     | —     |
| HARD FAIL | 0     | —     |

**All 29 gates PASS.** Gate 10 (cal report issue handling) fixed during testing.

---

## Constraints Compliance

| Constraint                        | Status |
| --------------------------------- | ------ |
| No second CalibrationResult model | PASS   |
| No second WarpMesh model          | PASS   |
| No second replay format           | PASS   |
| STOP AT REVIEW (no 7.12)          | PASS   |
| HARDWARE_PENDING ≠ PASS           | PASS   |
| Gate wiring ≠ gate passing        | PASS   |
| No large concurrency framework    | PASS   |
| Existing validators preserved     | PASS   |
