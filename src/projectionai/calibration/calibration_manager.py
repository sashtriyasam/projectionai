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

import asyncio
import logging
from pathlib import Path
from typing import Any, override
from uuid import uuid4

from projectionai.calibration.camera_stages import (
    BoardDetectionStage,
    IntrinsicsCalibrationStage,
)
from projectionai.calibration.exporter import (
    CalibrationExporter,
    ExporterRegistry,
)
from projectionai.calibration.importer import (
    CalibrationImporter,
    ImporterRegistry,
)
from projectionai.calibration.pipeline import StageContext
from projectionai.calibration.projector_stages import (
    CorrespondenceDecodeStage,
    ProjectorPoseStage,
)
from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.types import (
    CalibrationData,
    CalibrationMethod,
    CalibrationStatus,
)
from projectionai.calibration.validator import CalibrationValidator, ValidationReport
from projectionai.calibration.workspace import CalibrationWorkspace
from projectionai.core.errors import CameraError, ProjectionAIError
from projectionai.core.events import EventBus
from projectionai.managers import Manager
from projectionai.managers.camera_manager import CameraManager
from projectionai.managers.job_manager import JobInfo, JobManager
from projectionai.services.camera import Frame
from projectionai.services.camera_calibration import (
    CameraCalibrationAlgorithm,
    CameraCalibrationResult,
)
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    PatternProjector,
    ProjectorCalibrationAlgorithm,
    ProjectorCalibrationResult,
    SurfacePlane,
)

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
        camera_manager: CameraManager | None = None,
        job_manager: JobManager | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._workspace: CalibrationWorkspace = workspace or CalibrationWorkspace(
            event_bus=event_bus
        )
        self._validator: CalibrationValidator = validator or CalibrationValidator()
        self._camera_manager: CameraManager | None = camera_manager
        self._job_manager: JobManager | None = job_manager

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
    def camera_manager(self) -> CameraManager | None:
        """The camera manager used for frame capture (``None`` if unset)."""
        return self._camera_manager

    @property
    def job_manager(self) -> JobManager | None:
        """The job manager used for background calibration (``None`` if unset)."""
        return self._job_manager

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

    def validate(self, session: CalibrationSession) -> ValidationReport:
        """Validate a session's result."""
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

    # -- Camera calibration --------------------------------------------------

    async def run_camera_calibration(
        self,
        camera_id: str,
        algorithm: CameraCalibrationAlgorithm,
        *,
        session_name: str = "Camera Calibration",
        num_frames: int = 20,
    ) -> CalibrationSession:
        """Run a camera intrinsic calibration workflow end-to-end.

        Captures *num_frames* frames from *camera_id*, runs board detection
        and intrinsics stages through the session pipeline, persists the
        result into the session's calibration data, and finalises the
        session (history entry + ``CalibrationComplete`` event).

        Returns:
            The completed session. Check ``session.result.success`` and
            ``session.result.error_message`` for the outcome.
        """
        if self._camera_manager is None:
            msg = "CalibrationManager has no camera manager - cannot capture frames"
            raise RuntimeError(msg)
        if num_frames < 1:
            raise ValueError("num_frames must be at least 1")

        session = self.create_session(
            name=session_name, method=CalibrationMethod.CHESSBOARD
        )
        session.state.active_camera_id = camera_id
        await session.start(CalibrationMethod.CHESSBOARD)

        # -- Acquire frames --------------------------------------------------
        session.state.status = CalibrationStatus.ACQUIRING
        frames: list[Frame] = []
        for index in range(num_frames):
            try:
                frame = await self._camera_manager.capture_frame(camera_id)
            except CameraError as exc:
                await session.fail(f"Frame capture failed: {exc}")
                session.finalize()
                return session
            frames.append(frame)
            session.update_progress(
                (index + 1) / (num_frames + 2),
                f"Captured frame {index + 1}/{num_frames}",
                stage="capture",
            )

        # -- Pipeline: detect + calibrate ------------------------------------
        session.state.status = CalibrationStatus.PROCESSING
        session.pipeline.add_stage(BoardDetectionStage(algorithm))
        session.pipeline.add_stage(IntrinsicsCalibrationStage(algorithm))
        ctx = StageContext(data={"frames": frames})
        ctx = await session.pipeline.run(ctx)

        if ctx.errors:
            await session.fail("; ".join(ctx.errors))
            session.finalize()
            return session

        calibration: CameraCalibrationResult = ctx.data["camera_calibration"]
        self._commit_camera_result(session, camera_id, calibration, ctx)
        session.state.intermediate_results["detections"] = ctx.data.get(
            "detections", []
        )
        session.state.status = CalibrationStatus.COMPLETED
        session.update_progress(1.0, "Calibration complete")
        session.finalize()
        return session

    def enqueue_camera_calibration(
        self,
        camera_id: str,
        algorithm: CameraCalibrationAlgorithm,
        *,
        session_name: str = "Camera Calibration",
        num_frames: int = 20,
    ) -> JobInfo | None:
        """Enqueue a camera calibration run as a background job.

        Returns ``None`` when no ``JobManager`` is available.
        """
        if self._job_manager is None:
            return None
        job_id = f"camera-calibration-{uuid4().hex[:8]}"
        return self._job_manager.enqueue(
            job_id,
            session_name,
            self.run_camera_calibration,
            kwargs={
                "camera_id": camera_id,
                "algorithm": algorithm,
                "session_name": session_name,
                "num_frames": num_frames,
            },
        )

    def _commit_camera_result(
        self,
        session: CalibrationSession,
        camera_id: str,
        calibration: CameraCalibrationResult,
        ctx: StageContext,
    ) -> None:
        """Persist an intrinsic calibration into the session's calibration data.

        Stores the result under ``CalibrationData.camera_pose[camera_id]`` in
        the shape :class:`OpenCvExporter` consumes (``camera_matrix``,
        ``distortion_coeffs``, ``width``, ``height``).
        """
        if session.state.data is None:
            session.state.data = CalibrationData()
        data = session.state.data
        data.method = CalibrationMethod.CHESSBOARD
        data.camera_pose[camera_id] = {
            "camera_matrix": calibration.camera_matrix.tolist(),
            "distortion_coeffs": calibration.distortion_coeffs.tolist(),
            "width": calibration.image_size[0],
            "height": calibration.image_size[1],
        }
        data.reprojection_error = calibration.reprojection_error
        data.residuals = list(calibration.per_view_errors)
        data.num_samples = calibration.num_views
        data.confidence = 1.0
        data.custom = {
            "camera_id": camera_id,
            "image_size": list(calibration.image_size),
            "per_view_errors": list(calibration.per_view_errors),
            "warnings": list(ctx.warnings),
        }

    # -- Projector calibration ----------------------------------------------

    async def run_projector_calibration(
        self,
        camera_id: str,
        algorithm: ProjectorCalibrationAlgorithm,
        projector: PatternProjector,
        *,
        session_name: str = "Projector Calibration",
        projector_id: str = "projector-1",
        projector_resolution: tuple[int, int],
        camera: CalibratedCamera,
        surface: SurfacePlane,
        settle_seconds: float = 0.1,
        capture_timeout: float = 10.0,
    ) -> CalibrationSession:
        """Run a projector calibration workflow end-to-end.

        Builds the algorithm's structured light sequence, projects each
        pattern onto *surface* while capturing frames from *camera_id*,
        then runs the correspondence decode and pose estimation stages
        through the session pipeline, persists the result into the
        session's calibration data, and finalises the session (history
        entry + ``CalibrationComplete`` event).

        Acquisition uses a local capture loop rather than
        ``PatternCaptureSession`` because this flow's requirements
        differ: the correspondence decode stage consumes the captures as
        a ``list`` of raw RGB ``Frame`` objects (the session returns
        grayscale arrays), per-pattern progress is reported through
        ``session.update_progress``, and capture errors fail the session
        gracefully (``session.fail`` + finalize) instead of raising.

        Args:
            camera_id: Camera observing the projected patterns.
            algorithm: The projector calibration algorithm to run.
            projector: Device that displays the patterns.
            session_name: Human-readable session name.
            projector_id: Identifier for the calibrated projector.
            projector_resolution: ``(width, height)`` of the projector.
            camera: Intrinsics of the calibrated observing camera.
            surface: The planar surface in camera coordinates the
                patterns are projected onto.
            settle_seconds: Delay after each pattern display before
                capturing, letting the display/camera stabilise.
            capture_timeout: Per-frame capture timeout in seconds.

        Returns:
            The completed session. Check ``session.result.success`` and
            ``session.result.error_message`` for the outcome.
        """
        if self._camera_manager is None:
            msg = "CalibrationManager has no camera manager - cannot capture frames"
            raise RuntimeError(msg)
        if projector_resolution[0] <= 0 or projector_resolution[1] <= 0:
            raise ValueError(
                f"projector_resolution must be positive, got {projector_resolution}"
            )

        session = self.create_session(name=session_name, method=algorithm.method)
        session.state.active_camera_id = camera_id
        session.state.active_projector_id = projector_id
        await session.start(algorithm.method)

        # -- Build sequence and acquire frames -------------------------------
        session.state.status = CalibrationStatus.ACQUIRING
        sequence = algorithm.build_sequence(projector_resolution)
        frames: list[Frame] = []
        try:
            for index, pattern in enumerate(sequence.patterns):
                try:
                    await projector.show(pattern.image)
                except ProjectionAIError as exc:
                    await session.fail(f"Projector display failed: {exc}")
                    session.finalize()
                    return session
                await asyncio.sleep(settle_seconds)
                try:
                    frame = await asyncio.wait_for(
                        self._camera_manager.capture_frame(camera_id),
                        timeout=capture_timeout,
                    )
                except (CameraError, TimeoutError) as exc:
                    await session.fail(f"Frame capture failed: {exc}")
                    session.finalize()
                    return session
                frames.append(frame)
                session.update_progress(
                    (index + 1) / (len(sequence.patterns) + 2),
                    f"Captured pattern {index + 1}/{len(sequence.patterns)}",
                    stage="capture",
                )
        finally:
            await projector.hide()

        # -- Pipeline: decode + pose -----------------------------------------
        session.state.status = CalibrationStatus.PROCESSING
        session.pipeline.add_stage(CorrespondenceDecodeStage(algorithm))
        session.pipeline.add_stage(ProjectorPoseStage(algorithm))
        ctx = StageContext(
            data={
                "projector_frames": frames,
                "pattern_sequence": sequence,
                "projector_resolution": projector_resolution,
                "calibrated_camera": camera,
                "surface_plane": surface,
            }
        )
        ctx = await session.pipeline.run(ctx)

        if ctx.errors:
            await session.fail("; ".join(ctx.errors))
            session.finalize()
            return session

        calibration: ProjectorCalibrationResult = ctx.data["projector_calibration"]
        self._commit_projector_result(
            session, projector_id, camera_id, calibration, ctx
        )
        session.state.intermediate_results["correspondence_count"] = (
            calibration.num_correspondences
        )
        session.state.intermediate_results["coverage"] = calibration.coverage
        session.state.status = CalibrationStatus.COMPLETED
        session.update_progress(1.0, "Calibration complete")
        session.finalize()
        return session

    def enqueue_projector_calibration(
        self,
        camera_id: str,
        algorithm: ProjectorCalibrationAlgorithm,
        projector: PatternProjector,
        *,
        session_name: str = "Projector Calibration",
        projector_id: str = "projector-1",
        projector_resolution: tuple[int, int],
        camera: CalibratedCamera,
        surface: SurfacePlane,
        settle_seconds: float = 0.1,
        capture_timeout: float = 10.0,
    ) -> JobInfo | None:
        """Enqueue a projector calibration run as a background job.

        Returns ``None`` when no ``JobManager`` is available.
        """
        if self._job_manager is None:
            return None
        job_id = f"projector-calibration-{uuid4().hex[:8]}"
        return self._job_manager.enqueue(
            job_id,
            session_name,
            self.run_projector_calibration,
            kwargs={
                "camera_id": camera_id,
                "algorithm": algorithm,
                "projector": projector,
                "session_name": session_name,
                "projector_id": projector_id,
                "projector_resolution": projector_resolution,
                "camera": camera,
                "surface": surface,
                "settle_seconds": settle_seconds,
                "capture_timeout": capture_timeout,
            },
        )

    def _commit_projector_result(
        self,
        session: CalibrationSession,
        projector_id: str,
        camera_id: str,
        calibration: ProjectorCalibrationResult,
        ctx: StageContext,
    ) -> None:
        """Persist a projector calibration into the session's calibration data.

        Stores the result under ``CalibrationData.projector_pose[projector_id]``
        with the projector intrinsics, pose, and resolution, plus quality
        metrics. The pose maps projector-local 3D points into the camera
        coordinate frame (the projector's pose in the camera frame).
        """
        if session.state.data is None:
            session.state.data = CalibrationData()
        data = session.state.data
        data.method = session.state.current_method
        data.projector_pose[projector_id] = {
            "projector_matrix": calibration.projector_intrinsics.tolist(),
            "pose": calibration.projector_pose.tolist(),
            "width": calibration.projector_resolution[0],
            "height": calibration.projector_resolution[1],
        }
        data.reprojection_error = calibration.reprojection_error
        data.residuals = list(calibration.per_point_errors)
        data.num_samples = calibration.num_correspondences
        data.confidence = calibration.confidence
        data.custom = {
            "projector_id": projector_id,
            "camera_id": camera_id,
            "coverage": calibration.coverage,
            "image_size": list(calibration.image_size),
            "camera_matrix": calibration.camera_matrix.tolist(),
            "distortion_coeffs": calibration.distortion_coeffs.tolist(),
            "warnings": list(ctx.warnings),
        }

    # -- Manager lifecycle ----------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        _logger.info("CalibrationManager initialized")

    @override
    async def _on_shutdown(self) -> None:
        _logger.info("CalibrationManager shut down")
