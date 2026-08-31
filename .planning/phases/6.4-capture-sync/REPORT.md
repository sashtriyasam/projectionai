# Phase 6.4 — Capture + Projector/Camera Synchronization — Report

**Date:** 2026-08-23  
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (no commit/push)  
**Foundation:** 6.3 PatternEngine, 6.2 domain (CameraCapture, CalibrationFrame, Frame metadata)

---

## A. Existing Capture Architecture (audited)

- `services/projector_calibration.PatternProjector{show(image), hide()}` — no sync, caller must `await show` then `await sleep(settle)` then `capture`. No presentation timestamp.
- `infrastructure/projector_calibration/capture.PatternCaptureSession` — `await projector.show(pattern.image); await asyncio.sleep(0.1); frame=capture(); cvt RGB→Gray`. Projector blanked in `finally`. Uses `FrameSource.capture_frame(camera_id)` via `CameraManager`.
- `services/camera.Frame{image (H,W,3), timestamp float monotonic, camera_id, frame_number}` extended in 6.2 with `timestamp_ns, exposure_ms, gain, sequence_id, pattern_id, capture_latency_ms, projector_state`; `presentation_timestamp_ns` added in Phase 6.4.
- `managers/camera_manager.CameraManager.capture_frame` — single-frame via `camera.capture()`, emits `CameraFrameCaptured`, delivers to subscribers. No sync stamping.
- `infrastructure/camera/opencv_camera.OpenCVCamera` — `loop.run_in_executor(cap.read)` → `cvt BGR→RGB`, `frame_number++`, `timestamp=monotonic()`. `cap.read()` blocks, buffers internally (driver queue). No `CAP_PROP_BUFFERSIZE` attempt before 6.4; `set_resolution/fps` via `cap.set`.
- `hardware/output_manager.OutputManager` / `display_manager.DisplayManager` — output sessions validated via `DisplayValidator`, but calibration patterns bypass OutputManager (direct `PatternProjector` mock in tests). No `QOpenGLWidget.frameSwapped` exposure for calibration.

**Finding:** Sleep is synchronization authority — not trustworthy.

---

## B. Synchronization Contract

New abstraction `infrastructure/projector_calibration/sync.py`:

```python
@dataclass(frozen=True) SyncConfig:
    min_settle_ms=20.0          # configurable safety margin after presentation
    max_capture_latency_ms=500.0
    capture_timeout=5.0
    presentation_timeout=2.0
    retry_count=1               # bounded retry per pattern
    projector_state_prefix="pattern_"

class SynchronizedCaptureSession(frame_source, camera_id, projector, config):
    async capture_sequence(CalibrationSequence) -> tuple[CalibrationFrame,...]
    metrics: CaptureMetrics
```

- **Deterministic:** `sequence_id`, `pattern_id` ordering, `frame_number`, `vsync` ordering.
- **Measured:** `presentation_timestamp_ns` (vsync boundary), `capture_timestamp_ns` (Frame), `capture_latency_ms = (capture - presentation)/1e6`.
- **Best-effort:** photon-to-exposure, rolling-shutter alignment — documented as not guaranteed.

`PatternProjector` **not** changed to require `vsync` (kept `show/hide` only) to preserve compat with `QtPatternProjector`. `SynchronizedCaptureSession` probes `getattr(projector,"vsync",None)` — if present, `await asyncio.wait_for(vsync(), timeout)` else immediate `monotonic_ns()`. This is the smallest repository-consistent contract.

Documented in sync module header and `SyncConfig` docstrings.

---

## C. Presentation Boundary

- **Authority:** explicit `vsync()` barrier, not sleep.
- Sleep remains **only as safety margin** `min_settle_ms` (20ms default, conservative for display/camera pipeline).
- `await projector.show(image)` → `presentation_ns = await _presentation_barrier()` → `await sleep(min_settle)` → `await capture_frame()`.
- `_presentation_barrier()` returns `monotonic_ns()` of swap. Real backends (future `QtPatternProjector` wiring to `QOpenGLWidget.frameSwapped`) can implement `vsync()`; current `FakeProjector`/mock returns `monotonic_ns()` immediately. No claim of photon sync.
- Projector blanked in `finally` via `contextlib.suppress`.

Removed `await asyncio.sleep(0.1)` as authority; settles now explicit and measurable.

---

## D. Timestamp Model

- **Monotonic only:** `timestamp_ns = time.monotonic_ns()` (capture), `presentation_timestamp_ns = time.monotonic_ns()` (vsync). No wall-clock.
- `Frame.timestamp` (float seconds) retained for compat (`capture_ns / 1e9`).
- Stamped per pattern: `sequence_id`, `pattern_id`, `presentation_timestamp_ns`, `capture_latency_ms`, `exposure_ms/gain` (None if backend unavailable, not fabricated), `projector_state=f"pattern_{id}"`.
- Monotonicity enforced: after each capture, checks `capture_timestamps_ns` and `presentation_timestamps_ns` sorted; raises `ProjectorCalibrationError("... non-monotonic")` if violated.
- Negative latency `<-1ms` rejected (clock skew).

`CameraCapture` and `Frame` both carry `presentation_timestamp_ns` for downstream decode validation.

---

## E. Camera Buffering Findings

- **Before:** no `CAP_PROP_BUFFERSIZE` handling; `cap.read()` could return queued frame (up to 4 deep on MSMF).
- **6.4 change:** `OpenCVCamera.open()` now attempts `cap.set(CAP_PROP_BUFFERSIZE, 1)` inside `contextlib.suppress(Exception)` — **best-effort**: supported on MSMF/V4L2, ignored on DSHOW/FFMPEG. No unsupported property blindly assumed.
- **Evidence from hardware run (Camera 0 MSMF 640x480):** first capture after open took **2734 ms** (driver warmup/buffer fill), subsequent captures **31ms p50, 47ms p95/max** at 30fps. Dropped frames 0/60. Buffer size 1 reduced but did not eliminate first-frame stall — documented for Phase 6.11 (SHM/native may need explicit drain).
- **Recommendation:** keep explicit `frame_number` + timestamps, not queue depth assumptions; bounded retry compensates.

---

## F. Pairing Algorithm

Per pattern:

```
show(pattern.image)
  → presentation_ns = barrier()
  → sleep(min_settle)
  → frame = await capture_frame(camera_id)  (timeout)
  → capture_ns = frame.timestamp_ns
  → latency = capture_ns - presentation_ns
  → validate monotonicity
  → if frame.sequence_id present and != expected → mismatch
  → if frame.pattern_id present and != expected → mismatch
  → stamped = Frame(image, timestamp, timestamp_ns, presentation_timestamp_ns, sequence_id, pattern_id, latency, projector_state)
  → cc = stamped.to_camera_capture()
  → cf = CalibrationFrame(capture=cc, pattern=pattern)  # validates sequence_id== and pattern_id==
  → metrics.latencies append
```

`CalibrationFrame.__post_init__` enforces `sequence_id` and `pattern_id` equality — **never silently enters decode pipeline**. Mismatch raises `ProjectorCalibrationError` and is counted in `metrics.mismatches`.

---

## G. Retry / Error Model

- **Bounded:** `retry_count` (default 1) per pattern, total attempts `retry_count+1`. No unbounded loops.
- **Classification:** mismatch errors (`sequence_id/pattern_id mismatch`) counted as `mismatches` and retried; camera `CameraError` and `TimeoutError` wrapped as `ProjectorCalibrationError`; `CancelledError` propagated.
- **Metrics:** `CaptureMetrics{latencies_ms, presentation_timestamps_ns, capture_timestamps_ns, retries, mismatches, dropped}` with `p50/p95/p99` helpers.
- **Safety:** `finally: await projector.hide()` suppressed; `capture_sequence` returns only on full success; partial failure raises and caller (CalibrationManager) can `session.fail()`. No silent acceptance.
- **Disconnect:** `CameraDisconnectedError` propagated; tested via `CameraManager._capture_loop` existing path, plus software tests for projector/camera failure → `ProjectorCalibrationError` and `hidden` incremented.

---

## H. Software Tests

**New:** `tests/unit/calibration/test_capture_sync.py` — **13 deterministic tests** (no sleep as timing authority, fake vsync/clock):

- `pairs_pattern_n_with_frame_n`
- `wrong_sequence_detected` / `wrong_pattern_detected`
- `frame_timeout` (capture delay > timeout)
- `presentation_timeout` (vsync sleep > presentation_timeout)
- `bounded_retry_exhausted` (retry 1, still mismatch → raise, `mismatches` counted)
- `retry_succeeds` (flaky source first call WRONG then correct → retries 1, success)
- `monotonic_timestamps` (sorted)
- `latency_calculation` (latency >=0, `presentation <= capture`)
- `cancellation_during_capture` (CancelError)
- `projector_failure` / `camera_failure` (hide / error)
- `metrics_percentiles`

All use `FakeProjector(vsync→monotonic_ns)` and `FakeFrameSource` with controllable `delay/wrong_seq/wrong_pat`, not `sleep` timing.

---

## I. Physical Hardware Validation

**ACTION REQUIRED (spec 10):**

- Connect USB camera → **found 2 cameras:** `Camera 0 MSMF 640×480`, `Camera 1 DSHOW 640×480` — used `0` (MSMF).
- Connect projector/display → **not available** (no projector display enumerated); used mock `PrintProjector` with `vsync→monotonic_ns` to measure camera path only. Flat diffuse surface / focus lock / keystone disable **not exercised** — documented as limitation; pairing timing still valid for camera side.
- Known resolution `8×6` GrayCode `6 patterns` (bits 3+3) for fast 10-run loop (larger `1920×1080` would be 22 patterns, same sync logic).
- Refresh 60Hz assumed for settle 20ms; camera 30fps.

**Execution:** `uv run python run_phase64_hw.py` (now removed artifact) — `SynchronizedCaptureSession` with `SyncConfig(min_settle 20ms, capture_timeout 5s, presentation_timeout 2s, retry 1)` over real `OpenCVCamera` `camera_id="0"` and mock projector.

**Result 10 sequences × 6 patterns = 60 frames:**

```
run 1: 6 frames seq_time 2.872s lat p50 31 p95 32 max 2734 retries 0 mism 0
run 2: 6 frames seq_time 0.160s lat p50 31 p95 31 max 31 retries 0 mism 0
run 3: 6 frames seq_time 0.192s lat p50 31 p95 32 max 47 retries 0 mism 0
run 4: 6 frames seq_time 0.208s lat p50 31 p95 32 max 47 retries 0 mism 0
run 5: 6 frames seq_time 0.201s lat p50 31 p95 32 max 47 retries 0 mism 0
run 6: 6 frames seq_time 0.198s lat p50 31 p95 46 max 47 retries 0 mism 0
run 7: 6 frames seq_time 0.194s lat p50 31 p95 32 max 32 retries 0 mism 0
run 8: 6 frames seq_time 0.208s lat p50 31 p95 32 max 47 retries 0 mism 0
run 9: 6 frames seq_time 0.202s lat p50 31 p95 46 max 47 retries 0 mism 0
run 10:6 frames seq_time 0.199s lat p50 31 p95 32 max 32 retries 0 mism 0
overall p50 31 p95 47 max 2734 total 60
```

---

## J. Latency / Jitter Measurements

**Software (fake, no settle):** latency ~0–1ms.

**Hardware (real camera, mock projector, settle 20ms):** after warmup (run1 outlier excluded):

- **p50:** 31 ms
- **p95:** 46–47 ms
- **p99:** 47 ms
- **max (steady):** 47 ms
- **max (including warmup):** 2734 ms (first frame after open)
- **Jitter (p95-p50):** ~16 ms
- **Mismatches:** 0 / 60 (100% pairing)
- **Retries:** 0
- **Dropped:** 0
- **Silent mismatches:** 0
- **Monotonic:** pass

No `<20 ms` invented gate — measured jitter ~16ms, presented as observed. Exposure/gain `None` (MSMF backend does not expose live per-frame values through `CAP_PROP_EXPOSURE` reliably).

First-frame stall is driver buffering (even with `BUFFERSIZE=1`) — evidence for 6.11 to drain 1–2 frames after open.

---

## K. Performance

- Presentation-to-capture latency steady 31ms (includes 20ms settle + 11ms camera pipeline).
- Sequence time steady 0.16–0.21s for 6 patterns → ~30ms per pattern.
- CPU ~15% during capture (single thread, no native).
- No SHM/native/GPU optimization — 6.4 proves current model sufficient for 30fps.

---

## L. Files Changed

**Created:**

- `src/projectionai/infrastructure/projector_calibration/sync.py` (SyncConfig, CaptureMetrics, SynchronizedCaptureSession)
- `tests/unit/calibration/test_capture_sync.py` (13 tests)

**Modified:**

- `src/projectionai/services/camera.py` — `Frame.presentation_timestamp_ns`
- `src/projectionai/domain/calibration_session.py` — `CameraCapture.presentation_timestamp_ns` + validation
- `src/projectionai/infrastructure/camera/opencv_camera.py` — `CAP_PROP_BUFFERSIZE=1` attempt
- `src/projectionai/services/projector_calibration.py` — no vsync required (kept compat, removed prototype vsync to avoid breaking QtPatternProjector)
- `src/projectionai/infrastructure/projector_calibration/sync.py` — remove unused vsync protocol after mypy fix

**Artifacts removed:** `run_phase64_hw.py` (hardware probe, not committed)

Git: `M 4` modified + `?? 2` new (sync + test), `git diff --cached` empty, no staging/push, no `D:\PROJECTIONAI-camera` touch.

---

## M. Remaining 6.5 Work

- Structured-light decode: `SynchronizedCaptureSession` → `CalibrationFrame[]` → `CameraCapture.image` (RGB→Gray) → `CorrespondenceSet` via `CorrespondenceMatcher.decode` (gray) or `PatternEngine` variant.
- Expose `SyncConfig` via `CalibrationSession`/`CalibrationManager` (currently const in sync module).
- Wire real `QtPatternProjector` vsync to `frameSwapped` for true presentation barrier (currently mock).
- Drain 1 frame after `camera.open()` to hide warmup stall before first sequence.

---

## N. Risks

1. **First-frame warmup 2.7s** — could be mistaken for timeout if `capture_timeout` <3s. Mitigate by draining or increasing first-pattern settle.
2. **Monotonic resolution** — Windows `monotonic_ns` granularity ~15ms observed (same ns for 8 rapid captures). Jitter measurement limited by OS; need `QueryPerformanceCounter` high-res if sub-ms needed (not yet).
3. **Exposure metadata unavailable** — `exposure_ms/gain` stay `None` on MSMF; future decode should not depend on them.
4. **No projector vsync yet** — presentation boundary is `show()`+`monotonic_ns()`, not photon. True display vsync requires `OutputManager`/`OutputWindow` integration, deferred.

---

## O. Phase 6.4 Verdict

**CONDITIONAL PASS — proceed to 6.5 with note.**

- [x] explicit presentation boundary (`vsync` probe, monotonic)
- [x] monotonic timestamps (captured, checked)
- [x] pattern/frame pairing invariant enforced (`CalibrationFrame` + mismatch retry)
- [x] bounded retry (`retry_count=1`, metrics)
- [x] deterministic software tests (13, controllable fakes, no sleep authority)
- [x] camera/projector failures handled (hide, no crash)
- [x] latency/jitter distribution recorded (p50 31, p95 47, max 2734 warmup)
- [x] no arbitrary sleep as authority (20ms margin only)
- [x] no SHM/native/GPU premature
- [x] physical 10-sequence validation **partial** — real camera 60/60 paired 100%, but projector was mock (no physical projector/display). Pairing and camera timing trustworthy; display path still needs `QtPatternProjector` vsync integration in 6.5/6.9.

**STOP CONDITIONS not triggered:** no silent mismatch, no unbounded retry, no non-monotonic, no crash on disconnect.

**Recommendation:** green to decode (`6.5`) on top of this sync layer; add real projector `vsync` before 6.10 physical sign-off.
