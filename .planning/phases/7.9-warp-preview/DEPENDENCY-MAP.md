# Phase 7.9 — Warp Preview: Dependency Map

## Canonical Path (Accepted Result → Warp Mesh → Preview)

```
User clicks "Continue" in CalibrationResultReviewWidget
  → CalibrationResultReviewViewModel.accept()
  → emits signal to CalibrationProgressViewModel
  → CalibrationProgressViewModel.on_calibration_result_reviewed(result, decision)
  → Decision == ACCEPTED_FOR_PREVIEW
  → CalibrationProgressViewModel._transition_to_state(WorkflowState.PREVIEW)
  → PreviewViewModel.update_from_workflow(workflow_state, calibration_result)
  → PreviewViewModel calls calibration_to_warp_mesh(result)
  → Returns WarpMesh(domain, range, control_points, resolution)
  → PreviewViewModel calls create_projection_mapping(warp_mesh)
  → Returns ProjectionMapping(warp_mesh, output_resolution)
  → PreviewViewModel passes ProjectionMapping to ProjectionPass
  → ProjectionPass._ensure_mesh_uploaded() → GPU upload via ShaderProgram
  → ProjectionPass.render(content, projection_mapping) → OpenGL render
  → Preview display (IDLE/CHECKERBOARD/GRID/etc. content rendered through mesh)
```

## Key Domain Objects (Already Exist)

| Object              | Location                                       | Purpose                                                                            |
| ------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------- |
| `CalibrationResult` | `domain/calibration_session.py:509`            | Immutable result: projector→camera projection matrix, reprojection error, coverage |
| `WarpMesh`          | `domain/warp_mesh.py:72`                       | Canonical warp: domain/range rectangles, NxM control points, resolution            |
| `ProjectionMapping` | `domain/projection.py:147`                     | Output-facing warp: wraps WarpMesh + output_resolution                             |
| `ProjectionPass`    | `infrastructure/renderer/passes/projection.py` | GPU renderer: uploads mesh to shader, renders content through warp                 |

## Functions That Exist (Reuse These)

| Function                                 | Location                                       | Purpose                               |
| ---------------------------------------- | ---------------------------------------------- | ------------------------------------- |
| `calibration_to_warp_mesh()`             | `domain/warp_mesh.py`                          | Converts CalibrationResult → WarpMesh |
| `create_projection_mapping()`            | `domain/projection.py`                         | Wraps WarpMesh → ProjectionMapping    |
| `ProjectionPass.render()`                | `infrastructure/renderer/passes/projection.py` | Renders content through warp mesh     |
| `ProjectionPass._ensure_mesh_uploaded()` | `infrastructure/renderer/passes/projection.py` | Lazily uploads mesh to GPU            |

## OutputManager Safety Machine (Do NOT Bypass)

| Method       | State Transition     | Purpose                 |
| ------------ | -------------------- | ----------------------- |
| `arm()`      | READY_TO_ARM → ARMED | Enables hardware output |
| `go_live()`  | ARMED → LIVE         | Activates display       |
| `blackout()` | any → BLACKOUT       | Silences display        |
| `freeze()`   | LIVE → FROZEN        | Pauses last frame       |
| `stop()`     | any → STOPPED        | Full stop               |

**CRITICAL**: Preview MUST NOT call `go_live()` or `arm()`. Preview state is handled independently by PreviewViewModel. OutputManager remains authoritative for safety.

## What Phase 7.9 Must Build

### New Files

1. **`src/projectionai/ui/viewmodels/preview.py`** — `PreviewViewModel`
   - State model: IDLE → LOADING → READY → RUNNING → FROZEN → BLACKOUT → ERROR → CLOSED
   - Consumes CalibrationResult via `update_from_workflow()`
   - Calls `calibration_to_warp_mesh()` and `create_projection_mapping()`
   - Content generators: IDENTITY, CHECKERBOARD, GRID, CROSSHAIR, BORDER, CORNER_MARKERS, COLOR_BARS, GRADIENT
   - Mesh diagnostics: control point bounds, resolution, domain/range validation
   - Safety boundaries: never calls `go_live()` or `arm()`

2. **`src/projectionai/ui/widgets/preview_widget.py`** — `PreviewWidget`
   - Displays preview content through warp mesh
   - Content selector (combo box)
   - Mesh diagnostics display
   - Safety indicators (LIVE/ARMED/BLACKOUT states)

3. **`tests/unit/ui/test_preview_viewmodel.py`** — ViewModel tests
4. **`tests/unit/ui/test_preview_widget.py`** — Widget tests

### What We Do NOT Build (Reuse Existing)

- Do NOT create `PreviewWarpMesh` / `PreviewCalibrationMesh` / `PreviewProjectionModel`
- Do NOT recalculate calibration in preview
- Do NOT rerun decoder/reconstruction/solver
- Do NOT silently enter LIVE
- Do NOT bypass DisplayValidator / OutputManager
- Do NOT create another mesh cache
- Do NOT introduce a second content-generation framework
- Do NOT promote HARDWARE_PENDING to PASS

## Display Integration

- **Phase 7.2 Selected Display**: `DisplayManager.selected_display` — reuse for preview output
- **DisplayValidator**: Validates display capability — remains authoritative
- **OutputWindow**: `GLOutputWindow` — fullscreen OpenGL context for rendering
- **PatternPresentation**: Existing content generation — extend with new patterns

## Hardware Gates (7 Pending, Not Promoted by Preview)

1. optical closure
2. real vsync/frameSwapped
3. settle-time
4. camera buffer policy
5. real sentinel coverage
6. real two-plane calibration
7. repeatability

These gates remain `HARDWARE_PENDING` regardless of preview working correctly.

## Quality Gates (Must Pass)

- `ruff check` — no new errors
- `ruff format` — all files formatted
- `mypy --strict` — no new type errors
- `pytest tests/unit/ui/test_preview_viewmodel.py` — all pass
- `pytest tests/unit/ui/test_preview_widget.py` — all pass
- Google Sheet: row updated to DONE, STATUS_HISTORY + CHANGELOG appended
- REPORT.md updated at `.planning/phases/7.9-warp-preview/REPORT.md`
