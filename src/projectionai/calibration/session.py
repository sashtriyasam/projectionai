"""Calibration session — orchestrates a single calibration workflow.

A ``CalibrationSession`` owns one complete calibration run: it tracks
state, holds the active models (projector, camera, surface), manages
the pipeline execution, and produces the final ``CalibrationResult``.

Sessions are designed to be serialised for persistence, review, and
iterative refinement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from projectionai.calibration.camera_model import CameraModel
from projectionai.calibration.events import (
    CalibrationDataChanged,
)
from projectionai.calibration.history import CalibrationHistory
from projectionai.calibration.pipeline import CalibrationPipeline
from projectionai.calibration.projector_model import ProjectorModel
from projectionai.calibration.surface_model import SurfaceModel
from projectionai.calibration.target import CalibrationTarget
from projectionai.calibration.types import (
    CalibrationData,
    CalibrationMethod,
    CalibrationResult,
    CalibrationState,
    CalibrationStatus,
)
from projectionai.core.events import (
    CalibrationFailed,
    CalibrationProgress,
    CalibrationStarted,
    EventBus,
)
from projectionai.domain.calibration_session import (
    CalibrationMethod as DomainMethod,
)
from projectionai.domain.calibration_session import (
    CalibrationSession as DomainSession,
)
from projectionai.domain.calibration_session import (
    CalibrationSessionStatus as DomainStatus,
)

_logger = logging.getLogger(__name__)


_STATUS_MAP: dict[CalibrationStatus, DomainStatus] = {
    CalibrationStatus.IDLE: DomainStatus.CREATED,
    CalibrationStatus.CREATED: DomainStatus.CREATED,
    CalibrationStatus.PREPARING: DomainStatus.PREPARING,
    CalibrationStatus.ACQUIRING: DomainStatus.CAPTURING,
    CalibrationStatus.CAPTURING: DomainStatus.CAPTURING,
    CalibrationStatus.PROCESSING: DomainStatus.PROCESSING,
    CalibrationStatus.SOLVING: DomainStatus.SOLVING,
    CalibrationStatus.VALIDATING: DomainStatus.VALIDATING,
    CalibrationStatus.COMPLETED: DomainStatus.COMPLETED,
    CalibrationStatus.FAILED: DomainStatus.FAILED,
    CalibrationStatus.CANCELLED: DomainStatus.CANCELLED,
}


@dataclass
class CalibrationSession:
    """A single calibration session.

    Usage::

        session = CalibrationSession(projector, camera, surface, event_bus)
        await session.start(CalibrationMethod.ARUCO)
        # ... pipeline runs stages ...
        result = session.finalize()
    """

    # Identifiers
    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Calibration Session"

    # Models (active configuration)
    projector: ProjectorModel = field(default_factory=ProjectorModel)
    camera: CameraModel = field(default_factory=CameraModel)
    surface: SurfaceModel = field(default_factory=SurfaceModel)
    target: CalibrationTarget = field(default_factory=CalibrationTarget)

    # Active IDs for multi-entity configurations
    active_projector_id: str = ""
    active_camera_id: str = ""
    active_surface_id: str = ""

    # Pipeline and history
    pipeline: CalibrationPipeline = field(default_factory=CalibrationPipeline)
    history: CalibrationHistory = field(default_factory=CalibrationHistory)

    # State tracking
    state: CalibrationState = field(default_factory=CalibrationState)
    result: CalibrationResult | None = None

    # Event bus (optional — for cross-layer communication)
    event_bus: EventBus | None = None

    # Session metadata
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    tags: list[str] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)

    # Phase 6.2 domain entity (typed)
    domain_session: DomainSession | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.domain_session is None:
            try:
                dom_method = DomainMethod(self.state.current_method.value)
            except Exception:
                dom_method = DomainMethod.MANUAL
            dom_status = _STATUS_MAP.get(self.state.status, DomainStatus.CREATED)
            self.domain_session = DomainSession(
                session_id=self.id,
                name=self.name,
                status=dom_status,
                projector_id=self.active_projector_id,
                camera_id=self.active_camera_id,
                surface_id=self.active_surface_id,
                method=dom_method,
                created_at=self.created_at,
            )

    def _sync_domain_status(self, status: CalibrationStatus) -> None:
        if self.domain_session is None:
            return
        dom = _STATUS_MAP.get(status, DomainStatus.CREATED)
        try:
            self.domain_session.transition(dom)
        except ValueError as exc:
            _logger.warning(
                "Rejected domain transition %s → %s: %s",
                self.domain_session.status.value,
                dom.value,
                exc,
            )
        # sync IDs
        object.__setattr__(
            self.domain_session, "projector_id", self.active_projector_id
        )
        object.__setattr__(self.domain_session, "camera_id", self.active_camera_id)
        object.__setattr__(self.domain_session, "surface_id", self.active_surface_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, method: CalibrationMethod = CalibrationMethod.MANUAL) -> None:
        """Begin a calibration session with the given method.

        Transitions state to PREPARING and emits ``CalibrationStarted``.
        """
        if self.state.status != CalibrationStatus.IDLE:
            msg = f"Cannot start session in state: {self.state.status}"
            raise RuntimeError(msg)

        self.state.status = CalibrationStatus.PREPARING
        self._sync_domain_status(CalibrationStatus.PREPARING)
        self.state.current_method = method
        if self.domain_session is not None:
            object.__setattr__(
                self.domain_session,
                "method",
                DomainMethod(method.value)
                if method.value in [m.value for m in DomainMethod]
                else DomainMethod.MANUAL,
            )
        self.state.started_at = time.time()
        if self.state.data is None:
            from projectionai.calibration.types import (
                CalibrationData as _CalibrationData,
            )

            self.state.data = _CalibrationData()
        self.state.data.method = method

        _logger.info("Calibration session %s started (method=%s)", self.id, method)
        if self.event_bus:
            await self.event_bus.emit(CalibrationStarted(scene_id=self.id))

    async def cancel(self) -> None:
        """Cancel the running calibration session."""
        if self.state.status in (CalibrationStatus.COMPLETED, CalibrationStatus.FAILED):
            return
        self.state.status = CalibrationStatus.CANCELLED
        self._sync_domain_status(CalibrationStatus.CANCELLED)
        _logger.info("Calibration session %s cancelled", self.id)

    async def fail(self, reason: str) -> None:
        """Mark the session as failed with a reason."""
        self.state.status = CalibrationStatus.FAILED
        self._sync_domain_status(CalibrationStatus.FAILED)
        self.state.errors.append(reason)
        if self.domain_session is not None:
            object.__setattr__(
                self.domain_session, "errors", (*self.domain_session.errors, reason)
            )
        self.completed_at = time.time()
        _logger.warning("Calibration session %s failed: %s", self.id, reason)
        if self.event_bus:
            await self.event_bus.emit(
                CalibrationFailed(scene_id=self.id, reason=reason)
            )

    def finalize(self) -> CalibrationResult:
        """Finalise the session and produce a ``CalibrationResult``.

        Returns:
            The calibration result (success or failure).
        """
        if self.state.status not in (
            CalibrationStatus.COMPLETED,
            CalibrationStatus.FAILED,
            CalibrationStatus.CANCELLED,
        ):
            self.state.status = CalibrationStatus.COMPLETED
            self._sync_domain_status(CalibrationStatus.COMPLETED)
        else:
            self._sync_domain_status(self.state.status)

        self.completed_at = time.time()
        self.state.elapsed_seconds = self.completed_at - self.state.started_at
        if self.state.data is not None:
            self.state.data.duration_ms = self.state.elapsed_seconds * 1000.0

        success = (
            self.state.status == CalibrationStatus.COMPLETED
            and len(self.state.errors) == 0
        )

        self.result = CalibrationResult(
            success=success,
            data=self.state.data,
            validation_errors=list(self.state.errors),
            validation_warnings=list(self.state.warnings),
            quality_score=self._compute_quality_score(),
            error_message=self.state.errors[0] if self.state.errors else "",
        )

        # Store in history
        self.history.add_entry(self.result, session_name=self.name)

        if self.event_bus and success:
            from projectionai.core.events import (
                CalibrationComplete as CoreCalibrationComplete,
            )

            self._emit_nowait(CoreCalibrationComplete(scene_id=self.id))

        return self.result

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def update_progress(
        self,
        progress: float,
        status_text: str = "",
        stage: str = "",
    ) -> None:
        """Update progress of the current calibration.

        Args:
            progress: Value from 0.0 to 1.0.
            status_text: Human-readable status message.
            stage: Current pipeline stage name.
        """
        self.state.progress = max(0.0, min(1.0, progress))
        self.state.status_text = status_text
        if stage:
            self.state.current_stage = stage
        self.state.elapsed_seconds = time.time() - self.state.started_at

        if self.event_bus:
            self._emit_nowait(
                CalibrationProgress(
                    scene_id=self.id,
                    progress=self.state.progress,
                    status=status_text,
                )
            )

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def set_data(self, field: str, value: Any) -> None:
        """Set a field on the calibration data and emit change event."""
        if self.state.data is None:
            self.state.data = CalibrationData()
        setattr(self.state.data, field, value)
        if self.event_bus:
            self._emit_nowait(CalibrationDataChanged(session_id=self.id, field=field))

    def get_data(self, field: str) -> Any:
        """Get a field from the calibration data."""
        if self.state.data is None:
            self.state.data = CalibrationData()
        return getattr(self.state.data, field, None)

    @property
    def is_active(self) -> bool:
        """Return ``True`` if calibration is in progress."""
        return self.state.status in (
            CalibrationStatus.PREPARING,
            CalibrationStatus.ACQUIRING,
            CalibrationStatus.PROCESSING,
            CalibrationStatus.VALIDATING,
        )

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since the session started."""
        if self.state.started_at == 0.0:
            return 0.0
        return time.time() - self.state.started_at

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_quality_score(self) -> float:
        """Compute an overall quality score from available metrics.

        Returns a value between 0.0 (worst) and 1.0 (best).
        """
        data = self.state.data
        if data is None:
            return 0.0

        score = 1.0

        # Penalise high reprojection error
        if data.reprojection_error > 0.0:
            error_penalty = min(data.reprojection_error / 10.0, 0.5)
            score -= error_penalty

        # Penalise low confidence
        if data.confidence > 0.0:
            score *= data.confidence

        # Penalise few samples
        if data.num_samples > 0 and data.num_samples < 5:
            score -= 0.1 * (5 - data.num_samples)

        # Reduce by warnings
        score -= len(self.state.warnings) * 0.05

        return max(0.0, min(1.0, score))

    def _emit_nowait(self, event: Any) -> None:
        """Fire-and-forget event emission."""
        if self.event_bus is None:
            return
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            task = loop.create_task(self.event_bus.emit(event))
            task.add_done_callback(self._on_emit_done)
        except RuntimeError:
            pass

    def _on_emit_done(self, task: Any) -> None:
        """Done callback for fire-and-forget event emission."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _logger.warning("Emission failed in session %s: %s", self.id, exc)
