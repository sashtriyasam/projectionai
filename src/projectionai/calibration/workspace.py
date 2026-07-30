"""Calibration workspace — session management and lifecycle.

The ``CalibrationWorkspace`` manages multiple calibration sessions for a
given project. It owns the active session, handles session creation,
switching between sessions, and archival of completed sessions.

Designed for workflows where users perform multiple calibration passes
(e.g. one per projector, or iterative refinement of a single setup).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import uuid4

from projectionai.calibration.camera_model import CameraModel
from projectionai.calibration.projector_model import ProjectorModel
from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.surface_model import SurfaceModel
from projectionai.calibration.types import CalibrationMethod, CalibrationStatus
from projectionai.core.events import EventBus

_logger = logging.getLogger(__name__)


@dataclass
class CalibrationWorkspace:
    """Manages calibration sessions for a project.

    The workspace is the top-level coordination object for all calibration
    activity within a project. It holds the active projector, camera, and
    surface models, manages session lifecycle, and provides access to
    completed session results.

    Usage::

        ws = CalibrationWorkspace(event_bus=bus)
        session = ws.create_session()
        await session.start(CalibrationMethod.ARUCO)
        # ... calibration runs ...
        result = session.finalize()
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Calibration Workspace"

    # Active models (shared across sessions)
    projector: ProjectorModel = field(default_factory=ProjectorModel)
    camera: CameraModel = field(default_factory=CameraModel)
    surface: SurfaceModel = field(default_factory=SurfaceModel)

    # Sessions
    sessions: dict[str, CalibrationSession] = field(default_factory=dict)
    active_session_id: str = ""

    # Archived sessions
    archived_session_ids: list[str] = field(default_factory=list)

    event_bus: EventBus | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(
        self,
        name: str = "Calibration Session",
        method: CalibrationMethod = CalibrationMethod.MANUAL,
    ) -> CalibrationSession:
        """Create a new calibration session.

        The new session inherits the workspace's current projector,
        camera, and surface models.

        Returns:
            The newly created session (not yet started).
        """
        session = CalibrationSession(
            name=name,
            projector=self.projector,
            camera=self.camera,
            surface=self.surface,
            event_bus=self.event_bus,
        )
        session.state.current_method = method
        if session.state.data is not None:
            session.state.data.method = method

        self.sessions[session.id] = session
        self.active_session_id = session.id
        _logger.debug("Created calibration session: %s (%s)", session.id, name)
        return session

    def get_session(self, session_id: str) -> CalibrationSession | None:
        """Get a session by ID (active or archived)."""
        return self.sessions.get(session_id)

    def get_active_session(self) -> CalibrationSession | None:
        """Get the currently active session."""
        if not self.active_session_id:
            return None
        return self.sessions.get(self.active_session_id)

    def set_active_session(self, session_id: str) -> None:
        """Switch the active session."""
        if session_id in self.sessions:
            self.active_session_id = session_id

    def archive_session(self, session_id: str) -> bool:
        """Archive a completed session.

        Archived sessions are preserved but no longer active.

        Returns:
            ``True`` if the session was found and archived.
        """
        if session_id not in self.sessions:
            return False
        if session_id not in self.archived_session_ids:
            self.archived_session_ids.append(session_id)
        if self.active_session_id == session_id:
            # Switch to the most recent non-archived session
            for sid in reversed(list(self.sessions.keys())):
                if sid not in self.archived_session_ids:
                    self.active_session_id = sid
                    break
            else:
                self.active_session_id = ""
        return True

    def remove_session(self, session_id: str) -> bool:
        """Remove a session entirely.

        Returns:
            ``True`` if the session was found and removed.
        """
        if session_id not in self.sessions:
            return False
        self.sessions.pop(session_id)
        self.archived_session_ids = [
            sid for sid in self.archived_session_ids if sid != session_id
        ]
        if self.active_session_id == session_id:
            for sid in reversed(list(self.sessions.keys())):
                if sid not in self.archived_session_ids:
                    self.active_session_id = sid
                    break
            else:
                self.active_session_id = ""
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def session_count(self) -> int:
        """Total number of sessions (active + archived)."""
        return len(self.sessions)

    @property
    def active_session(self) -> CalibrationSession | None:
        """Alias for ``get_active_session()``."""
        return self.get_active_session()

    def get_sessions_by_method(
        self, method: CalibrationMethod
    ) -> list[CalibrationSession]:
        """Return all sessions using a specific method."""
        return [s for s in self.sessions.values() if s.state.current_method == method]

    def get_completed_sessions(self) -> list[CalibrationSession]:
        """Return all completed sessions."""
        return [
            s
            for s in self.sessions.values()
            if s.state.status == CalibrationStatus.COMPLETED
        ]
