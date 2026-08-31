# Phase 6.2 — Calibration Domain + Session Lifecycle — Report

**Date:** 2026-08-23  
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (no commit)  
**Scope:** `DO NOT COMMIT / PUSH / MERGE` — implementation only

---

## A. Canonical CalibrationResult Decision

**Problem:** 3 competing models:

1. `domain/calibration.py:CalibrationResult` (frozen, `object_pose + projectors: tuple[ProjectorCalibration]`, used by `services/calibration.py:calibration_to_warp_mesh`)
2. `calibration/types.py:CalibrationResult` (mutable `success + data: CalibrationData` dict-of-dicts, used by `calibration_manager`, `exporter`, `importer`, `history`)
3. `services/projector_calibration.py:ProjectorCalibrationResult` (frozen, `projector_intrinsics 3x3 + projector_pose 4x4 + coverage + per_point_errors`, produced by GrayCode MVP)

**Decision:** Canonical is **`domain/calibration_session.py:CalibrationResult`** (frozen, immutable, domain-owned).

```python
@dataclass(frozen=True, eq=False)
class CalibrationResult:
    calibration_id, sequence_id, method, projector_id, camera_id, surface_id,
    projector_intrinsics (3,3), projector_pose (4,4), projector_resolution,
    reprojection_error, coverage, num_correspondences, confidence,
    per_point_errors, camera_matrix?, distortion_coeffs?, image_size?,
    warp_mesh?, object_pose?, created_at, metadata
```

**Rationale:**

- Domain-owned, framework-independent (no Qt/OpenCV/ModernGL/pybind11).
- Carries validated state needed downstream (intrinsics+pose+warp_mesh) — unlike `types.CalibrationResult` which wraps dicts.
- Frozen + numpy `array_equal` semantics, matches `WarpMesh`/`Pose` style.
- Buffer-protocol friendly (`ndarray` contiguous) for future SHM/native zero-copy (Phase 6.11).
- Reuses existing fields (`reprojection_error`, `confidence`, `coverage`, `projector_pose`) — no fourth representation.

**Migration (no silent break):**

- `domain/calibration.py` retained, now bridges: `CalibrationResult.to_canonical()` / `from_canonical()` (uses `fov→fx` via `fx=(W/2)/tan(FOV/2)`).
- `services/projector_calibration.ProjectorCalibrationResult.to_canonical()` added.
- `calibration/types.calibration_result_to_canonical()` / `canonical_to_legacy_result()` added.
- `services/calibration.calibration_to_warp_mesh` now dispatches: `if hasattr(calibration,"projector_intrinsics")` → `_canonical_to_warp_mesh()` else legacy FOV path. Both paths validated via `WarpMesh.validate()`.
- `calibration/exporter.RawJsonExporter` detects canonical (`hasattr projector_intrinsics`) and delegates to `result.to_dict()`.
- `calibration/importer.RawJsonImporter._from_dict` detects `"projector_intrinsics" in data and "calibration_id" in data` → `Canonical.from_dict()` → `canonical_to_legacy_result()` else legacy dict.

Old serialized files (raw JSON with `success/data`) still load; new canonical dict (`projector_intrinsics/pose`) also loads via same importer.

Validation: `tests/unit/domain/test_calibration_session.py::test_legacy_*` proves round-trip.

---

## B. Domain Entities

**New file:** `src/projectionai/domain/calibration_session.py` — **only domain deps** (`dataclasses`, `enum`, `typing`, `numpy`, `domain.geometry.Pose`, `domain.warp_mesh.WarpMesh`). Zero Qt/OpenCV/ModernGL/pybind11.

| Entity                          | Validation                                                                                                                                                                                                                                                                                               |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CalibrationPattern`            | `pattern_id>=0`, non-empty `sequence_id`, `axis ∈{COLUMN,ROW}`, `bit_value∈{0,1}`, `width/height>0`, `image.shape==(H,W)`, `dtype uint8`                                                                                                                                                                 |
| `CalibrationSequence`           | non-empty `sequence_id`, `W,H>0`, `bits_x+y == len(patterns)`, every pattern `sequence_id` matches parent, unique `pattern_id`, empty patterns rejected                                                                                                                                                  |
| `CameraCapture`                 | `image (H,W,3) uint8`, `camera_id` non-empty, `frame_number>=0`, `pattern_id>=-1`, `timestamp_ns>=0`; properties `width/height`; ready for SHM (holds borrowed numpy view)                                                                                                                               |
| `CalibrationFrame`              | **invariant** `capture.sequence_id == pattern.sequence_id` and `capture.pattern_id == pattern.pattern_id` else `ValueError`                                                                                                                                                                              |
| `CorrespondenceSet`             | `projector_x/y (H,W) float32`, `mask (H,W) bool`, `image_size (W,H)>0`, `projector_resolution>0`, `sequence_id` non-empty, `valid_ratio∈[0,1]`; `num_correspondences` derived                                                                                                                            |
| `ReconstructionResult`          | `points_camera (N,3)`, `projector_pixels (N,2)` same N, `N>=1`, `normals` optional same shape, non-empty `sequence_id`                                                                                                                                                                                   |
| `CalibrationResult` (canonical) | `calibration_id/sequence_id/projector_id/camera_id` non-empty, `projector_intrinsics 3x3`, `projector_pose 4x4`, `resolution>0`, `reprojection_error finite ≥0`, `coverage∈[0,1]`, `confidence∈[0,1]`, `camera_matrix 3x3` optional, `distortion` shape `(5,)/(4,)/(8,)`                                 |
| `CalibrationSession` (domain)   | `session_id`, `name`, `status`, `sequence?`, `frames tuple[CalibrationFrame]`, `correspondences?`, `reconstruction?`, `result?`, `projector_id/camera_id/surface_id`, `method`, `created_at`, `completed_at?`, `errors/warnings`; `transition()`, `add_frame()` with sequence check, `to_dict/from_dict` |

All entities frozen where domain state is immutable (`eq=False` + `__hash__=None` for numpy), mutable only for `CalibrationSession` lifecycle.

Reuse: `Pose`, `WarpMesh` not duplicated; `Frame` not duplicated (CameraCapture is parallel domain view).

---

## C. Session Lifecycle

**Separation:** Domain `CalibrationSession` (`domain/calibration_session.py`) vs Runner `CalibrationSession` (`calibration/session.py`).

Runner now holds `domain_session: DomainSession` (initialized in `__post_init__`), maps legacy `CalibrationStatus` → `DomainStatus`, and syncs on every transition.

**Lifecycle (reuse existing values, add explicit):**

```
CREATED (alias IDLE)
  → PREPARING
    → CAPTURING (alias ACQUIRING)
      → PROCESSING
        → SOLVING
          → VALIDATING
            → COMPLETED
              (FAILED / CANCELLED from any non-terminal)
```

- `CalibrationSessionStatus` (domain) adds `CREATED`, `CAPTURING`, `SOLVING`; `IDLE==CREATED`, `ACQUIRING==CAPTURING` aliases for BC.
- `calibration/types.CalibrationStatus` extended with same values (`CREATED`, `CAPTURING`, `SOLVING`) — old code still matches.
- `_ALLOWED_TRANSITIONS` map enforces valid edges; `transition()` allows idempotent and validates, sets `completed_at` on terminal.
- Runner `_sync_domain_status()` translates legacy→domain (`CAPTURING→CAPTURING`, `SOLVING→SOLVING`) and tolerates alias equivalence via `canonical` dict.

Existing `CalibrationSession.start/cancel/fail/finalize` now sync domain status + `method` + `projector_id/camera_id/surface_id`.

---

## D. Typed Pipeline Context

**Before:** `StageContext.data: dict[str, Any]` untyped, keys by convention, invisible to `mypy --strict`.

**After:** `PipelineData(TypedDict, total=False)` with known optional keys:

```
frames, detections, camera_calibration, projector_frames, pattern_sequence,
projector_resolution, calibrated_camera, surface_plane, projector_calibration,
projector_correspondences, correspondence_map, correspondences, reconstruction, calibration_result
```

- `StageContext.data: PipelineData` (strict), helpers `get(key,default)`, `set(key,value)`, `require(key)` typed `Any` but key-checked; `calibration/projector_stages.py` now type-checks (`projector_correspondences` key added, previously flagged).
- Preserves ordering, `errors/warnings/timings` behavior unchanged.
- No giant generic framework; simplest design that satisfies `mypy --strict`.

Verified `mypy src/projectionai` → `Success`.

---

## E. Camera Metadata Contract

**Extended `services/camera.Frame` compatibly** (all new fields optional with `None` defaults):

```python
timestamp_ns: int|None = None  # monotonic_ns()
exposure_ms: float|None = None
gain: float|None = None
sequence_id: str|None = None
pattern_id: int|None = None
capture_latency_ms: float|None = None
projector_state: str|None = None
```

- `Frame.to_camera_capture() -> CameraCapture` adapter creates domain `CameraCapture` (fills `timestamp_ns` via `monotonic_ns()` if missing, `pattern_id=-1` sentinel).
- `infrastructure/camera/opencv_camera.py` and `mock_camera.py` now stamp `timestamp_ns=time.monotonic_ns()` on every capture (provenance for future sync).
- No SHM, no vsync, no driver change — data contract only, as required for 6.2.

Existing `Frame` construction (`image,timestamp,camera_id,frame_number`) still works; tests unchanged.

Future Phase 6.4 will populate `sequence_id/pattern_id` via capture sync without redesigning domain.

---

## F. Serialization Compatibility

- **Canonical** `CalibrationResult.to_dict/from_dict` (lists for arrays, `method.value`, `warp_mesh.to_dict()`), `CalibrationSequence.to_dict/from_dict`, `CalibrationSession.to_dict/from_dict` all JSON-safe, fail clearly (`ValueError: Cannot load CalibrationResult: ...`).
- **Legacy** `calibration/types.CalibrationResult` still serializes via `exporter.RawJsonExporter` (dict with `success/data`), but importer now auto-detects canonical shape and converts via `canonical_to_legacy_result`.
- **Domain legacy** `domain/calibration.CalibrationResult` round-trips via `to_canonical/from_canonical` (FOV→fx derivation, coverage via metadata).
- **Exporter:** `RawJsonExporter._to_dict` dispatches on `hasattr projector_intrinsics`; canonical exports via `to_dict`, legacy via `asdict`.
- **Importer:** `_from_dict` checks `"projector_intrinsics" in data and "calibration_id" in data` → canonical path.
- `calibration_to_warp_mesh` canonical path uses `ProjectorIntrinsics(fx=K[0,0], fy=K[1,1], cx=K[0,2], cy=K[1,2])` directly, no FOV approximation, and respects `object_pose`.

Tested: `test_legacy_domain_conversion`, `test_legacy_types_conversion`, `test_importer_canonical`, `test_result_roundtrip`.

---

## G. Files Changed

**Created:**

- `src/projectionai/domain/calibration_session.py` (canonical 7 entities + lifecycle)
- `tests/unit/domain/test_calibration_session.py` (50 focused tests)

**Modified (Phase 6.2 only, verified `git diff --name-only`):**

- `src/projectionai/services/camera.py` — Frame metadata + `to_camera_capture()`
- `src/projectionai/infrastructure/camera/opencv_camera.py` — stamp `timestamp_ns`
- `src/projectionai/infrastructure/camera/mock_camera.py` — stamp `timestamp_ns`
- `src/projectionai/domain/calibration.py` — bridge `to_canonical/from_canonical` + doc
- `src/projectionai/services/projector_calibration.py` — `ProjectorCalibrationResult.to_canonical()`
- `src/projectionai/calibration/types.py` — `CalibrationStatus` aliases + `calibration_result_to_canonical/canonical_to_legacy_result`
- `src/projectionai/calibration/exporter.py` — canonical dispatch
- `src/projectionai/calibration/importer.py` — canonical detection
- `src/projectionai/services/calibration.py` — `calibration_to_warp_mesh` canonical dispatch via `_canonical_to_warp_mesh`
- `src/projectionai/calibration/pipeline.py` — `PipelineData` TypedDict + typed helpers
- `src/projectionai/calibration/session.py` — domain orchestration (`domain_session`, `_sync_domain_status`)

**No staging, no commit, no push, no `D:\PROJECTIONAI-camera` touched.**

---

## H. Tests

**New:** `tests/unit/domain/test_calibration_session.py` — 50 tests covering:

- Pattern/Sequence invalid IDs, resolution, duplicate, empty, mismatch
- CameraCapture invalid image/pattern_id/timestamp_ns, Frame adapter
- Frame pairing invariants (sequence_id, pattern_id)
- CorrespondenceSet invalid sizes/mask/ratio
- ReconstructionResult mismatched lens, empty, normals, sequence
- CalibrationResult invalid resolution/reprojection/coverage/confidence/intrinsics shape
- Session lifecycle (CREATED→...→COMPLETED, invalid transition, idempotent, add_frame requires sequence / mismatch)
- Serialization round-trip (sequence, result, session, legacy domain, legacy types, importer canonical, canonical→warp_mesh)

**Existing suites (all green, --no-cov):**

- `tests/unit/domain/test_calibration_session.py` 50 passed
- `tests/unit/calibration/ + test_calibration_to_warp_mesh + test_warp_mesh` 349 passed
- `tests/unit/domain/` 172 passed
- `tests/unit/infrastructure/camera` 7 passed

No existing test weakened.

---

## I. Validation

```
uv run ruff check src/          → All checks passed!
uv run ruff format --check src/ → 216 files already formatted
uv run mypy src/projectionai   → Success: no issues found in 215 source files
uv run pytest tests/unit/domain/test_calibration_session.py -q --no-cov → 50 passed
uv run pytest tests/unit/calibration/ ... -q --no-cov → 349 passed
uv run pytest tests/unit/domain/ -q --no-cov → 172 passed
git status --short              → only Phase 6.2 files M + new files ?? (untracked .planning, prior temp files pre-existing)
git diff --name-only            → 11 files (listed in G)
git diff --cached --name-only   → (empty)
```

No native/GPU code added (performance rule respected).

---

## J. Architecture Compliance

- `domain → infrastructure = ZERO` — `domain/calibration_session.py` imports only `dataclasses`, `enum`, `typing`, `numpy`, `domain.geometry`, `domain.warp_mesh`. Checked via grep.
- `domain → Qt = ZERO`, `domain → ModernGL = ZERO`, `domain → pybind11 = ZERO` — verified.
- Services depend on domain (e.g., `services/camera.Frame.to_camera_capture` imports domain under method scope only, not at module top; acceptable — runtime adapter, not import cycle at import time). Pipeline `TypedDict` stays in `calibration/` (not domain).
- Existing dependency direction preserved: `calibration` still imports `domain`, not vice-versa (domain holds canonical, `calibration/types` adapts via functions, not domain importing calibration at top level — only inside `_pose_from_matrix` fallback).
- `mypy --strict` clean; `ruff` clean.

---

## K. Remaining Phase 6.3+ Work

- **6.3 Pattern engine** — verify GrayCode generator bit-exact, cache, `invert` correctness (reuse `CalibrationSequence`).
- **6.4 Capture + sync** — `vsync()` barrier, populate `Frame.sequence_id/pattern_id/capture_latency_ms` deterministically, SHM ring (not in 6.2), `CalibrationFrame` pairing at capture time.
- **6.5 Structured-light** — native GrayCode decode `CorrespondenceSet` via `CameraCapture[]` (currently opencv path still uses `Frame.image`).
- **6.6 Reconstruction** — `CorrespondenceSet → ReconstructionResult` triangulation (reuse `estimators.triangulate_plane` adapted to `ReconstructionResult`).
- **6.7 Solver** — `ReconstructionResult → CalibrationResult` via `ProjectorIntrinsicsEstimator/ExtrinsicsEstimator` → `canonical CalibrationResult.to_canonical()`.
- **6.8 Calibration→WarpMesh** — wiring already supports canonical; need `CalibrationManager` to persist `CalibrationResult.warp_mesh`.
- **6.9 GPU** — WarpMesh VBO upload, PBO, `WarpEngineFactory` backend selection.
- **6.10 Physical validation** — RMS≤2px / coverage≥0.5 gate using canonical `reprojection_error/coverage`.
- **6.11 Perf** — SHM zero-copy, SIMD decode, optional CUDA for phase-shift.

---

## L. Risks

1. **Dict legacy still in flight** — `calibration/types.CalibrationData` dict-of-dicts remains for persistence; conversion helpers must stay tested until SQLite migration replaces it.
2. **Pose conversion loss** — `domain/calibration.to_canonical` uses FOV→fx fallback (`fy=fx`) and identity rotation via `scipy` if available; non-standard FOV (ultra-short throw) will need real `K` from canonical instead.
3. **Frame metadata not yet populated** — `sequence_id/pattern_id` stay `None` until 6.4; `to_camera_capture()` defaults to `""`/`-1`; downstream must treat `-1` as unknown, not valid.
4. **Pipeline TypedDict still permissive** — `Any` for values keeps BC but hides misuse; tighten to generics in 6.7 if stages proliferate.
5. **SHM view lifetime** — future zero-copy `CameraCapture.image` as SHM view must document borrow semantics; domain currently holds reference (future explicit `SharedBuffer` wrapper).

---

## M. Phase 6.2 Verdict

**COMPLETE — proceed to 6.3.**

- [x] ONE canonical `CalibrationResult` exists (`domain/calibration_session.CalibrationResult`)
- [x] Existing callers migrated or compatibility-wrapped (exporter/importer, domain bridge, projector result adapter, `calibration_to_warp_mesh`)
- [x] `CalibrationSession` is a real typed domain entity (frozen entities + validated lifecycle)
- [x] Runner orchestration separate from domain state (`session.py:domain_session` + `_sync_domain_status`)
- [x] `StageContext` is typed (`PipelineData` TypedDict, helpers)
- [x] `Frame` metadata contract supports future sync (7 optional fields, stamped `timestamp_ns`)
- [x] Old calibration data remains loadable (legacy→canonical and canonical→legacy round-trips tested)
- [x] `mypy --strict` introduces no new errors (`Success: 215 files`)
- [x] Existing calibration tests remain green (349+172 passed)
- [x] No native/GPU implementation added prematurely
- [x] No duplicated `Pose`/`Surface`/`WarpMesh` model created

**STOP AFTER THE REPORT.**
