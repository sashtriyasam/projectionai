# Phase 7.6 — Capture State + Recovery: Report

**Status:** DONE
**Date:** 2026-08-28
**Author:** Sisyphus (orchestrator)
**Gate:** G-10

---

## 1. Objective

Build production capture-state and recovery layer — capture state machine, frame acceptance protocol, retry, disconnect recovery, partial sequence preservation, and enhanced metrics. Compose with `PatternPresentationSession` + `FrameSource` without duplicating `SynchronizedCaptureSession` or `ProductionWorkflow`.

## 2. Delivered Artifacts

| File                                                      | Type        | Description                                                                                                                                              |
| --------------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/projectionai/services/capture_session.py`            | **Created** | `CaptureSession`, `CaptureState`, `CaptureConfig`, `CaptureMetrics`, `CaptureResult`, `FrameAcceptancePolicy`, `DefaultFrameAcceptance`, error hierarchy |
| `tests/unit/services/test_capture_session.py`             | **Created** | 72 tests across 18 test classes                                                                                                                          |
| `.planning/phases/7.6-capture-recovery/DEPENDENCY-MAP.md` | **Created** | Contract audit and composition plan                                                                                                                      |

## 3. Architecture

```
CalibrationSequence
        │
        ▼
CaptureSession (orchestrator)
    ├── PatternPresentationSession (display lifecycle)
    ├── FrameSource (camera capture)
    ├── FrameAcceptancePolicy (validation)
    └── CaptureConfig (tuning)

State machine:
    IDLE → PRESENTING → WAITING → CAPTURED → VALIDATING → COMPLETE
                                                  │
                              ┌───────────────────┤
                              ▼                   ▼
                          TIMEOUT             FAILED
                              │                   │
                              └─────────► RETRYING ──► PRESENTING

    CANCELLED (at any point via cooperative check)
```

**Key design decisions:**

- `CaptureSession` composes `PatternPresentationSession` + `FrameSource` — does NOT duplicate `SynchronizedCaptureSession` (per-pattern barrier/latency) or `ProductionWorkflow` (global state machine)
- `CaptureState` is scoped to capture behavior only; maps to workflow stage externally
- `FrameAcceptancePolicy` protocol allows swapping validation without changing capture session
- `DefaultFrameAcceptance` validates: non-None, shape (H,W,3) uint8, sequence/pattern ID match, latency bounds, timestamp monotonicity
- `CaptureMetrics` tracks per-sequence statistics with p50/p95/p99 percentiles
- `CaptureResult` preserves partial frames on failure for graceful degradation
- `BEST_EFFORT_TIMESTAMP` semantics preserved — presentation timestamps are `time.monotonic_ns()` approximations, NOT hardware-vsync boundaries
- Pre-sequence cancel check: `cancel()` before `capture_sequence()` returns immediately
- Between-pattern cancel: cooperative check after each retry loop
- Timeout propagation: `CaptureTimeoutError` re-raised after retries exhausted → outer handler sets TIMEOUT state
- Camera disconnect classification: only genuine `CameraError` instances from `FrameSource` are classified as camera disconnects; unexpected `FrameSource` exceptions and programming errors propagate unchanged

## 4. Test Results

```
72 passed in 1.94s
```

| Test Class                      | Tests | Status     |
| ------------------------------- | ----- | ---------- |
| `TestCaptureSequenceHappyPath`  | 5     | ALL PASSED |
| `TestFrameAcceptance`           | 5     | ALL PASSED |
| `TestRetry`                     | 3     | ALL PASSED |
| `TestCameraDisconnect`          | 3     | ALL PASSED |
| `TestCancellation`              | 3     | ALL PASSED |
| `TestPartialSequence`           | 2     | ALL PASSED |
| `TestMetrics`                   | 7     | ALL PASSED |
| `TestTimeout`                   | 3     | ALL PASSED |
| `TestStateMachine`              | 5     | ALL PASSED |
| `TestDefaultFrameAcceptance`    | 13    | ALL PASSED |
| `TestCaptureResult`             | 4     | ALL PASSED |
| `TestCaptureConfig`             | 3     | ALL PASSED |
| `TestCaptureMetricsPercentiles` | 4     | ALL PASSED |
| `TestExceptionClassification`   | 2     | ALL PASSED |
| `TestStaleFrameSemantics`       | 4     | ALL PASSED |
| `TestDataIntegrity`             | 2     | ALL PASSED |
| `TestCancelStopsRetry`          | 2     | ALL PASSED |
| `TestWarmup`                    | 2     | ALL PASSED |

**Total: 72/72 — all passing, no xfail, no skip.**

**Regression suite (existing tests):**

```
tests/unit/calibration/test_capture_sync.py       15/15 passed
tests/unit/services/test_pattern_presentation.py   29/29 passed
tests/unit/application/test_calibration_workflow.py 22/22 passed
```

## 5. Quality Gates

| Gate            | Result                            |
| --------------- | --------------------------------- |
| `mypy --strict` | ✅ Success: no issues found       |
| `ruff check`    | ✅ All checks passed              |
| `ruff format`   | ✅ All files already formatted    |
| `pytest`        | ✅ 72/72 passed, 66/66 regression |

## 6. Review Gate Audit (18-Gate)

| Gate | Description                                   | Status                                                                                                                                    |
| ---- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | State machine correctness                     | ✅ PASS — 9 states, cooperative cancel, timeout propagation, proper terminal states                                                       |
| 2    | Does NOT duplicate SynchronizedCaptureSession | ✅ PASS — SynchronizedCaptureSession handles per-pattern barrier; CaptureSession handles sequence lifecycle                               |
| 3    | Does NOT duplicate ProductionWorkflow         | ✅ PASS — CaptureState maps to WorkflowStage externally, no parallel safety state machine                                                 |
| 4    | BEST_EFFORT_TIMESTAMP preserved               | ✅ PASS — Presentation timestamps are `time.monotonic_ns()` approximations, not vsync                                                     |
| 5    | Frame acceptance protocol                     | ✅ PASS — `FrameAcceptancePolicy` protocol; `DefaultFrameAcceptance` validates shape/dtype/IDs/latency/monotonicity                       |
| 6    | Partial sequence preservation                 | ✅ PASS — `CaptureResult.partial_frames` preserves valid frames before failure                                                            |
| 7    | Camera disconnect recovery                    | ✅ PASS — Programming errors NOT masked as disconnect; only genuine CameraError classified                                                |
| 8    | Retry bounded                                 | ✅ PASS — `retry_count` config; metrics track retry attempts                                                                              |
| 9    | Cancel cooperative                            | ✅ PASS — Pre-sequence cancel, between-pattern cancel, asyncio.CancelledError caught; `_cancelled` checks inside retry exception handlers |
| 10   | Timeout propagation                           | ✅ PASS — `CaptureTimeoutError` re-raised after retries → TIMEOUT state                                                                   |
| 11   | Config validation                             | ✅ PASS — `CaptureConfig` is frozen dataclass; defaults reasonable                                                                        |
| 12   | Metrics accuracy                              | ✅ PASS — p50/p95/p99 percentiles, success_rate, latencies tracked; `camera_errors` incremented on stale-frame disconnect                 |
| 13   | Test quality                                  | ✅ PASS — 72 tests, no xfail, no skip; covers exception classification, stale-frame semantics, data integrity, cancel-during-retry        |
| 14   | No type errors                                | ✅ PASS — `mypy --strict` clean, zero errors                                                                                              |
| 15   | No lint errors                                | ✅ PASS — `ruff check` and `ruff format` clean                                                                                            |
| 16   | Regression tests pass                         | ✅ PASS — 66/66 existing tests unaffected                                                                                                 |
| 17   | Hardware gates unchanged                      | ✅ PASS — Phase 6 hardware gates remain HARDWARE_PENDING                                                                                  |
| 18   | STOP AT REVIEW                                | ✅ PASS — Not starting 7.7                                                                                                                |

### Gate Audit Findings & Fixes Applied

| #   | Finding                                                                                                                                                                                                    | Severity | Action                                                                                                                               |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Tautology `if frame.image.dtype != frame.image.dtype:` in `DefaultFrameAcceptance` — always False, dead code                                                                                               | MEDIUM   | Removed tautology (line removed from acceptance check)                                                                               |
| 2   | `except Exception` in `_present_and_capture` silently converted ALL errors to `CameraDisconnectError` — programming bugs would be masked                                                                   | HIGH     | Removed bare `except Exception`; programming bugs now propagate to top-level handler                                                 |
| 3   | `frames=tuple(accepted_frames)` on failure return paths — contradicting docstring that says "empty on failure"                                                                                             | MEDIUM   | Changed to `frames=()` on both failure paths; `partial_frames` still preserves valid frames                                          |
| 4   | `camera_errors` not incremented when stale-frame threshold raises `CameraDisconnectError` inside `except FrameRejectionError` — raised exception bypasses the `except CameraDisconnectError` handler below | MEDIUM   | Added `self._metrics.camera_errors += 1` before raising                                                                              |
| 5   | Retry loop did not check `_cancelled` inside exception handlers — cooperative cancel ineffective when mock completes faster than cancel task schedules                                                     | MEDIUM   | Added `if self._cancelled: return None, retries` at top of `FrameRejectionError`, `CaptureTimeoutError`, and `CaptureError` handlers |
| 6   | Test `test_correct_ids_but_stale_image_rejected` assumed (1,1,3) uint8 image would be rejected — but it passes all acceptance checks                                                                       | LOW      | Renamed to `test_correct_ids_but_wrong_dtype_rejected`; uses wrong dtype (float32) instead                                           |
| 7   | Test `test_cancel_between_retries` used monkeypatch that ran entire retry loop in one call — cancel never reached                                                                                          | LOW      | Rewrote to use `sess.cancel()` + `asyncio.sleep(0)` yielding mock for cooperative cancellation                                       |

## 7. Constraints Verified

| Constraint                                                              | Status      |
| ----------------------------------------------------------------------- | ----------- |
| Do NOT touch `D:\PROJECTIONAI-camera`                                   | ✅ Verified |
| Do NOT rewrite Phase 6 calibration algorithms                           | ✅ Verified |
| Do NOT duplicate ProductionWorkflow state                               | ✅ Verified |
| Do NOT put calibration/reconstruction/solver math inside UI widgets     | ✅ Verified |
| Do NOT duplicate SynchronizedCaptureSession                             | ✅ Verified |
| Do NOT introduce a second replay format                                 | ✅ Verified |
| Preserve BEST_EFFORT_TIMESTAMP semantics                                | ✅ Verified |
| Never label VSYNC_LOCKED / FRAME_PRESENTED without hardware observation | ✅ Verified |
| No module/session-scoped QApplication fixtures                          | ✅ Verified |
| No `xfail` or skipped tests                                             | ✅ Verified |
| STOP AT REVIEW — DO NOT START 7.7                                       | ✅ Verified |

## 8. Google Sheet Closure

| Sheet               | Action                 | Row | Result |
| ------------------- | ---------------------- | --- | ------ |
| `01_MASTER_PLAN`    | Status → DONE, % → 100 | 42  | ✅     |
| `16_STATUS_HISTORY` | Appended REVIEW → DONE | 22  | ✅     |
| `12_CHANGELOG`      | Appended CH-011        | 22  | ✅     |
| Hardware gates      | Unchanged              | —   | ✅     |

## 9. Files Changed

```
src/projectionai/services/capture_session.py              (NEW — ~853 lines, 3 fixes applied during audit)
tests/unit/services/test_capture_session.py               (NEW — ~1670 lines, 10 tests added during audit)
.planning/phases/7.6-capture-recovery/DEPENDENCY-MAP.md   (NEW — contract audit)
.planning/phases/7.6-capture-recovery/REPORT.md           (NEW — this report)
```

## 9. Known Limitations

- Frame timing is `BEST_EFFORT_TIMESTAMP` — no hardware vsync observation yet
- `max_stale_frames` disconnect detection is opt-in (0 = reject immediately)
- No multi-camera support (single `camera_id` per session)
- No automatic retry backoff (immediate retries only)
- `FrameAcceptancePolicy` protocol is sync — async acceptance not supported

## 10. Recommendations for 7.7

- 7.7 (Display Output Integration) should wire `CaptureSession` into the production workflow
- Consider adding exponential backoff for retry logic
- Hardware validation gates remain `HARDWARE_PENDING` — do not advance until physical projector/camera available
- `FrameAcceptancePolicy` may benefit from async variant for ML-based acceptance in future phases

---

**Phase 7.6 is DONE. Do NOT start 7.7 automatically.**
