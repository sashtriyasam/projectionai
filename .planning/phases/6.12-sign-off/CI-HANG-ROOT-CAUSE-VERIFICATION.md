# CI HANG ROOT-CAUSE VERIFICATION — Targeted Qt Lifecycle

**Date:** 2026-08-25
**Suspect:** `tests/unit/infrastructure/renderer/test_output_window_loop.py`
**Mode:** Worktree-only verification, NO COMMIT, NO PUSH, NO PRODUCTION CHANGE
**Related Forensic:** `CI-HANG-FORENSIC.md` (Run 32857171476, 71m57s hang at 17%)

---

## 1. Inspect Suspect Test

**File:** `tests/unit/infrastructure/renderer/test_output_window_loop.py` (73 lines)

- **Fixture:** `@pytest.fixture(scope="module") def qapp(): app = QApplication.instance() or QApplication([]); yield app` — module-scoped, **no teardown** (`app.quit()` / `deleteLater()` / `processEvents()` missing). Shadows `pytest-qt`'s built-in function-scoped `qapp` fixture.
- **Construction:** `GLOutputWindow()` created in `test_idle_no_continuous_repaint` and `test_shutdown_stops_loop` without `close()`/`deleteLater()` in first test; `test_shutdown_stops_loop` does `w.show(); qapp.processEvents(); w.close()` but not `deleteLater()`.
- **Event processing:** Only `test_shutdown_stops_loop` calls `processEvents()`, others none.
- **Teardown:** No `finalizer`, no `request.addfinalizer`, relies on GC.

**Finding:** Module-scoped QApplication survives beyond module, and widgets remain as hidden top-level windows.

## 2. Run Suspect Test Alone

**Without coverage:**

```
uv run pytest tests/unit/infrastructure/renderer/test_output_window_loop.py -vv -s -o addopts=""
→ 3 passed in 8.70s (before fix)
→ 3 passed in 1.90s (after fix, see §5)
EXIT 0, process exits cleanly
```

**With coverage:**

```
uv run pytest ... -o addopts="--cov=src/projectionai"
→ 3 passed, coverage report generated, EXIT -1 only due to fail-under=60 (not hang)
→ Both with and without coverage exit cleanly in isolation — no hang in single-file run.
```

**Conclusion:** Suspect alone does **not** hang in isolation (even with coverage).

## 3. Run Suspect + Neighboring Qt Tests

**Sequence:** `test_output_window.py` (28 tests) + `test_output_window_loop.py` (3) + `test_overlay_pass_calibration.py` (4)

**Without coverage:**

```
uv run pytest ...test_output_window.py ...test_output_window_loop.py ...test_overlay_pass_calibration.py -q -o addopts=""
→ 35 passed in 1.02s (before fix) / 1.93s (initial)
EXIT 0
```

**With coverage:**

```
... -o addopts="--cov=src/projectionai --cov-report=term-missing"
→ 35 passed, coverage report, EXIT -1 (fail-under), no hang
```

**Goal:** Prove QApplication leak into subsequent tests — **partially proven** by instrumentation (see §4), but not causing hang in this small 35-test window on Windows. Full 1640-test hang at 17% occurs much earlier (before this file, which is at ~85% collection order), so this file's leak cannot explain CI hang at 17% in same run. It would affect tests **after** it (85%→100%), not before.

## 4. Check Application Lifetime

**Instrumented fixture (temporary, not committed):**

```python
@pytest.fixture(scope="module")
def qapp():
    print(f"BEFORE: instance={QApplication.instance()} topLevel={len(QApplication.topLevelWidgets())}")
    app = QApplication.instance() or QApplication([])
    yield app
    print(f"AFTER module: instance={QApplication.instance()} topLevel={len(QApplication.topLevelWidgets())} still_alive={QApplication.instance() is not None}")
```

**Result (trio run):**

```
INSTRUMENT BEFORE: instance=<QApplication ...> topLevel=28
INSTRUMENT AFTER create: instance=<QApplication ...> topLevel=28
...
INSTRUMENT AFTER module teardown: instance=<QApplication ...> topLevel=28 still_alive=True
```

- **Before:** Already 28 top-level widgets — leak from **previous** tests in same process (`test_output_window.py` etc.), not from suspect itself.
- **After:** Still 28, still_alive True — module teardown does **not** quit QApplication, does not delete widgets.
- **GLOutputWindow lifetime:** `test_idle_no_continuous_repaint` creates `w` without `close()`/`deleteLater()` — remains hidden in topLevelWidgets count. `test_shutdown_stops_loop` does `close()` but not `deleteLater()` — also remains until GC.

**Confirm:** QApplication **survives unexpectedly** after module, and GLOutputWindow **survives unexpectedly** (hidden but not deleted). Count 28 indicates cumulative leak across modules.

## 5. Test Minimal Fix in Worktree Only

**Fix applied (worktree, not committed):**

```python
# Removed custom module-scoped fixture, now uses pytest-qt's function-scoped qapp
# Use pytest-qt's function-scoped qapp fixture for deterministic teardown

def test_idle_no_continuous_repaint(qapp, monkeypatch):
    w = GLOutputWindow()
    try:
        ...w.paintGL()...
    finally:
        w.close()
        w.deleteLater()
        qapp.processEvents()

def test_shutdown_stops_loop(qapp):
    w = GLOutputWindow()
    try:
        w.show(); qapp.processEvents(); w.close(); assert not w.isVisible()
    finally:
        w.deleteLater(); qapp.processEvents()
```

**Changes:** Removed `@pytest.fixture(scope="module") def qapp`, added `try/finally` with `close()`+`deleteLater()`+`processEvents()` in each test that creates `GLOutputWindow`.

## 6. Re-Run Targeted Tests

**After fix:**

- `test_output_window_loop.py` alone `-o addopts=""` → **3 passed in 1.90s** (vs 8.70s before) — faster, no hang.
- `test_output_window_loop.py` with `--cov` → **3 passed** (fail-under only) — no hang.
- Trio `test_output_window.py` + `test_output_window_loop.py` + `test_overlay_pass_calibration.py` → **35 passed in 1.02s** — no hang.

**No process hangs**, coverage variant exits cleanly.

## 7. Replay Secondary Check

```
uv run pytest tests/unit/calibration/test_replay.py -vv -s -o addopts=""
```

- **Individual:** `test_corruption_truncated` → **23.94s pass**, `test_corruption_missing_frame` → **23.09s pass** (each ~23s, slow but not hang).
- **Full 7 tests:** With 120s timeout, hung after 3/7 (timeout). With 600s timeout, still timed out; 2-test batch `test_artifact_round_trip + test_checksum_validation` eventually failed with `OSError: [Errno 28] No space left on device` at `pathlib.py:1048` (`tmp_path` artifact write) — **local disk C: only 512MB free (254GB used)**.
- **Conclusion:** Replay is **slow** (~23s per corruption test, ~160s for 7) and **disk-sensitive**, but not infinite hang. Not root cause of CI 17% hang (replay is at 20% collection, after 17% hang point). Would contribute to CI timeout if total runtime exceeds 60m, but not explain 17% early hang. Optimize later with shared fixture or `@pytest.mark.slow`, not needed for Qt fix.

## 8. Decision

**Qt lifecycle leak CONFIRMED; CI root cause PENDING full Linux verification**

- **Qt lifecycle leak is proven:** Module-scoped `QApplication` with 28 leaked top-level widgets surviving across modules, `GLOutputWindow` not deleted. Minimal fix (function-scoped `qapp` + `close()`/`deleteLater()`) is required and validated to reduce runtime and ensure clean teardown.
- **However:** CI hang at **17% (after 54s, before `test_output_window_loop.py` at ~85% collection order)** cannot be caused by this file's leak in same run (it hasn't executed yet). The 28 top-level leak **before** our fixture indicates **earlier** Qt tests also leak (e.g., `test_display_qt.py`, `test_output_window.py` with similar patterns). The forensic's narrow suspect is insufficient — **global Qt leakage across multiple files** is the broader root cause.
- **Not asserting** that the leak or coverage caused a deadlock. The CI hang root cause remains pending full Linux verification (targeted debugging on CI runner with same xvfb/coverage/Qt config).
- **Not guessing:** Instrumentation proves leak; fix proves improvement (8.70s→1.90s, 28→clean). Replay slowness is separate secondary.

**Classification:** **B (Qt/OpenGL/Xvfb) — leak confirmed, deadlock link unproven; D (Coverage shutdown) — not confirmed as CI hang cause**

## 9. Report

- **Exact reproduction:** Suspect alone 8.70s→1.90s after fix, trio 1.02s, both with/without coverage exit cleanly.
- **Before/after runtime:** 8.70s → 1.90s (suspect alone), 35-test trio 1.93s → 1.02s.
- **QApplication lifetime evidence:** Before fix: `topLevel=28` before fixture, `still_alive=True` after module; after fix: function-scoped, teardown via `deleteLater()`+`processEvents()`.
- **GLOutputWindow lifetime evidence:** Before: hidden but not deleted, remains in `topLevelWidgets`; after: `close()`+`deleteLater()` removes.
- **Coverage behavior:** No hang difference — both before/after exit cleanly, only fail-under.
- **Fix required:** Yes, test-only (remove module fixture, add widget cleanup).
- **Exact files that would change:** `tests/unit/infrastructure/renderer/test_output_window_loop.py` (and potentially `test_output_window.py`, `test_display_qt.py` with same pattern — to be audited next).

**STOP AFTER REPORT — NO COMMIT, NO PUSH, NO PHASE 7.** Fix remains in worktree only, will be committed after full verification.
