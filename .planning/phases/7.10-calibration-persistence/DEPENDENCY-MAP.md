# Phase 7.10 — DEPENDENCY-MAP: Calibration Persistence + Recall

## Existing Persistence Infrastructure

### What Already Exists

| Component                                     | Location                                          | Pattern                        | Gap                                            |
| --------------------------------------------- | ------------------------------------------------- | ------------------------------ | ---------------------------------------------- |
| `CalibrationResult.to_dict()`                 | `domain/calibration_session.py:639`               | JSON-safe dict with numpy→list | **No checksum, no schema version**             |
| `CalibrationResult.from_dict()`               | `domain/calibration_session.py:683`               | Reconstructs from dict         | **No integrity check, no compatibility check** |
| `WarpMesh.to_dict()` / `from_dict()`          | `domain/warp_mesh.py:198`                         | JSON-safe dict with numpy→list | Same                                           |
| `ProjectionMapping.to_dict()` / `from_dict()` | `domain/projection.py:216`                        | JSON-safe dict                 | Same                                           |
| `RawJsonExporter`                             | `calibration/exporter.py:57`                      | Writes JSON file               | **No atomic write, no checksum**               |
| `RawJsonImporter`                             | `calibration/importer.py:55`                      | Reads JSON file                | **No integrity check**                         |
| `CalibrationHistory`                          | `calibration/history.py:40`                       | In-memory only                 | **No disk persistence at all**                 |
| `WorkspaceManager.save()`                     | `managers/workspace_manager.py:220`               | tmp→os.replace atomic          | **Reference pattern for atomic writes**        |
| `project_format.write_project()`              | `infrastructure/persistence/project_format.py:57` | Direct write (non-atomic)      | **No checksum, no version**                    |

### Canonical Domain Objects (DO NOT DUPLICATE)

| Object                       | Location                            | Serialization                       |
| ---------------------------- | ----------------------------------- | ----------------------------------- |
| `CalibrationResult`          | `domain/calibration_session.py:509` | `to_dict()` / `from_dict()`         |
| `WarpMesh`                   | `domain/warp_mesh.py:72`            | `to_dict()` / `from_dict()`         |
| `ProjectionMapping`          | `domain/projection.py:147`          | `to_dict()` / `from_dict()`         |
| `HistoryEntry` (calibration) | `calibration/history.py:23`         | No serialization yet                |
| `HistoryEntry` (project)     | `domain/project.py:127`             | Different type, not for calibration |

### Bridge: Canonical ↔ Legacy

- `canonical_to_legacy_result()` — `calibration/types.py` (converts canonical → legacy)
- `RawJsonImporter._from_dict()` — detects canonical by `projector_intrinsics` key, calls `CalibrationResult.from_dict()`

## What Phase 7.10 Must Build

### New Module: `src/projectionai/calibration/persistence.py`

```
calibration/persistence.py
├── SCHEMA_VERSION = 1
├── class PersistenceError(RuntimeError)
├── class IntegrityError(PersistenceError)
├── class CompatibilityError(PersistenceError)
├── class CalibrationPersistence
│   ├── save(directory, calibration_result, warp_mesh=None, projection_mapping=None)
│   ├── load(directory) → CalibrationPersistenceBundle
│   ├── _compute_checksum(data) → str (SHA-256)
│   └── _verify_checksum(data, expected) → bool
└── class CalibrationRecall
    ├── recall(directory) → RecallResult
    ├── _validate_integrity(bundle) → list[str]
    ├── _validate_compatibility(bundle) → list[str]
    └── _reconstruct_canonical(bundle) → CalibrationResult
```

### New Module: `src/projectionai/calibration/history_store.py`

```
calibration/history_store.py
├── class CalibrationHistoryStore
│   ├── save(history, directory)
│   ├── load(directory) → CalibrationHistory
│   └── _atomic_write(path, data)
```

### File Layout on Disk

```
.calibration/
├── manifest.json          # Schema version, checksums, timestamps
├── calibration.json       # CalibrationResult.to_dict()
├── warp_mesh.json         # WarpMesh.to_dict() (optional)
├── projection.json        # ProjectionMapping.to_dict() (optional)
└── history/
    └── entries.json       # List of HistoryEntry dicts
```

### Manifest Format

```json
{
  "schema_version": 1,
  "created_at": "2026-08-28T...",
  "updated_at": "2026-08-28T...",
  "checksums": {
    "calibration": "sha256:...",
    "warp_mesh": "sha256:...",
    "projection": "sha256:..."
  },
  "projector_id": "...",
  "camera_id": "...",
  "surface_id": "...",
  "calibration_id": "..."
}
```

### Constraints

1. **No second CalibrationResult model** — use `domain.calibration_session.CalibrationResult`
2. **No second WarpMesh model** — use `domain.warp_mesh.WarpMesh`
3. **No second replay format** — use existing `calibration/replay.py`
4. **No parallel persistence framework** — single `CalibrationPersistence` class
5. **No silent overwrite** — prompt/check before overwriting valid calibration
6. **No silent corrupt load** — raise `IntegrityError` on checksum mismatch
7. **No silent substitution** — verify projector/camera/surface IDs match
8. **No recalculation** — load exactly what was saved
9. **Every change updates Control Center** (Google Sheet)
10. **STOP AT REVIEW — DO NOT START 7.11**

### Consumers of Persisted Data

| Consumer                | Phase    | What it reads                                   |
| ----------------------- | -------- | ----------------------------------------------- |
| 7.8 (Multi-orientation) | DONE     | CalibrationResult with calibration_sequence_ids |
| 7.9 (Warp Preview)      | DONE     | WarpMesh for preview rendering                  |
| UI panels               | Existing | ProjectionMapping for display                   |

### Test Coverage Requirements

- Save/load round-trip for each domain object
- Checksum verification (valid, corrupted, missing)
- Schema version migration (future-proof)
- Atomic write (interrupted write doesn't corrupt)
- Compatibility check (wrong projector/camera/surface)
- History persistence
- Legacy import compatibility
- Filesystem safety (path traversal, permissions)
