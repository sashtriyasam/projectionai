# 7.4 Dependency Map

## Existing Integration Points

| File                                  | Role                        | Reuse                                                                            |
| ------------------------------------- | --------------------------- | -------------------------------------------------------------------------------- |
| `application/calibration_workflow.py` | ProductionWorkflow contract | **READ-ONLY** — consume state, progress, hardware_pending                        |
| `ui/viewmodels/calibration.py`        | CalibrationViewModel        | No direct modification — progress lives in separate CalibrationProgressViewModel |
| `ui/viewmodels/devices.py`            | DevicesViewModel (7.2)      | Reuse camera/projector status                                                    |
| `ui/viewmodels/observable.py`         | Observable base class       | Inherit for poll-based notifications                                             |
| `ui/panels/calibration_panel.py`      | CalibrationSessionsPanel    | **DO NOT MODIFY** — separate concern                                             |
| `ui/theme.py`                         | Color tokens                | Use existing palette                                                             |

## New Files to Create

| File                                                   | Purpose                                             |
| ------------------------------------------------------ | --------------------------------------------------- |
| `ui/viewmodels/calibration_progress.py`                | Thin presentation model wrapping ProductionWorkflow |
| `ui/widgets/calibration_progress_widget.py`            | Qt widget: stages, progress, ETA, hardware-pending  |
| `tests/unit/ui/test_calibration_progress_viewmodel.py` | Deterministic viewmodel tests                       |
| `tests/unit/ui/test_calibration_progress_widget.py`    | Widget rendering tests                              |

## Dependency Chain

```
ProductionWorkflow (7.1)
    ↓ read-only
CalibrationProgressViewModel (new)
    ↓ subscribe/revision
CalibrationProgressWidget (new)
    ↓ polls
DevicesViewModel (7.2) → camera/projector status
```

## Constraints

- ProductionWorkflow is the single authority for state/progress
- Viewmodel maps WorkflowState → display text, never duplicates state
- Widget polls viewmodel on timer, never calls workflow directly
- No calibration math in UI layer
- Hardware-pending gates displayed as-is from workflow.hardware_pending
