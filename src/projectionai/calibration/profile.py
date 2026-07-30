"""Calibration profile — a named, reusable calibration configuration.

Profiles allow users to save and load complete calibration setups:
projector model, camera model, surface model, target configuration,
and pipeline settings. This enables fast switching between different
calibration scenarios (e.g. different venues, different projector models).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from projectionai.calibration.camera_model import CameraModel
from projectionai.calibration.projector_model import ProjectorModel
from projectionai.calibration.surface_model import SurfaceModel
from projectionai.calibration.target import CalibrationTarget
from projectionai.calibration.types import CalibrationMethod


@dataclass
class CalibrationProfile:
    """A complete, saved calibration configuration.

    A profile captures everything needed to reproduce a calibration setup:
    the projector, camera, surface, target, and method. It does NOT store
    calibration results — those go in ``CalibrationHistory``.

    Profiles are serialised to JSON for persistence and sharing.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Default Profile"
    description: str = ""

    # Method
    method: CalibrationMethod = CalibrationMethod.MANUAL

    # Models
    projector: ProjectorModel = field(default_factory=ProjectorModel)
    camera: CameraModel = field(default_factory=CameraModel)
    surface: SurfaceModel = field(default_factory=SurfaceModel)
    target: CalibrationTarget = field(default_factory=CalibrationTarget)

    # Pipeline configuration
    pipeline_stages: list[str] = field(default_factory=list)
    pipeline_settings: dict[str, Any] = field(default_factory=dict)

    # Multi-configuration
    projector_ids: list[str] = field(default_factory=list)
    camera_ids: list[str] = field(default_factory=list)
    surface_ids: list[str] = field(default_factory=list)

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tags: list[str] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Mark the profile as recently modified."""
        self.updated_at = datetime.now(UTC).isoformat()
