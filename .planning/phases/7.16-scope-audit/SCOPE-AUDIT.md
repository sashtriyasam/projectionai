# SCOPE-AUDIT.md — Phase 7.16 Scope / Dependency Audit

**Date**: 2026-08-30
**Status**: AUDIT COMPLETE (no implementation)
**Author**: Sisyphus (orchestrator)

---

## 1. Historical Scope

| Field             | Value                                       |
| ----------------- | ------------------------------------------- |
| Phase             | 7.16                                        |
| Description       | "Phase 7 sign-off — Verification + reports" |
| Historical Status | BACKLOG                                     |
| Dependencies      | 7.15                                        |
| Priority          | HIGH                                        |
| Validation Gates  | None listed                                 |

**7.16 was the final closure phase for Phase 7.** Its purpose was to verify
all Phase 7 subphases are complete, compile reports, run regression tests,
and produce a final sign-off document.

---

## 2. Current Phase 7 State

| Phase | Description                 | Status         | Reports                               |
| ----- | --------------------------- | -------------- | ------------------------------------- |
| 7.1   | Workflow orchestration      | ✅ DONE        | REPORT.md                             |
| 7.2   | Device selection UX         | ✅ DONE        | REPORT.md                             |
| 7.3   | Surface setup               | ✅ DONE        | REPORT.md                             |
| 7.4   | Calibration progress UI     | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.5   | Pattern presentation        | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md, PLAN.md |
| 7.6   | Capture recovery            | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.7   | Decode/reconstruction/solve | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md, PLAN.md |
| 7.8   | Calibration result review   | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.9   | Warp preview                | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.10  | Calibration persistence     | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.11  | Validation & safety         | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.12  | Arm/live workflow           | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.13  | Error recovery              | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.14  | End-to-end integration      | ✅ DONE        | REPORT.md, DEPENDENCY-MAP.md          |
| 7.15  | Hardware validation         | ⏳ IN_PROGRESS | REPORT.md (HARDWARE_PENDING)          |
| 7.16  | Sign-off                    | ⏸ NOT_STARTED  | This file                             |

**14/16 subphases complete. 1 blocked (7.15). 1 not started (7.16).**

---

## 3. Requirement Classification

For every potential 7.16 deliverable, classify against hardware dependency:

### 3.1 Software Regression Tests

| Requirement                           | Classification | Rationale                   |
| ------------------------------------- | -------------- | --------------------------- |
| Run `ruff check src/`                 | SOFTWARE_ONLY  | No hardware needed          |
| Run `ruff format --check src/`        | SOFTWARE_ONLY  | No hardware needed          |
| Run `mypy --strict src/projectionai/` | SOFTWARE_ONLY  | No hardware needed          |
| Run `pytest` regression suite         | SOFTWARE_ONLY  | Existing tests, no hardware |

### 3.2 Report Compilation

| Requirement                    | Classification    | Rationale                                 |
| ------------------------------ | ----------------- | ----------------------------------------- |
| Compile 7.1-7.14 reports       | ALREADY_DELIVERED | All 14 REPORT.md files exist              |
| Summarize Phase 7 test results | SOFTWARE_ONLY     | 378/378 tests pass (from 7.14)            |
| Compile hardware gate status   | ALREADY_DELIVERED | H-01..H-07 = HARDWARE_PENDING (from 7.15) |
| Write final Phase 7 summary    | SOFTWARE_ONLY     | Can summarize without hardware evidence   |

### 3.3 Verification Checks

| Requirement                          | Classification    | Rationale                      |
| ------------------------------------ | ----------------- | ------------------------------ |
| Verify 7.1-7.14 all DONE             | ALREADY_DELIVERED | Confirmed in workbook          |
| Verify 7.15 status                   | ALREADY_DELIVERED | IN_PROGRESS / HARDWARE_PENDING |
| Verify no source regressions         | SOFTWARE_ONLY     | Ruff/mypy/pytest               |
| Verify gate integration (V-01..V-07) | ALREADY_DELIVERED | Verified in 7.14               |
| Verify persistence round-trip        | ALREADY_DELIVERED | Verified in 7.14 (67 tests)    |
| Verify error recovery paths          | ALREADY_DELIVERED | Verified in 7.14               |

### 3.4 Hardware-Dependent Items

| Requirement       | Classification   | Rationale                                      |
| ----------------- | ---------------- | ---------------------------------------------- |
| Confirm H-01 PASS | HARDWARE_BLOCKED | Requires physical camera + projector           |
| Confirm H-02 PASS | HARDWARE_BLOCKED | Requires physical projector                    |
| Confirm H-03 PASS | HARDWARE_BLOCKED | Requires physical camera + projector           |
| Confirm H-04 PASS | HARDWARE_BLOCKED | Requires physical camera                       |
| Confirm H-05 PASS | HARDWARE_BLOCKED | Requires physical camera + projector           |
| Confirm H-06 PASS | HARDWARE_BLOCKED | Requires physical camera + projector + surface |
| Confirm H-07 PASS | HARDWARE_BLOCKED | Requires physical camera + projector + surface |
| Mark Phase 7 DONE | HARDWARE_BLOCKED | Cannot close without H-01..H-07 evidence       |

---

## 4. Duplication Audit

Comparing 7.16 against completed phases to avoid duplicating work:

| 7.16 Potential Task                      | Already Done In | Duplication?        |
| ---------------------------------------- | --------------- | ------------------- |
| Workflow state machine verification      | 7.14 §3.2       | ✅ DUPLICATE — skip |
| Output state machine verification        | 7.14 §3.3       | ✅ DUPLICATE — skip |
| UI ↔ ViewModel binding verification      | 7.14 §4         | ✅ DUPLICATE — skip |
| Validation gate integration (V-01..V-07) | 7.14 §5         | ✅ DUPLICATE — skip |
| Error recovery path verification         | 7.14 §6         | ✅ DUPLICATE — skip |
| Persistence round-trip verification      | 7.14 §7         | ✅ DUPLICATE — skip |
| Test suite execution (378 tests)         | 7.14 §2         | ✅ DUPLICATE — skip |
| Hardware gate status                     | 7.15 §2         | ✅ DUPLICATE — skip |
| Software quality baseline                | 7.15 §4         | ✅ DUPLICATE — skip |

**Nothing in 7.16's historical scope requires re-doing work from 7.1-7.14.**

---

## 5. Hardware Dependency Matrix

| Gate | 7.16 Needs It?          | Classification   | Can 7.16 Proceed? |
| ---- | ----------------------- | ---------------- | ----------------- |
| H-01 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |
| H-02 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |
| H-03 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |
| H-04 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |
| H-05 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |
| H-06 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |
| H-07 | Only for final sign-off | HARDWARE_BLOCKED | YES (partial)     |

**Key insight**: 7.16 can execute ALL software-only verification tasks now.
It cannot complete the FINAL sign-off (marking Phase 7 DONE) until 7.15
hardware gates pass. These are two different milestones:

1. **Software verification** (can happen NOW): regression tests, report
   compilation, completeness check
2. **Final sign-off** (BLOCKED on 7.15): marking Phase 7 DONE, confirming
   all H-01..H-07 PASS

---

## 6. Software-Only Work That Can Safely Proceed

The following 7.16 tasks can execute WITHOUT physical hardware:

1. **Regression suite** — Run ruff, mypy, pytest to confirm no software regressions
2. **Completeness audit** — Verify all 7.1-7.14 reports exist and are substantive
3. **Gate integration verification** — Confirm V-01..V-07 are wired (already done in 7.14)
4. **Phase 7 summary report** — Compile a summary of all subphase deliverables
5. **Workbook finalization** — Update 7.16 status (but NOT mark Phase 7 DONE)

These tasks produce a **partial sign-off** that can be completed now. The
**full sign-off** (Phase 7 DONE) must wait for 7.15 hardware evidence.

---

## 7. Explicit Non-Goals (for 7.16)

The following are OUT OF SCOPE for 7.16:

- Marking Phase 7 DONE (requires H-01..H-07 PASS)
- Producing hardware validation evidence (that's 7.15's job)
- Running physical calibration tests (that's 7.15's job)
- Changing source code (no code changes in sign-off phase)
- Marking any hardware gate PASS without measured evidence

---

## 8. Recommendation

### Can 7.16 Start? **YES — partially**

7.16 can execute the **software verification subset** now:

| Task                       | Blocked? | Why                           |
| -------------------------- | -------- | ----------------------------- |
| Run regression tests       | NO       | Software-only                 |
| Verify report completeness | NO       | All reports exist             |
| Compile Phase 7 summary    | NO       | Can summarize without HW      |
| Update workbook            | NO       | Administrative                |
| Mark Phase 7 DONE          | **YES**  | Requires 7.15 H-01..H-07 PASS |

### Recommended Execution Plan

**Wave 1 (NOW — no hardware needed):**

- Run ruff check, ruff format, mypy (confirm baseline)
- Run pytest regression suite
- Verify all 14 subphase reports exist
- Write Phase 7 summary report ( SOFTWARE sign-off)
- Update 7.16 status to IN_PROGRESS

**Wave 2 (AFTER 7.15 completes):**

- Append hardware gate results to summary
- Mark Phase 7 DONE
- Final workbook update

### Risk of Starting Now

**LOW.** Software verification is non-destructive and produces useful
intermediate results. The only risk is premature closure — which is
mitigated by NOT marking Phase 7 DONE until 7.15 completes.

---

## 9. Summary

| Question                                | Answer                                                  |
| --------------------------------------- | ------------------------------------------------------- |
| Can 7.16 proceed independently of 7.15? | **PARTIALLY** — software tasks yes, final sign-off no   |
| What's blocked?                         | Final closure (Phase 7 DONE) — requires H-01..H-07 PASS |
| What's safe to do now?                  | Regression tests, report compilation, summary           |
| Should we start?                        | **YES — Wave 1 only** (software verification)           |
| Should we mark Phase 7 DONE?            | **NO — WAIT for 7.15**                                  |
| Duplication with 7.1-7.14?              | **NONE** — all verification already done                |
| Hardware dependency?                    | **ONLY for final sign-off** (Wave 2)                    |

---

## 10. Appendix: File Inventory

All Phase 7 subphase deliverables confirmed on disk:

```
.planning/phases/
├── 7.1-production-calibration-workflow/REPORT.md           ✅
├── 7.2-device-selection/REPORT.md                          ✅
├── 7.3-surface-setup/REPORT.md                             ✅
├── 7.4-calibration-progress-ui/{REPORT.md, DEPENDENCY-MAP.md}  ✅
├── 7.5-pattern-presentation/{REPORT.md, PLAN.md, DEPENDENCY-MAP.md}  ✅
├── 7.6-capture-recovery/{REPORT.md, DEPENDENCY-MAP.md}    ✅
├── 7.7-decode-reconstruction-solve/{REPORT.md, PLAN.md, DEPENDENCY-MAP.md}  ✅
├── 7.8-calibration-result-review/{REPORT.md, DEPENDENCY-MAP.md}  ✅
├── 7.9-warp-preview/{REPORT.md, DEPENDENCY-MAP.md}        ✅
├── 7.10-calibration-persistence/{REPORT.md, DEPENDENCY-MAP.md}  ✅
├── 7.11-validation-safety-workflow/{REPORT.md, DEPENDENCY-MAP.md}  ✅
├── 7.12-arm-live/{REPORT.md, DEPENDENCY-MAP.md}            ✅
├── 7.13-runtime-safety/{REPORT.md, DEPENDENCY-MAP.md}     ✅
├── 7.14-end-to-end-integration/{REPORT.md, DEPENDENCY-MAP.md}  ✅
├── 7.15-hardware-validation/REPORT.md                      ✅ (HARDWARE_PENDING)
└── 7.16-scope-audit/SCOPE-AUDIT.md                         ✅ (this file)
```
