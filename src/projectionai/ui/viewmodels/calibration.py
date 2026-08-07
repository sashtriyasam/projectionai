"""CalibrationViewModel — calibration sessions list and lifecycle.

Qt-free. Wraps :class:`CalibrationManager` (and through it the
``CalibrationWorkspace``) and exposes session snapshots for the
Calibration Sessions panel. Sessions progress asynchronously, so
widgets poll ``revision`` after ``refresh()``.
"""

from __future__ import annotations

from projectionai.calibration.calibration_manager import CalibrationManager
from projectionai.calibration.session import CalibrationSession
from projectionai.calibration.types import CalibrationMethod, CalibrationStatus
from projectionai.calibration.validator import ValidationReport
from projectionai.ui.viewmodels.observable import Observable


class CalibrationViewModel(Observable):
    """Observable calibration-session facade."""

    def __init__(self, calibration_manager: CalibrationManager) -> None:
        super().__init__()
        self._calibration = calibration_manager

    # -- Sessions -------------------------------------------------------------

    def sessions(self) -> list[CalibrationSession]:
        """All sessions in the workspace, newest first."""
        sessions = list(self._calibration.workspace.sessions.values())
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    @property
    def session_count(self) -> int:
        """Number of sessions in the workspace."""
        return self._calibration.workspace.session_count

    def active_session(self) -> CalibrationSession | None:
        """The currently active session, or ``None``."""
        return self._calibration.get_active_session()

    def get_session(self, session_id: str) -> CalibrationSession | None:
        """Return a session by id, or ``None``."""
        return self._calibration.get_session(session_id)

    def create_session(
        self,
        name: str = "Calibration Session",
        method: CalibrationMethod = CalibrationMethod.MANUAL,
    ) -> CalibrationSession:
        """Create a new session (becomes active)."""
        session = self._calibration.create_session(name=name, method=method)
        self._notify()
        return session

    def set_active_session(self, session_id: str) -> None:
        """Switch the active session."""
        self._calibration.workspace.set_active_session(session_id)
        self._notify()

    def archive_session(self, session_id: str) -> bool:
        """Archive a session; returns True when found."""
        archived = self._calibration.workspace.archive_session(session_id)
        if archived:
            self._notify()
        return archived

    def remove_session(self, session_id: str) -> bool:
        """Remove a session entirely; returns True when found."""
        removed = self._calibration.workspace.remove_session(session_id)
        if removed:
            self._notify()
        return removed

    # -- Session state helpers --------------------------------------------------

    @staticmethod
    def status_of(session: CalibrationSession) -> str:
        """Human-readable status of a session."""
        return str(session.state.status.value)

    @staticmethod
    def progress_of(session: CalibrationSession) -> float:
        """Progress of a session (0.0-1.0)."""
        return float(session.state.progress)

    @staticmethod
    def status_text_of(session: CalibrationSession) -> str:
        """Free-form status message of a session."""
        return session.state.status_text

    @staticmethod
    def is_finished(session: CalibrationSession) -> bool:
        """True when a session reached a terminal state."""
        return session.state.status in (
            CalibrationStatus.COMPLETED,
            CalibrationStatus.FAILED,
            CalibrationStatus.CANCELLED,
        )

    @staticmethod
    def methods() -> list[CalibrationMethod]:
        """Calibration methods offered by the New Session wizard."""
        return [
            CalibrationMethod.MANUAL,
            CalibrationMethod.ARUCO,
            CalibrationMethod.CHESSBOARD,
            CalibrationMethod.STRUCTURED_LIGHT,
            CalibrationMethod.GRAY_CODE,
        ]

    # -- Validation ------------------------------------------------------------

    def validate(self, session: CalibrationSession) -> ValidationReport:
        """Validate a session's result; returns the validation report."""
        return self._calibration.validate(session)

    def refresh(self) -> None:
        """Force a revision bump (call on a poll timer)."""
        self._notify()
