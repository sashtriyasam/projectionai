"""Calibration framework — reusable projection calibration architecture.

This package provides the data models, pipeline orchestration, session
management, and editor integration for projection calibration. It is
deliberately algorithm-free: computer vision techniques (ArUco, structured
light, etc.) implement the ``CalibrationStage`` interface and slot into
the pipeline.

Architecture layers:

1. **Data models** — ``ProjectorModel``, ``CameraModel``, ``SurfaceModel``,
   ``CalibrationTarget``, and shared ``types.py`` enums/dataclasses.
   These define WHAT we are calibrating.

2. **Session management** — ``CalibrationSession``, ``CalibrationWorkspace``,
   ``CalibrationProfile``, ``CalibrationHistory``. These manage WHEN and
   in what order calibration happens.

3. **Pipeline** — ``CalibrationPipeline``, ``CalibrationStage`` (ABC),
   ``StageContext``. These define HOW calibration stages are orchestrated
   without containing algorithm logic.

4. **Quality** — ``CalibrationValidator`` with composable checks,
   validation reports, and quality scoring.

5. **Persistence** — ``CalibrationExporter`` / ``CalibrationImporter``
   with format-specific implementations and registries.

6. **Application integration** — ``CalibrationManager`` (``Manager``
   subclass) that owns the workspace and coordinates with other managers,
   the editor viewport, and the gizmo system.

Multi-projector design:
- ``ProjectorModel`` holds multiple ``ProjectorPose`` instances (keyed
  by output/screen ID).
- ``CameraModel`` holds multiple ``CameraPose`` instances.
- ``SurfaceModel`` holds multiple ``SurfacePose`` instances.
- ``CalibrationWorkspace`` manages N sessions, one per projector.
- Edge blending and colour matching operate after per-projector warps.

Usage::

    from projectionai.calibration import CalibrationManager

    mgr = CalibrationManager(event_bus)
    await mgr.initialize()

    session = mgr.create_session(method=CalibrationMethod.ARUCO)
    await session.start()
    # ... stages execute ...
    result = session.finalize()
    report = mgr.validate(session)
    mgr.export(session, "projection_mapping", "warp.json")
"""

from __future__ import annotations

from projectionai.calibration.calibration_manager import CalibrationManager
from projectionai.calibration.camera_model import (
    CameraExtrinsics,
    CameraIntrinsics,
    CameraModel,
    CameraPose,
)
from projectionai.calibration.exporter import (
    CalibrationExporter,
    ExporterRegistry,
    OpenCvExporter,
    ProjectionMappingExporter,
    RawJsonExporter,
)
from projectionai.calibration.history import CalibrationHistory, HistoryEntry
from projectionai.calibration.importer import (
    CalibrationImporter,
    ImporterRegistry,
    RawJsonImporter,
)
from projectionai.calibration.pipeline import (
    CalibrationPipeline,
    CalibrationStage,
    StageContext,
    StageError,
)
from projectionai.calibration.profile import CalibrationProfile
from projectionai.calibration.projector_model import (
    ProjectorExtrinsics,
    ProjectorIntrinsics,
    ProjectorLens,
    ProjectorModel,
    ProjectorPose,
)
from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.surface_model import (
    SurfaceModel,
    SurfacePose,
)
from projectionai.calibration.target import CalibrationTarget
from projectionai.calibration.types import (
    CalibrationData,
    CalibrationMethod,
    CalibrationResult,
    CalibrationStageType,
    CalibrationState,
    CalibrationStatus,
    LensType,
    ProjectionType,
    WarpMode,
)
from projectionai.calibration.validator import (
    CalibrationCheck,
    CalibrationValidator,
    ValidationReport,
)
from projectionai.calibration.workspace import CalibrationWorkspace

__all__ = [
    # Quality
    "CalibrationCheck",
    # Types
    "CalibrationData",
    # Export / Import
    "CalibrationExporter",
    # Workspace & session
    "CalibrationHistory",
    "CalibrationImporter",
    # Manager
    "CalibrationManager",
    "CalibrationMethod",
    # Pipeline
    "CalibrationPipeline",
    "CalibrationProfile",
    "CalibrationResult",
    "CalibrationSession",
    "CalibrationStage",
    "CalibrationStageType",
    "CalibrationState",
    "CalibrationStatus",
    # Models
    "CalibrationTarget",
    "CalibrationValidator",
    "CalibrationWorkspace",
    "CameraExtrinsics",
    "CameraIntrinsics",
    "CameraModel",
    "CameraPose",
    "ExporterRegistry",
    "HistoryEntry",
    "ImporterRegistry",
    "LensType",
    "OpenCvExporter",
    "ProjectionMappingExporter",
    "ProjectionType",
    "ProjectorExtrinsics",
    "ProjectorIntrinsics",
    "ProjectorLens",
    "ProjectorModel",
    "ProjectorPose",
    "RawJsonExporter",
    "RawJsonImporter",
    "StageContext",
    "StageError",
    "SurfaceModel",
    "SurfacePose",
    "ValidationReport",
    "WarpMode",
]
