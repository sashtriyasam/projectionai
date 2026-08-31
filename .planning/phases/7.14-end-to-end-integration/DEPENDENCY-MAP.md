# DEPENDENCY-MAP.md — Phase 7.14 Architecture Audit

**Generated**: 2026-08-30 | **Phase**: 7.14 End-to-End Production Calibration Integration

## 1. Layer Architecture (Top → Bottom)

```
┌─────────────────────────────────────────────────────────────────────┐
│  UI LAYER (Qt Widgets + ViewModels)                                │
│  CalibrationProgressWidget ↔ CalibrationProgressViewModel          │
│  CalibrationResultReviewWidget ↔ CalibrationResultReviewViewModel  │
│  PreviewWidget ↔ PreviewViewModel                                  │
│  DeviceSelectionWidget ↔ DevicesViewModel                          │
│  SurfaceSetupWidget ↔ SurfaceSetupViewModel                        │
│  MainWindow (panel docking, lifecycle)                             │
├─────────────────────────────────────────────────────────────────────┤
│  APPLICATION LAYER (Workflow + State Machine)                      │
│  ProductionWorkflow (state machine, run_full, run_gate)            │
│  OutputStateMachine (IDLE→PREVIEW→ARMED→LIVE→BLACKOUT/FREEZE)     │
├─────────────────────────────────────────────────────────────────────┤
│  SERVICES LAYER (Calibration Pipeline)                             │
│  CaptureSession / SynchronizedCaptureSession                       │
│  PatternPresentationSession                                        │
│  StructuredLightDecoder                                            │
│  ReconstructionBackend (triangulation)                             │
│  CalibrationSolver (solve_calibration)                             │
│  CalibrationResult (domain) + WarpMesh + ProjectionMapping         │
│  ValidationGate (V-01..V-07, AuthorizationLevel)                   │
├─────────────────────────────────────────────────────────────────────┤
│  PERSISTENCE LAYER                                                 │
│  CalibrationPersistence (save/load .calibration/)                  │
│  CalibrationHistoryStore (save/load history/entries.json)          │
│  RecallManager (list/load/delete/activate)                         │
├─────────────────────────────────────────────────────────────────────┤
│  HARDWARE + INFRASTRUCTURE LAYER                                   │
│  OutputManager (arm, go_live, blackout, freeze, end_session)       │
│  RuntimeWatchdog (failure → safe output state)                     │
│  DisplayManager + DisplayValidator                                 │
│  CameraManager / FrameSource                                       │
│  GLOutputWindow / ProjectionPass / PatternPass                     │
│  WarpEngine (CPU reference / GPU realtime)                         │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Calibration Workflow State Machine

```
IDLE → PRECHECK → PREPARING → CAPTURING → DECODING → RECONSTRUCTING
    → SOLVING → VALIDATING → PREVIEW → SAVING → READY_TO_ARM → ARMED → LIVE

Terminal: FAILED, CANCELLED
```

**ProductionWorkflow** (`application/calibration_workflow.py:191`):

- States: `WorkflowState` (StrEnum) — 15 values
- Holds: `calibration_result`, `warp_mesh`, `hardware_pending`, `is_synthetic`
- Key methods: `preflight()`, `run_full()`, `transition()`, `reset()`, `run_gate()`
- Cancellation: `request_cancel()` → `_check_cancelled()` raises `CancelledError`

## 3. Output State Machine

```
IDLE → PREVIEW → ARMED → LIVE
                    ↓         ↓
               DISARM    BLACKOUT ↔ LIVE
                         FREEZE ↔ LIVE
                         STOP → IDLE
```

**OutputStateMachine** (`ui/state_machine.py`):

- States: `IDLE, PREVIEW, ARMED, LIVE, BLACKOUT, FREEZE`
- Guards: `can()`, `can_arm()`, `can_send()`, `can_blackout()`, etc.

**OutputManager** (`hardware/output_manager.py:97`):

- Wraps display routing + validation gate
- `arm()`: validates display + gate → ARMED (safe, returns report on failure)
- `go_live()`: validates + gate → LIVE (raises `LiveNotAuthorizedError` on failure)
- `blackout()`, `freeze()`, `unfreeze()`, `end_session()`
- `set_calibration_context()`: feeds gate with calibration_report, hardware_pending, source_mode

## 4. Validation Gate Architecture

**GateId** (V-01..V-07):

| Gate | Name                | Description                |
| ---- | ------------------- | -------------------------- |
| V-01 | CALIBRATION_QUALITY | Calibration result quality |
| V-02 | DISPLAY_ROUTING     | Display routing valid      |
| V-03 | RENDERER_READINESS  | Renderer ready             |
| V-04 | WINDOW_AVAILABILITY | Output window available    |
| V-05 | HARDWARE_PENDING    | Hardware pending gates     |
| V-06 | SOURCE_MODE         | Source mode validation     |
| V-07 | WARP_READINESS      | Warp mesh ready            |

**AuthorizationLevel**: `NONE → PREVIEW → ARM → LIVE`

- NONE: any FAIL → no authorization
- PREVIEW: V-01 PASS + V-07 PASS
- ARM: PREVIEW + V-02 PASS + V-03 PASS + V-04 PASS + V-06 PASS
- LIVE: ARM + V-05 PASS

## 5. Component Dependency Graph

```
CalibrationProgressViewModel
  └── ProductionWorkflow (direct reference)
        ├── SynchronizedCaptureSession (capture pipeline)
        │     ├── FrameSource (CameraManager)
        │     └── PatternProjector (display backend)
        ├── StructuredLightDecoder (decode frames)
        ├── ReconstructionBackendFactory.create() (triangulation)
        ├── solve_calibration() (solver)
        ├── ValidationGate (run_gate)
        └── CalibrationPersistence (save/load)

CalibrationResultReviewViewModel
  ├── CalibrationResult (domain object)
  ├── ValidationGate (evaluate_gate, cached)
  └── ReviewDecision (ACCEPT/REJECT/NEEDS_RECALIBRATION)

PreviewViewModel
  ├── CalibrationResult → calibration_to_warp_mesh()
  ├── WarpMesh
  ├── ProjectionMapping
  ├── MeshDiagnostics (validity check)
  └── ProjectionWarpEngine (CPU/GPU render)

OutputViewModel
  └── OutputStateMachine (direct reference)

OutputManager
  ├── DisplayManager + DisplayValidator
  ├── ValidationGate (unified gate check)
  ├── CalibrationReport (context)
  └── OutputSession (state snapshot)

RuntimeWatchdog
  └── OutputManager → safe output state on failure

CalibrationPersistence
  ├── save() → .calibration/manifest.json + calibration.json + warp_mesh.json + projection.json
  └── load() → CalibrationPersistenceBundle

CalibrationHistoryStore
  └── save()/load() → history/entries.json (checksummed)

RecallManager
  ├── list() → HistoryEntry[]
  ├── load(entry_id) → CalibrationPersistenceBundle
  └── activate(entry_id) → sets active calibration
```

## 6. UI ↔ ViewModel ↔ Workflow Binding

| Widget                        | ViewModel                        | Workflow Binding                                                   |
| ----------------------------- | -------------------------------- | ------------------------------------------------------------------ |
| CalibrationProgressWidget     | CalibrationProgressViewModel     | `set_workflow(workflow)` — reads state, stages, progress           |
| CalibrationResultReviewWidget | CalibrationResultReviewViewModel | `set_result(calibration_result)` — shows intrinsics, pose, quality |
| PreviewWidget                 | PreviewViewModel                 | `update_from_workflow(result)` — builds warp mesh from result      |
| DeviceSelectionWidget         | DevicesViewModel                 | Camera/projector selection                                         |
| SurfaceSetupWidget            | SurfaceSetupViewModel            | Surface validation                                                 |
| OutputStatusWidget            | OutputViewModel                  | `arm()`, `send_to_live()`, `blackout()` via OutputStateMachine     |
| OutputManager                 | —                                | `begin_session()`, `arm()`, `go_live()`, `end_session()`           |

## 7. Data Flow — Canonical Journey

```
1. DeviceSelection → camera/projector IDs
2. SurfaceSetup → surface validation report
3. ProductionWorkflow.preflight() → camera/projector/surface checks
4. ProductionWorkflow.run_full():
   a. prepare → CalibrationSequence
   b. capture → SynchronizedCaptureSession → CalibrationFrames
   c. decode → StructuredLightDecoder → CorrespondenceSet
   d. reconstruct → ReconstructionBackend → ReconstructionResult
   e. solve → solve_calibration() → CalibrationResult
   f. validate → ValidationReport
   g. preview → CalibrationResult
   h. save → CalibrationPersistence.save()
5. CalibrationResultReviewViewModel → operator review
6. OutputManager.set_calibration_context() → feeds gate
7. OutputManager.arm() → validated ARMED state
8. OutputManager.go_live() → validated LIVE state
```

## 8. Handoff Boundaries

| From                  | To                                                  | Data                                                        | Boundary                          |
| --------------------- | --------------------------------------------------- | ----------------------------------------------------------- | --------------------------------- |
| Capture → Decode      | SynchronizedCaptureSession → StructuredLightDecoder | CalibrationFrame[] → CorrespondenceSet                      | async await                       |
| Decode → Reconstruct  | Decoder → ReconstructionBackend                     | CorrespondenceSet + Camera + Surface → ReconstructionResult | function call                     |
| Reconstruct → Solve   | Backend → solve_calibration()                       | ReconstructionResult → CalibrationResult                    | function call                     |
| Solve → Review        | Workflow → ReviewViewModel                          | CalibrationResult                                           | property access                   |
| Review → Preview      | ReviewViewModel → PreviewViewModel                  | CalibrationResult → WarpMesh + ProjectionMapping            | update_from_workflow()            |
| Preview → Persistence | PreviewViewModel → CalibrationPersistence           | CalibrationResult + WarpMesh → disk                         | save()                            |
| Persistence → Recall  | RecallManager → CalibrationPersistence              | entry_id → CalibrationPersistenceBundle                     | load()                            |
| Arm → Output          | OutputViewModel → OutputManager                     | gate context → ValidationGate                               | set_calibration_context() + arm() |
| Go Live → Output      | OutputManager → DisplayManager                      | validated → display switch                                  | go_live()                         |
