"""Calibration events — typed dataclasses for calibration workflow.

These extend the core ``CalibrationStarted`` / ``CalibrationProgress`` /
``CalibrationComplete`` / ``CalibrationFailed`` events in
``projectionai.core.events`` with calibration-domain-specific detail.

Components emit these via the core ``EventBus`` for cross-layer
communication (UI, editor, job system).
"""

from __future__ import annotations

from dataclasses import dataclass

from projectionai.calibration.types import (
    CalibrationMethod,
    CalibrationStageType,
)
from projectionai.core.events import Event

# -- Calibration pipeline events ----------------------------------------------


@dataclass(frozen=True)
class CalibrationStageStarted(Event):
    """Emitted when a pipeline stage begins."""

    session_id: str
    stage: CalibrationStageType
    method: CalibrationMethod


@dataclass(frozen=True)
class CalibrationStageCompleted(Event):
    """Emitted when a pipeline stage finishes successfully."""

    session_id: str
    stage: CalibrationStageType
    duration_ms: float = 0.0


@dataclass(frozen=True)
class CalibrationStageFailed(Event):
    """Emitted when a pipeline stage fails."""

    session_id: str
    stage: CalibrationStageType
    reason: str


# -- Projector / camera / surface events --------------------------------------


@dataclass(frozen=True)
class ProjectorDetected(Event):
    """Emitted when a projector is discovered or configured."""

    projector_id: str
    resolution_x: int = 0
    resolution_y: int = 0


@dataclass(frozen=True)
class ProjectorConfigured(Event):
    """Emitted when projector parameters are updated."""

    projector_id: str


@dataclass(frozen=True)
class CameraDetected(Event):
    """Emitted when a camera is discovered or configured."""

    camera_id: str
    resolution_x: int = 0
    resolution_y: int = 0


@dataclass(frozen=True)
class CameraConfigured(Event):
    """Emitted when camera parameters are updated."""

    camera_id: str


@dataclass(frozen=True)
class SurfaceConfigured(Event):
    """Emitted when surface geometry or pose is updated."""

    surface_id: str


# -- Data management events ---------------------------------------------------


@dataclass(frozen=True)
class CalibrationDataChanged(Event):
    """Emitted when calibration data is modified (undoable)."""

    session_id: str
    field: str  # which field changed


@dataclass(frozen=True)
class CalibrationHistoryChanged(Event):
    """Emitted when the calibration history is modified."""

    session_id: str


@dataclass(frozen=True)
class CalibrationProfileApplied(Event):
    """Emitted when a profile is loaded and applied."""

    profile_id: str
    session_id: str


@dataclass(frozen=True)
class CalibrationProfileSaved(Event):
    """Emitted when a profile is saved from current session data."""

    profile_id: str
    session_id: str


# -- Workspace events ---------------------------------------------------------


@dataclass(frozen=True)
class CalibrationWorkspaceChanged(Event):
    """Emitted when the calibration workspace configuration changes."""

    workspace_id: str


# -- Validation events --------------------------------------------------------


@dataclass(frozen=True)
class CalibrationValidationStarted(Event):
    """Emitted when validation begins."""

    session_id: str


@dataclass(frozen=True)
class CalibrationValidationCompleted(Event):
    """Emitted when validation finishes."""

    session_id: str
    passed: bool
    error_count: int = 0
    warning_count: int = 0
    quality_score: float = 0.0
