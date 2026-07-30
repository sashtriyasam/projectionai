"""Calibration manager — application-level calibration orchestration.

Integrates the calibration framework with the application as a proper
``Manager`` subclass. Owns the workspace, session lifecycle, and
coordinates with other managers (scene, command, job).

Editor integration:
- ViewportController switches to calibration mode via gizmo domain.
- Calibration gizmos use ``GizmoDomain.CALIBRATION``.
- Undo/redo for calibration parameter changes via CommandManager.
- Scene graph nodes with ``ComponentType.CALIBRATION`` hold calibration data.

Multi-projector scaling:
- Workspace holds N projector poses, M camera poses, K surfaces.
- Each projector gets its own calibration session.
- Sessions produce per-projector warp meshes.
- Edge blending and colour matching operate on the combined output.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, override

from projectionai.calibration.exporter import (
    CalibrationExporter,
    ExporterRegistry,
)
from projectionai.calibration.importer import (
    CalibrationImporter,
    ImporterRegistry,
)
from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.types import CalibrationMethod
from projectionai.calibration.validator import CalibrationValidator
from projectionai.calibration.workspace import CalibrationWorkspace
from projectionai.core.events import EventBus
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class CalibrationManager(Manager):
    """Application-level calibration orchestration.

    Owns the workspace, session lifecycle, and coordinates with
    other managers and the editor viewport.

    Usage::

        calib_mgr = CalibrationManager(event_bus)
        await calib_mgr.initialize()

        session = calib_mgr.create_session(method=CalibrationMethod.ARUCO)
        await session.start()
        # ... pipeline runs ...
        result = session.finalize()
        report = calib_mgr.validate(result)
        calib_mgr.export(result, "raw", "calibration.json")
    """

    def __init__(
        self,
        event_bus: EventBus,
        workspace: CalibrationWorkspace | None = None,
        validator: CalibrationValidator | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._workspace: CalibrationWorkspace = workspace or CalibrationWorkspace(
            event_bus=event_bus
        )
        self._validator: CalibrationValidator = validator or CalibrationValidator()

        # Export / import
        self._exporter_registry = ExporterRegistry()
        self._importer_registry = ImporterRegistry()

        # Paths
        self._data_dir: Path | None = None

    # -- Properties -----------------------------------------------------------

    @property
    def workspace(self) -> CalibrationWorkspace:
        """The calibration workspace."""
        return self._workspace

    @property
    def validator(self) -> CalibrationValidator:
        """The calibration validator."""
        return self._validator

    @property
    def exporter_registry(self) -> ExporterRegistry:
        """Registry of named calibration exporters."""
        return self._exporter_registry

    @property
    def importer_registry(self) -> ImporterRegistry:
        """Registry of named calibration importers."""
        return self._importer_registry

    @property
    def data_dir(self) -> Path | None:
        """Directory for calibration data persistence."""
        return self._data_dir

    @data_dir.setter
    def data_dir(self, path: str | Path) -> None:
        self._data_dir = Path(path)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # -- Session management ---------------------------------------------------

    def create_session(
        self,
        name: str = "Calibration Session",
        method: CalibrationMethod = CalibrationMethod.MANUAL,
    ) -> CalibrationSession:
        """Create a new calibration session in the workspace."""
        return self._workspace.create_session(name=name, method=method)

    def get_active_session(self) -> CalibrationSession | None:
        """Get the currently active calibration session."""
        return self._workspace.get_active_session()

    def get_session(self, session_id: str) -> CalibrationSession | None:
        """Get a session by ID."""
        return self._workspace.get_session(session_id)

    # -- Validation -----------------------------------------------------------

    def validate(self, session: CalibrationSession) -> Any:
        """Validate a session's result."""
        from projectionai.calibration.validator import ValidationReport

        if session.result is None:
            _logger.warning("Cannot validate session %s: no result", session.id)
            return ValidationReport(passed=False, quality_score=0.0)
        return self._validator.validate_and_update(session.result)

    # -- Export / Import ------------------------------------------------------

    def register_exporter(self, name: str, exporter: CalibrationExporter) -> None:
        """Register a custom calibration exporter."""
        self._exporter_registry.register(name, exporter)

    def register_importer(self, name: str, importer: CalibrationImporter) -> None:
        """Register a custom calibration importer."""
        self._importer_registry.register(name, importer)

    def export(
        self,
        session: CalibrationSession,
        fmt: str = "raw",
        path: str | Path | None = None,
    ) -> Any:
        """Export a session's calibration result.

        Args:
            session: The calibration session.
            fmt: Export format name (``"raw"``, ``"projection_mapping"``,
                ``"open_cv"``).
            path: Optional file path.

        Returns:
            The exported data.

        Raises:
            RuntimeError: If the session has no result.
        """
        if session.result is None:
            msg = f"Session {session.id} has no result to export"
            raise RuntimeError(msg)
        return self._exporter_registry.export(fmt, session.result, path=path)

    def import_calibration(
        self, source: str | Path | dict[str, Any], fmt: str = "raw"
    ) -> Any:
        """Import calibration data from a source.

        Args:
            source: File path, JSON string, or dict.
            fmt: Import format name.

        Returns:
            The imported ``CalibrationResult``.
        """
        return self._importer_registry.import_data(fmt, source)

    # -- Editor integration ---------------------------------------------------

    def get_calibration_nodes(self) -> list[dict[str, Any]]:
        """Return scene nodes with calibration components.

        Integrates with the scene manager to find nodes tagged with
        calibration data.
        """
        # Future: query SceneManager for nodes with ComponentType.CALIBRATION
        return []

    def get_calibration_gizmo_data(self) -> dict[str, Any]:
        """Return data needed by calibration gizmos in the editor.

        Returns control points, warp grid, and projector/camera info
        for the editor gizmo system to display and manipulate.
        """
        session = self.get_active_session()
        if session is None or session.result is None:
            return {}

        data = session.result.data
        if data is None:
            return {}

        return {
            "control_points": data.control_points,
            "warp_mesh": data.warp_mesh,
            "confidence": data.confidence,
            "projector_pose": data.projector_pose,
            "camera_pose": data.camera_pose,
            "surface_pose": data.surface_pose,
        }

    # -- Manager lifecycle ----------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        _logger.info("CalibrationManager initialized")

    @override
    async def _on_shutdown(self) -> None:
        _logger.info("CalibrationManager shut down")
