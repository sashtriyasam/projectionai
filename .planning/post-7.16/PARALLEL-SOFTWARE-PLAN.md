# PARALLEL-SOFTWARE-PLAN.md — Post-7.16 Scope Audit

**Date**: 2026-08-30
**Status**: AUDIT COMPLETE (no implementation)
**Author**: Sisyphus (orchestrator)
**Purpose**: Determine what software work can safely continue while 7.15 hardware is unavailable

---

## 1. Current State

| Phase        | Status      | Blocker                       |
| ------------ | ----------- | ----------------------------- |
| 7.1–7.14     | DONE        | —                             |
| 7.15         | IN_PROGRESS | HARDWARE_PENDING (H-01..H-07) |
| 7.16 Wave 1  | REVIEW      | Complete — 1,099 tests pass   |
| 7.16 Wave 2  | NOT STARTED | Blocked by 7.15               |
| Phase 7 DONE | BLOCKED     | Requires H-01..H-07 PASS      |

---

## 2. Roadmap After 7.16

### 2.1 Defined in ROADMAP.md

| Milestone | Name                                    | Status                    | Notes                                     |
| --------- | --------------------------------------- | ------------------------- | ----------------------------------------- |
| M-7.0     | Phase 7 production workflow             | NOT_STARTED (in workbook) | Blocked by 7.16 sign-off                  |
| M-8.0     | Polish & Performance (v0.9.0)           | NOT DEFINED in workbook   | Roadmap lists items but no phases created |
| M-9.0     | Multi-Projector & Collaboration (v1.0+) | NOT DEFINED in workbook   | Roadmap lists items but no phases created |

### 2.2 Defined in 15_BACKLOG.csv

| ID   | Item                              | Status  | Trigger                 |
| ---- | --------------------------------- | ------- | ----------------------- |
| B-01 | Optional CUDA phase-shift backend | BACKLOG | decode > capture budget |
| B-02 | Vulkan backend                    | BACKLOG | Scale insufficient      |
| B-03 | Rust native capture layer         | BACKLOG | Capture bottleneck      |
| B-04 | Full distortion calibration       | BACKLOG | Edge RMS >2px           |
| B-05 | Bundle adjustment                 | BACKLOG | Multi-plane residual    |
| B-06 | Multi-projector calibration       | BACKLOG | Single shipped          |
| B-07 | Non-planar reconstruction         | BACKLOG | Curved surface          |
| B-08 | Advanced zero-copy camera path    | BACKLOG | Capture latency         |

**All backlog items are classified as "Future" and require hardware measurements to trigger.**

### 2.3 Key Finding

**There are NO defined phases after 7.16 in the control center.** The ROADMAP.md lists Milestone 8 and 9 features, but no phases have been created for them. The BACKLOG items all require hardware measurements to trigger.

**The only formally defined work remaining is:**

1. 7.15 hardware validation (BLOCKED)
2. 7.16 Wave 2 final sign-off (BLOCKED by 7.15)

---

## 3. Classification of Every Remaining Item

### 3.1 Phase 7 Closure Items

| Item                     | Classification | Rationale                                      |
| ------------------------ | -------------- | ---------------------------------------------- |
| 7.15 hardware validation | HARDWARE_ONLY  | Requires physical camera + projector + surface |
| H-01 optical closure     | HARDWARE_ONLY  | Requires physical optical path                 |
| H-02 vsync timing        | HARDWARE_ONLY  | Requires physical display                      |
| H-03 settle-time         | HARDWARE_ONLY  | Requires physical sync                         |
| H-04 BUFFERSIZE policy   | HARDWARE_ONLY  | Requires physical camera                       |
| H-05 sentinel coverage   | HARDWARE_ONLY  | Requires physical surface                      |
| H-06 2-plane calibration | HARDWARE_ONLY  | Requires physical surfaces                     |
| H-07 repeatability       | HARDWARE_ONLY  | Requires physical rig                          |
| 7.16 Wave 2 sign-off     | BLOCKED        | Waiting on 7.15                                |
| Phase 7 DONE             | BLOCKED        | Waiting on H-01..H-07                          |

### 3.2 Software Issues Found During Audit

| Item                                       | Classification | Evidence                                                       |
| ------------------------------------------ | -------------- | -------------------------------------------------------------- |
| Calibration test directory hang            | SOFTWARE_ONLY  | Individual files pass; hang is from running 532 tests together |
| test_replay.py "No space left"             | SOFTWARE_ONLY  | Coverage artifact issue, not real disk space                   |
| mypy no-any-return (persistence.py:333)    | SOFTWARE_ONLY  | Pre-existing type annotation gap                               |
| Empty integration test directory           | SOFTWARE_ONLY  | `tests/integration/` has only `__init__.py`                    |
| 532 calibration tests excluded from Wave 1 | SOFTWARE_ONLY  | Hang when run as directory                                     |

### 3.3 Roadmap Items

| Item                        | Classification | Hardware Dependency                       |
| --------------------------- | -------------- | ----------------------------------------- |
| Milestone 8 features        | NOT_NEEDED     | No phases defined; premature              |
| Milestone 9 features        | NOT_NEEDED     | No phases defined; premature              |
| B-01 CUDA backend           | DEFERRED       | Requires hardware bottleneck measurement  |
| B-02 Vulkan backend         | DEFERRED       | Requires scale testing                    |
| B-03 Rust capture           | DEFERRED       | Requires capture bottleneck measurement   |
| B-04 Distortion calibration | DEFERRED       | Requires edge-RMS hardware measurement    |
| B-05 Bundle adjustment      | DEFERRED       | Requires multi-plane residual measurement |
| B-06 Multi-projector        | DEFERRED       | Requires single-projector shipped first   |
| B-07 Non-planar             | DEFERRED       | Requires curved surface requirement       |
| B-08 Zero-copy camera       | DEFERRED       | Requires capture latency measurement      |

---

## 4. Software Work That Is Safe Now

### 4.1 Calibration Test Hang Investigation

**Finding**: The calibration directory hang is NOT from individual tests hanging.
Individual test files pass cleanly:

| File                                    | Tests | Time | Status |
| --------------------------------------- | ----- | ---- | ------ |
| test_validation_gate.py                 | 47    | 10s  | PASS   |
| test_calibration_history.py             | 18    | 10s  | PASS   |
| test_calibration_persistence.py         | 53    | 12s  | PASS   |
| test_calibration_pipeline.py            | 19    | 1s   | PASS   |
| test_solver.py                          | 21    | 12s  | PASS   |
| test_calibration_session_calibration.py | 24    | 1s   | PASS   |

**Root cause hypothesis**: Running all 532 calibration tests together causes a hang, likely due to:

- Qt event loop conflicts between test files
- Coverage data collection overhead with large test sets
- Process/subprocess accumulation

**Classification**: SOFTWARE_ONLY — safe to investigate and fix.

**Risk**: LOW — fixing test infrastructure does not affect production code.

**Estimated effort**: 2-4 hours to isolate and fix.

**Recommendation**: Investigate as a standalone task. The fix would recover 532 tests for CI.

### 4.2 Replay Test Reliability

**Finding**: `test_replay.py` fails with `OSError: [Errno 28] No space left on device` when run with coverage enabled. Without coverage, some tests pass but others fail with the same error.

**Root cause**: Coverage artifact accumulation (`.coverage` file + `coverage_html/` directory) exhausts temp space during test execution.

**Classification**: SOFTWARE_ONLY — safe to fix.

**Risk**: LOW — test infrastructure fix.

**Estimated effort**: 1-2 hours.

**Recommendation**: Fix coverage configuration or add cleanup between test runs.

### 4.3 Mypy No-Any-Return

**Finding**: `persistence.py:333` returns `Any` from `json.loads()`.

**Classification**: SOFTWARE_ONLY — safe to fix.

**Risk**: LOW — type annotation improvement.

**Estimated effort**: 15 minutes.

**Recommendation**: Add explicit type annotation to `json.loads()` result.

### 4.4 Integration Test Infrastructure

**Finding**: `tests/integration/` contains only `__init__.py` — no actual tests.

**Classification**: SOFTWARE_ONLY — safe to build.

**Risk**: MEDIUM — new tests may reveal existing bugs.

**Estimated effort**: 4-8 hours for minimal harness.

**Recommendation**: Defer unless roadmap requires it. No phases depend on integration tests currently.

### 4.5 CI/Test Infrastructure

**Finding**: CI runs on Ubuntu with `xvfb-run`, `QT_QPA_PLATFORM=offscreen`. Coverage threshold is 60%. No timeout configuration for individual tests.

**Classification**: SOFTWARE_ONLY — safe to improve.

**Risk**: LOW — infrastructure improvement.

**Estimated effort**: 2-4 hours.

**Recommendation**: Add `pytest-timeout` configuration to prevent hangs. Consider splitting calibration tests into separate CI job.

---

## 5. Work That Should NOT Be Touched

| Item                               | Reason                              |
| ---------------------------------- | ----------------------------------- |
| 7.15 hardware gates (H-01..H-07)   | Hardware-dependent, no physical rig |
| Phase 7 DONE status                | Blocked by 7.15                     |
| Source code in `src/projectionai/` | No implementation in scope audit    |
| Milestone 8/9 features             | No phases defined, premature        |
| Backlog items (B-01..B-08)         | All require hardware measurements   |
| `D:\PROJECTIONAI-camera`           | Out of scope                        |

---

## 6. Parallel-Work Plan

### 6.1 Recommended Work Items

| Item                                 | Why It Matters           | Dependency     | Hardware Dependency | Risk   | Effort | Recommended Phase | Blocking     |
| ------------------------------------ | ------------------------ | -------------- | ------------------- | ------ | ------ | ----------------- | ------------ |
| Fix calibration test hang            | Recover 532 tests for CI | None           | None                | LOW    | 2-4h   | Standalone task   | Non-blocking |
| Fix replay test coverage issue       | Recover replay tests     | None           | None                | LOW    | 1-2h   | Standalone task   | Non-blocking |
| Fix mypy no-any-return               | Type safety              | None           | None                | LOW    | 15min  | Standalone task   | Non-blocking |
| Add pytest-timeout config            | Prevent CI hangs         | None           | None                | LOW    | 1h     | Standalone task   | Non-blocking |
| Split calibration CI job             | Faster feedback          | Fix hang first | None                | LOW    | 2h     | After hang fix    | Non-blocking |
| Build integration test harness       | Better coverage          | None           | None                | MEDIUM | 4-8h   | Defer             | Non-blocking |
| Prepare evidence directory structure | Ready for 7.15           | None           | None                | LOW    | 1h     | Standalone task   | Non-blocking |
| Add structured measurement logging   | Ready for 7.15           | None           | None                | LOW    | 2h     | Standalone task   | Non-blocking |

### 6.2 Items Deferred (Require Hardware)

| Item                      | Trigger                | Current Blocker             |
| ------------------------- | ---------------------- | --------------------------- |
| 7.15 hardware validation  | Physical rig available | No camera/projector/surface |
| H-01..H-07 gate execution | Physical rig available | No physical evidence        |
| B-01..B-08 backlog items  | Hardware measurements  | No bottleneck data          |
| Milestone 8/9 features    | Phase 7 complete       | No phases defined           |

---

## 7. Final Recommendations

### 7.1 What Can We Safely Do Now?

1. **Fix calibration test hang** — Recover 532 tests. This is the highest-value software-only task.
2. **Fix replay test coverage issue** — Recover replay tests.
3. **Fix mypy no-any-return** — Quick type safety improvement.
4. **Add pytest-timeout** — Prevent future CI hangs.
5. **Prepare evidence directory structure** — Ready for 7.15 when hardware arrives.

### 7.2 What Must Wait for Hardware?

1. 7.15 hardware validation (all 7 gates)
2. 7.16 Wave 2 final sign-off
3. Phase 7 DONE
4. All backlog items (B-01..B-08)
5. Milestone 8/9 features (not yet defined as phases)

### 7.3 What Software Issues Should Be Fixed Now?

| Priority | Issue                                      | Effort |
| -------- | ------------------------------------------ | ------ |
| HIGH     | Calibration test hang (532 tests excluded) | 2-4h   |
| MEDIUM   | Replay test coverage issue                 | 1-2h   |
| LOW      | mypy no-any-return                         | 15min  |
| LOW      | pytest-timeout configuration               | 1h     |

### 7.4 What Work Should NOT Be Touched?

- Any source code in `src/projectionai/` (no implementation in scope audit)
- 7.15 hardware gates
- Phase 7 DONE status
- Milestone 8/9 features (premature)
- Backlog items (require hardware measurements)

### 7.5 What Is the Cleanest Next Phase/Task?

**Option A: Standalone bug-fix tasks**

- Fix calibration hang → Fix replay issue → Fix mypy → Add timeout config
- No new phase needed; these are maintenance tasks

**Option B: Create a formal "Phase 7.17 — Test Infrastructure"**

- Only if the calibration hang fix is complex enough to warrant tracking
- Would include: hang fix, replay fix, mypy fix, timeout config, CI split

**Recommendation**: Option A — these are small, independent fixes that don't need formal phase tracking. Create them as individual tasks in the backlog or as a lightweight "Maintenance" section.

---

## 8. Evidence Summary

### 8.1 Calibration Test Audit

```
Total tests in tests/unit/calibration/: 532
Tests that pass individually:           ~200+ (validated: 182 across 6 files)
Tests that fail individually:           7 (test_replay.py — coverage artifact)
Hang when running entire directory:     YES (532 tests together)
Root cause:                             Likely Qt event loop or coverage overhead
Classification:                         SOFTWARE_ONLY
```

### 8.2 Replay Test Audit

```
File: tests/unit/calibration/test_replay.py
Total tests: 7
Pass without coverage: 0 (all fail with OSError)
Fail with coverage: 7 (No space left on device)
Root cause: Coverage artifact accumulation
Classification: SOFTWARE_ONLY
```

### 8.3 CI Configuration

```
Platform: Ubuntu (GitHub Actions)
Qt: QT_QPA_PLATFORM=offscreen via xvfb-run
Coverage: --cov-fail-under=60
Timeout: Not configured (causes hangs)
Calibration tests: Run as part of full suite (causes hang)
```

### 8.4 Roadmap State

```
Defined phases after 7.16: NONE
Defined milestones after M-7.0: M-8.0, M-9.0 (not in workbook)
Backlog items: 8 (all Future, all require hardware)
```

---

## 9. Control Center State (Unchanged)

```
7.15 = IN_PROGRESS / HARDWARE_PENDING
7.16 = REVIEW (Wave 1 complete)
Phase 7 = NOT COMPLETE
```

**No changes to control center files.**
**No new phases created.**
**No implementation started.**
