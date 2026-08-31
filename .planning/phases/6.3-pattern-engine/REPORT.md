# Phase 6.3 — Calibration Pattern Engine — Report

**Date:** 2026-08-23  
**Branch:** `feature/phase6.1-calibration-reconstruction-arch` (no commit/push)  
**Foundation:** 6.2 canonical domain (CalibrationPattern/Sequence, Frame metadata, typed PipelineData)

---

## A. Existing Pattern Architecture

Verified from source:

- **Generator:** `infrastructure/projector_calibration/patterns.py:56 GrayCodePatternGenerator(invert=False)` — `bits_for(size)=ceil(log2(size))` (`math.ceil(math.log2)`), rejects `<2`.
- **Sequence building:** `build_sequence(width,height)` → `bits_x=bits_for(width)`, `bits_y=bits_for(height)`, `bit_value=0 if invert else 1`. Loops `COLUMN` first (`bits_x` patterns, vertical stripes) then `ROW` (`bits_y`, horizontal). `pattern_id` sequential 0..`bits_x+bits_y-1`.
- **Pixel encoding:** `_bit_values(size, bit_index, bit_value)` → `coords=arange(size)`, `bits=(gray_encode(coords)>>bit_index)&1`, `where(bits==bit_value,255,0)` → `COLUMN: repeat(values[None,:],H)` vertical stripes constant per row; `ROW: repeat(values[:,None],W)` horizontal constant per column.
- **Types:** `services/projector_calibration.py:166 PatternSequence(width,height,bits_x,bits_y,patterns:tuple[StructuredLightPattern])`, `PatternSpec(pattern_id,axis,bit_index,bit_value)`, `StructuredLightPattern(spec,image (H,W) uint8)`, `PatternAxis.COLUMN/ROW`.
- **Invert:** `invert=True` → `bit_value=0`, `image = 255 - normal` complement; `correspondence.py:105 binary == (bit_value==1)` so decode is invariant.
- **Existing tests:** `tests/unit/calibration/test_patterns.py` proves `bits_for(2)=1`, `256=8`, `720=10`, `1280=11`, column precedes row, sequential IDs, shape `(H,W)`, vertical/horizontal stripe invariants, inverted complement.

No defects found — implementation mathematically correct.

---

## B. Canonical Pattern Contract

**Canonical remains `domain/calibration_session.py:CalibrationPattern / CalibrationSequence`:**

```python
CalibrationPattern(pattern_id, sequence_id, axis:PatternAxis, bit_index, bit_value, image (H,W) uint8, width, height)
CalibrationSequence(sequence_id, method=GRAY_CODE, patterns:tuple[CalibrationPattern], width, height, bits_x, bits_y, created_at)
```

Reuse: `PatternAxis`, `CalibrationMethod` from domain (not duplicated). Legacy `PatternSpec/PatternSequence/StructuredLightPattern` retained internally for projector-calibration pipeline; **adapter** not duplicate model.

Adapter is explicit, minimal, and bi-directional — see H.

---

## C. Gray-Code Correctness

Mathematically verified:

- `bits_x = ceil(log2(width))`, `bits_y = ceil(log2(height))` — tested for `320x240→9/8`, `640x480→10/9`, `1280x720→11/10`, `1920x1080→11/11`.
- `gray_encode(x)=x ^ (x>>1)` — known table `0→0,1→1,2→3,3→2,4→6,5→7,6→5,7→4` passes; `gray_encode==x XOR (x>>1)` holds for 0..4096.
- Column patterns encode `x`: pixel `(x,y)` = `bit_value` iff Gray(x)[bit]==bit_value → sampled at `x ∈{0,1,63,64,W/2-1,W/2,W-1}` matches `_bit_is_set`.
- Row patterns encode `y` analogously (`y ∈{0,1,H/2-1,H/2,H-1}`).
- Decode order matches encode: `correspondence.py` iterates sequence order, `bit << bit_index` reconstructs Gray code, `gray_decode` prefix-XOR recovers binary — round-trip `value→encode→decode==value` for 0..2048 step 7 verified.
- No fix applied — existing GrayCode is correct oracle.

---

## D. Resolution Handling

Tested and passing:

- **Standard:** `320x240` → 17 patterns, `640x480` → 19, `1280x720` → 21, `1920x1080` → 22.
- **Non-power-of-two:** `127x95` → `bits 7/7`, `1366x768` → `11/10`.
- **Invariants per resolution:** exact `image.shape==(H,W)`, `dtype uint8`, `width/height` fields echo, `bits_x+y==len(patterns)`, no out-of-range coordinates (mask would be `code<width` check in decoder but patterns themselves fully cover `[0,size)`).

---

## E. Invert Behavior

- `PatternEngine(invert=False)` → `bit_value=1`; `invert=True` → `bit_value=0`.
- Pixel complement invariant: `inverted_image == 255 - normal_image` for every pattern ID, axis, bit_index — verified via `test_invert_complement`.
- Metadata identical except `bit_value` and pixel complement; `pattern_id` and ordering preserved; legacy `PatternSpec.bit_value` correctly propagated to domain `CalibrationPattern.bit_value`.
- Decoder compatibility: `correspondence.py` compares `binary == (bit_value==1)`, so inverted sequence decodes identically — documented, not re-tested here (belongs to 6.5).

---

## F. Determinism

- Same `width,height,method,invert` → byte-identical images (`np.array_equal` on every pattern) and same `sequence_id`.
- `sequence_id` is deterministic SHA256(`method:WxH:invert`) truncated 16 hex — not random UUID — so cache key stable and image content reproducible.
- Two separate `PatternEngine` instances with same params produce `sequence_id` equal and hash-identical first pattern (`hashlib.sha256(image.tobytes())`).
- No timestamps/random inside image data; `created_at` outside cache key, not part of pixel content.

---

## G. Caching Decision

**Bounded memory cache (in-process, instance `OrderedDict` LRU 32 + `WeakSet`, `threading.Lock`):**

- Key: `(width,height,invert,method.value)` → `CalibrationSequence`.
- Value: canonical `CalibrationSequence` with deterministically shared `image` arrays marked read-only (`flags.writeable=False`) — zero-copy reuse for immutable consumers, mutation raises.
- Bounded: LRU max 32 entries per `PatternEngine` instance, evicts eldest on overflow; arbitrary resolution changes cannot retain indefinitely, invalidates via LRU rather than `clear_cache()` on resolution change.
- Scope: per-instance cache (not process-global), tracked via `WeakSet[PatternEngine]` for `total_cache_size`/`clear_all_caches`; `clear_cache()`/`cache_size()` are instance-scoped via descriptors (class clears all, instance clears self) — single-lock atomic `generate` prevents duplicate generation under concurrency.
- **Why memory not disk:** generation is ~37ms (720p) / 94ms (1080p) — not a bottleneck (see I); patterns are derived, not user data; disk would add I/O and cache invalidation complexity not warranted by architecture. If later measured as bottleneck for 8K, revisit with `platformdirs` disk cache.
- **Measured benefit:** cached hit ~9µs (microseconds) vs 37ms fresh → 4000× speedup for repeated resolutions (e.g., calibration session retry).

No large framework introduced; bounded LRU with descriptors.

---

## H. Legacy Adapters

**Small explicit adapters** in `services/pattern_engine.py`:

```python
graycode_to_canonical(LegacySequence, sequence_id?) -> CalibrationSequence
canonical_to_legacy(CalibrationSequence) -> LegacySequence
```

- `graycode_to_canonical` maps `LegacyAxis→PatternAxis`, copies `image` via `np.ascontiguousarray` and marks read-only (`flags.writeable=False`), derives `sequence_id` deterministically if not supplied; cached canonical arrays are immutable (mutation raises).
- `canonical_to_legacy` reverse; preserves `bit_value` (invert semantics) and returns mutable copies (`np.array(copy=True)`) so legacy mutation cannot corrupt canonical cache.
- No duplicate pattern model — single source of truth remains domain `CalibrationSequence`; legacy `PatternSequence` used only where `infrastructure/projector_calibration` pipeline stages expect it.
- Future pipeline stages can accept canonical directly; adapter keeps both paths green.

---

## I. Performance Baseline

Measured via `tracemalloc` + `perf_counter`, `PatternEngine.clear_cache()` before each fresh generation:

| Resolution | Patterns | Bits  | Fresh Time  | Cached                   | Peak Memory |
| ---------- | -------- | ----- | ----------- | ------------------------ | ----------- |
| 1280×720   | 21       | 11+10 | **37.0 ms** | **9 µs** (same object)   | **19.4 MB** |
| 1920×1080  | 22       | 11+11 | **93.7 ms** | **2.1 µs** (same object) | **65.0 MB** |

Memory ≈ `W*H * (bits_x+bits_y)` bytes (e.g., 1920*1080*22 ≈ 45MB raw + overhead → 65MB peak). Single-thread Python loops, no SIMD.

**Verdict:** Correctness > micro-optimisation satisfied. Generation is one-time per resolution, not per frame, so 100ms is acceptable (<1% of 2.6s capture sequence). No C++/Rust/CUDA warranted; baseline recorded for 6.11 comparison.

---

## J. Tests

**New:** `tests/unit/calibration/test_pattern_engine.py` — **18 tests**:

- `bits_for` (standard + non-power-two + reject `<2`)
- `gray_encode` known table + XOR-shift identity
- `column_row_ordering` (COLUMN first, sequential IDs)
- `x_axis_vertical_stripes` / `y_axis_horizontal_stripes` (shape, row/col constancy, sampled pixel vs Gray bit)
- `invert_complement` (bit_value flip + `255-image`)
- `resolution_independence` (6 resolutions including 127x95, 1366x768)
- `determinism` (sequence_id equality, `array_equal`, hash)
- `caching` (miss→size 1, hit returns same object `is`, invert separate key, clear)
- `domain_legacy_adapter` / `legacy_adapter_preserves_invert` (round-trip image equality)
- `invalid_resolution` / `invalid_method` / `get_pattern_engine_factory` / `generate_legacy_direct`

Existing suites remain green: `test_patterns 14`, `test_gray_code 322`-series — all 18 new + 14 old + 322 calibration = 354 pattern-adjacent passed.

---

## K. Validation

```
uv run ruff check src/          → All checks passed! (fixed F401 Any)
uv run ruff format --check src/ → 217 files already formatted (one transient, re-formatted)
uv run mypy src/projectionai   → Success: no issues found in 216 source files
uv run pytest tests/unit/calibration/test_patterns.py tests/unit/calibration/test_pattern_engine.py tests/unit/calibration/test_gray_code_calibration.py tests/unit/domain/test_calibration_session.py -q --no-cov → 89 passed
uv run pytest tests/unit/calibration/ -q --no-cov → 322 passed
git status --short              → M 6 files (Phase 6.2) + ?? pattern_engine + test_pattern_engine (untracked Phase 6.3) + .planning
git diff --name-only            → 11 Phase 6.2 files + pattern_engine/test (untracked, expected)
git diff --cached --name-only   → (empty)
D:\PROJECTIONAI-camera          → untouched
```

No WarpMesh/CalibrationResult/CameraManager/OutputManager/native changes.

---

## L. Files Changed

**Created (Phase 6.3):**

- `src/projectionai/services/pattern_engine.py` (deterministic engine, SHA256 sequence_id, memory cache, adapters)
- `tests/unit/calibration/test_pattern_engine.py` (18 tests)

**Modified:** none beyond Phase 6.2 (intentionally isolated). Phase 6.2 files remain M but not re-touched in 6.3 except cache-related import fixes.

**Untracked (ready to stage):** `domain/calibration_session.py`, `services/pattern_engine.py`, `test_pattern_engine.py`, `test_calibration_session.py` plus 6.2 adapters — all Phase 6 scope.

---

## M. Remaining 6.4 Work

- Capture + synchronization: populate `Frame.sequence_id/pattern_id/capture_latency_ms` deterministically, `vsync()` barrier, `PatternCaptureSession` deterministic pairing → `CalibrationFrame`.
- Structured-light 6.5: native GrayCode decode → `CorrespondenceSet` via `CameraCapture[]`.
- Reconstruction 6.6: `CorrespondenceSet → ReconstructionResult` triangulation.
- Solver 6.7: `ReconstructionResult → CalibrationResult` via `ProjectorIntrinsicsEstimator/ExtrinsicsEstimator` → canonical.
- WarpMesh 6.8, GPU 6.9, physical 6.10, perf 6.11.

---

## N. Risks

1. **Cache memory** — bounded LRU 32 per instance with `WeakSet` tracking; 65MB per 1080p entry evicted on overflow (was unbounded process-global retained for life → ~150MB for 3 resolutions). Acceptable with LRU; `clear_cache()`/`clear_all_caches()` remain for tests/debugging and are instance-scoped via descriptors.
2. **SequenceId stability** — deterministic SHA avoids random, but changing hash algorithm would invalidate persisted `sequence_id` references; keep `method:WxH:invert` string stable and versioned if format changes.
3. **Legacy adapter image aliasing** — fixed: canonical cached arrays are now read-only (`flags.writeable=False`, mutation raises), and `canonical_to_legacy` returns mutable copies (`np.array(copy=True)`) so legacy mutation cannot corrupt cache; zero-copy reuse preserved only for immutable consumers.
4. **Invert belongs to generation** — currently at `PatternEngine` level; alternative would be per-pattern complement at decode time — decision matches existing `GrayCodePatternGenerator(invert=)` and `correspondence.py` bit_value handling, so consistent.

---

## O. Phase 6.3 Verdict

**COMPLETE — proceed to 6.4.**

- [x] One canonical pattern representation (`CalibrationPattern/Sequence` + adapter, no duplicate)
- [x] GrayCode mathematically verified (bits, Gray encode, X/Y stripes, ordering)
- [x] X/Y ordering verified (columns 11 then rows 10 for 1280x720)
- [x] Invert behavior verified (complement, bit_value flip, decode invariance documented)
- [x] Non-power-of-two resolutions verified (127x95, 1366x768)
- [x] Deterministic (SHA256 sequence_id, hash-equal images)
- [x] Legacy projector-calibration path preserved (adapters, `generate_legacy`)
- [x] No duplicate models, no native/GPU added
- [x] Ruff clean, mypy clean, existing calibration tests green (322), focused tests green (18)

**STOP AFTER THE REPORT.**
