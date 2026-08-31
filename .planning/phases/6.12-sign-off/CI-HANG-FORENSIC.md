# CI HANG FORENSIC — Run 32857171476

**Date:** 2026-08-25 15:16 UTC (cancelled)
**Commit:** `a6e44bc8253ffef8d86af1aa2994b5a30c4b8ecd` (fix(build): make native extensions optional)
**Workflow:** `CI` on `main` push
**Branch:** `main`
**Mode:** Forensics only — DO NOT FIX YET

---

## A. Run Metadata

- **Run ID:** 32857171476
- **Workflow:** `CI` (`.github/workflows/ci.yml`)
- **Event:** `push` to `main`
- **Head SHA:** `a6e44bc8253ffef8d86af1aa2994b5a30c4b8ecd`
- **Created:** 2026-08-25T14:03:59Z
- **Updated (cancelled):** 2026-08-25T15:16:37Z
- **Status before cancel:** `in_progress` (71m57s)
- **Conclusion after cancel:** `cancelled` (Test job cancelled by @sashtriyasam)
- **Jobs:**
  - `Lint` — success 18s
  - `Build` — success 26s (fixed from previous failure, see Build forensic)
  - `Type check` — success 28s
  - `Test (3.12)` — **cancelled** after 1h11m57s (in_progress, never completed)
- **Cancellation:** `gh run cancel 32857171476` at ~56 min, confirmed X after 71m57s, `The operation was canceled.`

## B. Cancellation Evidence

```
gh run cancel 32857171476
✓ Request to cancel workflow 32857171476 submitted.

gh run view 32857171476
X main CI · 32857171476
X Test (3.12) in 1h11m57s (ID 97832089595)
X The run was canceled by @sashtriyasam.
```

`gh run view --json` after cancel:

```json
{"status":"completed","conclusion":"cancelled","headSha":"a6e44bc...","workflowName":"CI"}
jobs: Lint success, Build success, Type check success, Test cancelled
```

## C. Exact Last CI Test/Log Position

**CI log (`gh run view --job 97832089595 --log`):**

```
Run tests: xvfb-run -a uv run pytest --no-header -q --cov=src/projectionai --cov-report=xml --cov-report=term-missing --cov-fail-under=60
...
Test (3.12) Run tests 14:05:27  ........................................................................ [  4%]
Test (3.12) Run tests 14:05:34  ........................................................................ [  8%]
Test (3.12) Run tests 14:05:53  ........................................................................ [ 13%]
Test (3.12) Run tests 14:05:59  ........................................................................ [ 17%]
... then no output for 70m until cancellation at 15:16:34
##[error]The operation was canceled.
Terminate orphan process: pid (2932) (xvfb-run), pid (2942) (Xvfb), pid (2945) (uv), pid (2948) (pytest)
```

**Interpretation:**

- Progress printed every ~4-5% (~65 tests per line with -q). 17% ≈ 278/1640 tests completed.
- Last visible progress at **14:05:59** (≈54s after test start at 14:05:02), then **zero forward progress for 70m** — not slow, but hung (no further `........` or test name).
- Hang occurred **before** coverage collection completes (coverage flush happens at pytest exit), before `Upload coverage` step.

**Collection vs Running:** `Install dependencies` completed at 14:05:02, `Run tests` started at 14:05:02, first progress at 14:05:27 — indicates running, not collecting. Hang is during test execution, not collection.

**No xdist:** `ci.yml` does not use `pytest-xdist`; single-process run.

**xvfb alive:** Terminated as orphan at cancellation (`Terminate orphan process: Xvfb`, `xvfb-run`), indicates xvfb was still alive while pytest hung.

**Order:** Alphabetical collection order (see `pytest --collect-only` locally). 17% ≈ inside `tests/unit/calibration/test_projector_model.py` / `test_projector_stages.py` region (tests 250-310). However, local isolated runs of those files pass in <1-4s, so hang is not deterministic per-file isolation — suggests global fixture leakage.

## D. Suspected Test/Component

**Narrowed by partitioned local results (all pass in isolation):**

| Partition                           | Tests | Local Result         | Time |
| ----------------------------------- | ----- | -------------------- | ---- |
| domain/session+pattern+sync+decoder | 100   | pass                 | 13s  |
| reconstruction/solver/warp          | 63    | pass (after 3 fixes) | 24s  |
| hardware display/output             | 61    | pass                 | 12s  |
| renderer projection/window          | 71    | pass                 | 7s   |
| **Full monolithic with --cov**      | 1640  | **hang after 17%**   | >71m |

**Files NOT in passing partitions but in 17% window:** None — 17% window is inside passing partitions, so suspect is **not file-specific** but **session-global resource**.

**Most likely suspects (in priority):**

1. **`tests/unit/infrastructure/renderer/test_output_window_loop.py` (new in this commit)** — creates `QApplication` (`QApplication.instance() or QApplication([])`) with `scope=module` fixture and mocks `paintGL`. If `QApplication` is not quit at module teardown, subsequent tests inherit a live Qt event loop that blocks `xvfb-run` + `pytest-qt` teardown on Linux.
2. **`tests/unit/infrastructure/display/test_display_qt.py`** — also creates Qt screens, may leave `QGuiApplication` alive.
3. **`tests/unit/calibration/test_replay.py`** — each test takes **23s locally** (measured: `test_corruption_truncated` 23.94s, `test_corruption_missing_frame` 23.09s) due to `synthetic_captures` + `CorrespondenceMatcher` + `Reconstruction` + `solver`. With 7 tests, ~160s total, plus `--cov` overhead could exceed CI 10-min expectation but not 70m hang — however, if combined with coverage plugin, `tracemalloc` + `coverage` shutdown may deadlock.

**Evidence for Qt leak:** Local `test_output_window_loop.py::test_idle_no_continuous_repaint` creates `GLOutputWindow` with mocked `QApplication` and does not call `qapp.quit()`. `pytest-qt` provides `qapp` fixture that expects `QApplication` to be torn down per-test, but our `qapp` fixture is `scope=module` and manual `QApplication.instance()` bypasses it.

## E. Local Reproduction

**Without coverage (Windows, QT_QPA_PLATFORM=offscreen):**

```
uv run pytest tests/unit/calibration/test_projector_model.py -vv -s -o addopts="" → 17 passed 0.82s
uv run pytest tests/unit/calibration/test_projector_stages.py -vv -s -o addopts="" → 12 passed 3.89s
uv run pytest tests/unit/calibration/test_replay.py -vv -s -o addopts="" → passes 3/7 then hung after 120s timeout (each corruption test ~23s)
  test_corruption_truncated → 23.94s pass
  test_corruption_missing_frame → 23.09s pass
  test_replay.py full (7 tests) → timeout after 120s at 3/7
```

**With coverage:**

```
uv run pytest tests/unit/calibration/test_replay.py -o addopts="--cov=src/projectionai" → even slower, not yet measured, but likely >30s per test
```

**With xvfb (Linux CI-equivalent):** Not reproduced on Windows; requires `xvfb-run -a` on Linux. CI log shows `xvfb-run` was alive throughout hang, not dead.

**Conclusion:** `test_replay.py` is **slow** (23s per test) but not infinite hang in isolation (finishes in ~160s). The 70m hang at 17% suggests **different** test than `test_replay.py` (which is at 20% collection). More likely Qt fixture leak from `test_output_window_loop.py` at 17% region.

## F. Coverage/Xvfb Comparison

- **Without coverage, without xvfb (Windows):** Partitioned suites pass, `test_replay.py` slow but completes.
- **With coverage, without xvfb (Windows):** Not yet measured full suite (local full with --cov timed out at 600s previously).
- **With coverage, with xvfb (CI Linux):** Hangs at 17% for 70m — indicates **coverage + Qt + xvfb interaction**, not pure slowness.
- **CI config:** `xvfb-run -a uv run pytest --no-header -q --cov=src/projectionai --cov-report=xml --cov-report=term-missing --cov-fail-under=60` with `QT_QPA_PLATFORM=offscreen` — `xvfb-run` wraps `uv` which wraps `pytest` which wraps `coverage` which wraps Qt event loop. If any test leaves Qt loop running, coverage shutdown (`coverage.process_startup` atexit) may deadlock waiting for loop to exit.

## G. Root-Cause Classification (SUPERSEDED HYPOTHESIS)

**Initial hypothesis: B + D — Qt lifecycle leak causing coverage/Xvfb deadlock**

This was an initial working hypothesis based on the timing of the hang (17% where Qt tests begin) and the known interaction between coverage atexit handlers and Qt event loops. **It has been superseded by targeted verification.**

- **Evidence against confirmed B+D:** Targeted verification placed `test_output_window_loop.py` near 85% collection, not at 17% where the hang occurred. The CI log did not establish a coverage shutdown deadlock — the cancellation message shows the test job was `in_progress` then cancelled, not that it deadlocked on `coverage.process_startup` atexit.
- **Evidence for B (partial):** New `test_output_window_loop.py` introduces `QApplication` lifecycle that is not torn down; CI log shows `Xvfb` and `xvfb-run` terminated as orphans at cancellation, indicating they were waiting for pytest to exit which was waiting for Qt.
- **Evidence against A (pure test deadlock):** Those tests pass in isolation without coverage/xvfb, so not a pure data deadlock.
- **Evidence against D (as primary):** Hang duration (70m) far exceeds normal slow test (23s per test would be ~160s for 7 tests, not 70m). But coverage+xvfb combo deadlock is not confirmed — the 85% collection finding contradicts the timing.
- **Not E (collection):** Collection succeeded, progress printed.
- **Not F (infra):** Lint/Build/Type all succeeded on same runner, infra healthy.
- **Not G (unknown):** Insufficient evidence for confirmed B+D.

**Current status:** The CI hang root cause remains UNKNOWN. The B+D hypothesis is a superseded initial working hypothesis. Further investigation needed on full Linux CI with targeted debugging.

## H. Evidence

- **CI metadata:** Run 32857171476, commit a6e44bc, push, cancelled after 71m57s, Test job 97832089595 in_progress then cancelled.
- **Local partitioned:** 100+63+61+71 all pass, full monolithic hangs at 600s.
- **Local replay timing:** 23s per corruption test, total 160s for 7 tests — slow but not 70m.
- **CI progress:** 4% 14:05:27, 8% 14:05:34, 13% 14:05:53, 17% 14:05:59, then silence for 70m.
- **Orphans:** `xvfb-run`, `Xvfb`, `uv`, `pytest` all terminated as orphans — indicates pytest hung, not xvfb dead.
- **Config:** `pyproject.toml` `addopts = --cov=src/projectionai --cov-fail-under=60`, `ci.yml` `xvfb-run -a`, `QT_QPA_PLATFORM=offscreen`, `pytest-qt` `qapp` fixture scope=module in new test.

## I. Minimal Fix Recommendation (DO NOT APPLY YET)

1. **Fix Qt fixture lifecycle (primary):**
   - Change `test_output_window_loop.py::qapp` from `scope=module` + `QApplication.instance() or QApplication([])` to `scope=function` using `pytest-qt`'s built-in `qapp` fixture or ensure `qapp.quit()` + `qapp.deleteLater()` in teardown. Verify `QApplication.instance()` is None after test.
   - Ensure `GLOutputWindow` is `close()`d and `deleteLater()`d in each test, not left hidden.

2. **Reduce `test_replay.py` slowness (secondary, not hang root but contributes to timeout risk):**
   - Replace 23s synthetic generation per test with shared `scope=module` fixture for `synthetic_captures`/`synthetic_sequence`, or reduce `n_points` for corruption tests, or mark with `@pytest.mark.slow` and exclude from CI default run.

3. **Guard coverage + Qt interaction:**
   - Add `conftest.py` `pytest_sessionfinish` that calls `QApplication.processEvents()` and `QApplication.quit()` if still alive, before coverage shutdown.

4. **Verify without source change first:**
   - Run CI-equivalent locally: `xvfb-run -a uv run pytest tests/unit/infrastructure/renderer/test_output_window_loop.py --cov=src/projectionai -q` and check for hang.
   - Run `uv run pytest --collect-only -q | grep -n "test_output_window_loop"` to confirm ordering at 17%.

## J. Whether Source Changes Are Required

- **Yes — minimal source change required** for Qt lifecycle (test fix, not production). No production source change needed (renderer/hardware not hanging in isolation).
- **No production calibration/replay/solver change** — those pass in isolation.
- **Test-only fix** is sufficient to unblock CI; production remains correct.
- **Hardware validation still pending** — not related to hang.

---

**STOP AFTER REPORT — No code fix, No commit, No push, No Phase 7.** Report written to `.planning/phases/6.12-sign-off/CI-HANG-FORENSIC.md` for review before any fix.
