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
from projectionai.infrastructure.calibration.chessboard import (
    ChessboardCalibrationAlgorithm,
)
from projectionai.services.camera_calibration import CalibrationBoardConfig
from projectionai.ui.viewmodels.observable import Observable


class CalibrationViewModel(Observable):
    """Observable calibration-session facade."""

    def __init__(self, calibration_manager: CalibrationManager) -> None:
        super().__init__()
        self._calibration = calibration_manager
        self._running: bool = False
        self._last_run_status: str | None = None
        self._last_run_session: CalibrationSession | None = None

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

    # -- Camera calibration (run) --------------------------------------------

    def open_camera_ids(self) -> tuple[str, ...]:
        """Ids of cameras currently open, for the run picker."""
        camera_manager = self._calibration.camera_manager
        if camera_manager is None:
            return ()
        return camera_manager.open_camera_ids()

    async def run_camera_calibration(
        self,
        camera_id: str,
        *,
        session_name: str = "Camera Calibration",
        num_frames: int = 20,
    ) -> CalibrationSession:
        """Run a camera intrinsic calibration; updates run status/overlay.

        The wrapper exists so the panel can fire-and-forget the run while
        the overlay and status label follow ``_notify`` callbacks.
        """
        algorithm = ChessboardCalibrationAlgorithm(
            CalibrationBoardConfig(pattern_size=(9, 6), square_size_mm=25.0)
        )
        self._running = True
        self._last_run_status = "Running…"
        self._last_run_session = None
        self._notify()
        try:
            session = await self._calibration.run_camera_calibration(
                camera_id,
                algorithm,
                session_name=session_name,
                num_frames=num_frames,
            )
            result = session.result
            if result is not None and result.success:
                self._last_run_status = "Calibration complete"
            else:
                detail = (
                    result.error_message
                    if result is not None and result.error_message
                    else "no board detected"
                )
                self._last_run_status = f"Calibration failed: {detail}"
            self._last_run_session = session
        except Exception as exc:
            self._last_run_status = f"Calibration failed: {exc}"
        finally:
            self._running = False
            self._notify()
        last_session = self._last_run_session
        if last_session is None:
            raise RuntimeError("Calibration did not produce a session")
        return last_session

    def is_calibration_running(self) -> bool:
        """True while a camera calibration run is in flight."""
        return self._running

    def last_run_status(self) -> str | None:
        """Human-readable status of the last calibration run, if any."""
        return self._last_run_status

    def calibration_overlay(
        self,
    ) -> tuple[list[tuple[int, int]] | None, tuple[int, int] | None]:
        """Detected board corners + frame size for the overlay, if any.

        Returns ``(corners, image_size)`` from the last successful run's
        final detection, or ``(None, None)`` when there is nothing to
        draw yet.
        """
        session = self._last_run_session
        if session is None:
            return None, None
        result = session.result
        if result is None or not result.success:
            return None, None
        detections = session.state.intermediate_results.get("detections", [])
        if not detections:
            return None, None
        detection = detections[-1]
        corners = [(int(row[0]), int(row[1])) for row in detection.corners]
        return corners, detection.image_size

    # -- Validation ------------------------------------------------------------

    def validate(self, session: CalibrationSession) -> ValidationReport:
        """Validate a session's result; returns the validation report."""
        return self._calibration.validate(session)

    def refresh(self) -> None:
        """Force a revision bump (call on a poll timer)."""
        self._notify()
