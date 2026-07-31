# ADR-009: Stage-Based Calibration Pipeline with Explicit Validation

## Status

Accepted

## Context

Projection calibration is the core correctness problem of the product: a projector must be positioned so its output lands precisely on a detected surface. The domain is error-prone — lens distortion, projector/camera poses, and correspondence noise all compound. We needed a design that makes the process auditable and testable rather than a single opaque solver call.

## Decision

Model calibration as a **stage-based pipeline** (`src/projectionai/calibration/pipeline.py`) where each stage transforms typed calibration data, bookended by explicit validation:

- `CalibrationData` (poses, correspondences) flows through ordered stages: feature extraction → pose estimation → refinement.
- A dedicated `validator.py` layer runs sanity checks (NaN detection, reprojection error bounds, pose plausibility) that can fail a calibration early.
- `history.py` keeps an append-only `CalibrationHistory` so operators can compare attempts and re-apply the best result.
- `session.py` groups one calibration run; `profile.py` and `workspace.py` persist per-projector profiles and workspace state.
- The pipeline is UI-agnostic — `calibration_manager.py` orchestrates it, and both manual and automatic calibrators implement the `Calibrator` service interface.

## Consequences

**Positive**

- Validation catches bad captures early instead of producing garbage output.
- History enables A/B comparison and rollback between attempts.
- Pure-Python pipeline logic is unit-testable without hardware (the 400+ test suite covers pipeline, validator, projector model, history).

**Negative**

- Stage-based flow is more verbose than a single `solve()` call.
- Hardware-dependent stages (camera capture) remain outside the pipeline and must be injected.

## Compliance

Implemented across `src/projectionai/calibration/` — `pipeline.py`, `validator.py`, `history.py`, `session.py`, `types.py` — orchestrated by `calibration_manager.py` and surfaced as the `Calibrator` service interface in `src/projectionai/services/calibration.py`.
