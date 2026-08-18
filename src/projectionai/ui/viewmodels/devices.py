"""DevicesViewModel — cameras and projector outputs for the Devices panel.

Qt-free. Camera enumeration is async on the manager side, so the
viewmodel caches the last refresh and exposes it as a snapshot; widgets
call ``refresh_cameras()`` through a worker task and then re-render on
``revision``. Live preview keeps only the newest captured frame —
widgets poll ``latest_frame()`` on a timer and report rendered frames
with ``mark_frame_rendered()`` so stale frames can be counted as
dropped. Projector outputs are injected by the app shell
(``update_projectors()``) — there is no projector backend yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from projectionai.core.errors import (
    CameraCaptureError,
    CameraDisconnectedError,
    CameraError,
    CameraNotFoundError,
    CameraOpenError,
    CameraUnavailableError,
)
from projectionai.core.events import (
    CameraCaptureFailed,
    CameraClosed,
    CameraDisconnected,
    Event,
)
from projectionai.managers.camera_manager import CameraManager
from projectionai.services.camera import CameraInfo, Frame
from projectionai.ui.viewmodels.observable import Observable


class ProjectorState(StrEnum):
    """Projector output state."""

    IDLE = "idle"
    LIVE = "live"
    BLACKOUT = "blackout"


@dataclass(frozen=True)
class ProjectorDevice:
    """Display output available for projection (shell-injected)."""

    name: str
    resolution: tuple[int, int] = (1920, 1080)
    state: ProjectorState = ProjectorState.IDLE
    edge_blend_group: str = ""


def _friendly_camera_error(exc: CameraError) -> str:
    """Map a camera exception to a short, user-facing message."""
    if isinstance(exc, CameraNotFoundError):
        return "Camera not found"
    if isinstance(exc, CameraOpenError):
        return "Could not open camera"
    if isinstance(exc, CameraUnavailableError):
        return "Camera unavailable (in use or disconnected)"
    if isinstance(exc, CameraDisconnectedError):
        return "Camera disconnected"
    if isinstance(exc, CameraCaptureError):
        return "Frame capture failed"
    return str(exc) or "Camera error"


class DevicesViewModel(Observable):
    """Observable camera/projector device facade."""

    def __init__(self, camera_manager: CameraManager) -> None:
        super().__init__()
        self._cameras = camera_manager
        self._camera_infos: tuple[CameraInfo, ...] = ()
        self._projectors: list[ProjectorDevice] = []
        # -- Live preview state -------------------------------------------
        self._preview_camera_id: str | None = None
        self._preview_fps: int = 30
        self._latest_frame: Frame | None = None
        self._rendered_frame_number: int = -1
        self._frame_count: int = 0
        self._dropped_count: int = 0
        self._preview_error: str | None = None
        self._cameras.event_bus.subscribe(
            CameraDisconnected, self._on_camera_disconnected
        )
        self._cameras.event_bus.subscribe(CameraClosed, self._on_camera_closed)
        self._cameras.event_bus.subscribe(
            CameraCaptureFailed, self._on_camera_capture_failed
        )

    # -- Cameras --------------------------------------------------------------

    def cameras(self) -> list[CameraInfo]:
        """Last enumerated camera metadata snapshot."""
        return list(self._camera_infos)

    @property
    def camera_count(self) -> int:
        """Number of detected cameras in the last refresh."""
        return len(self._camera_infos)

    async def refresh_cameras(self) -> int:
        """Re-enumerate cameras; returns the number detected."""
        try:
            infos = await self._cameras.list_cameras()
        except CameraError:
            return 0
        self._camera_infos = tuple(infos)
        self._notify()
        return len(self._camera_infos)

    def is_open(self, camera_id: str) -> bool:
        """Return whether *camera_id* is currently open."""
        return self._cameras.is_open(camera_id)

    async def open_camera(self, camera_id: str) -> bool:
        """Open a camera; returns True on success."""
        try:
            await self._cameras.open_camera(camera_id)
        except CameraError:
            return False
        self._notify()
        return True

    async def close_camera(self, camera_id: str) -> None:
        """Close a camera."""
        try:
            await self._cameras.close_camera(camera_id)
        except CameraError:
            return
        self._notify()

    # -- Live preview --------------------------------------------------------

    @property
    def preview_camera_id(self) -> str | None:
        """Camera id currently streaming preview frames (``None`` when idle)."""
        return self._preview_camera_id

    @property
    def preview_fps(self) -> int:
        """Requested preview frame rate."""
        return self._preview_fps

    @property
    def frame_count(self) -> int:
        """Number of frames delivered since the preview started."""
        return self._frame_count

    @property
    def dropped_count(self) -> int:
        """Frames skipped by the renderer since the preview started."""
        return self._dropped_count

    def is_previewing(self, camera_id: str) -> bool:
        """Return whether *camera_id* is the active preview source."""
        return self._preview_camera_id == camera_id

    def preview_error(self) -> str | None:
        """Friendly message for the latest preview failure, if any."""
        return self._preview_error

    def latest_frame(self) -> Frame | None:
        """Newest captured frame for the active preview (``None`` when idle)."""
        return self._latest_frame

    def mark_frame_rendered(self, frame_number: int) -> None:
        """Record that the renderer displayed frame *frame_number*."""
        self._rendered_frame_number = frame_number

    async def start_preview(self, camera_id: str, fps: int = 30) -> bool:
        """Start streaming preview frames from *camera_id*; returns True on success.

        Starting the same camera again is a no-op. Starting a different
        camera stops the previous preview first. On failure the view
        model stays idle and :meth:`preview_error` reports why.
        """
        if self._preview_camera_id == camera_id:
            return True
        await self.stop_preview()
        try:
            self._cameras.subscribe_frames(camera_id, self._on_frame)
            await self._cameras.start_capture(camera_id, fps=fps)
        except CameraError as exc:
            self._cameras.unsubscribe_frames(camera_id, self._on_frame)
            self._preview_error = _friendly_camera_error(exc)
            self._notify()
            return False
        self._preview_camera_id = camera_id
        self._preview_fps = fps
        self._preview_error = None
        self._reset_preview_state()
        self._notify()
        return True

    async def stop_preview(self) -> None:
        """Stop the active preview (no-op when idle)."""
        camera_id = self._preview_camera_id
        if camera_id is None:
            return
        self._preview_camera_id = None
        self._cameras.unsubscribe_frames(camera_id, self._on_frame)
        await self._cameras.stop_capture(camera_id)
        self._preview_error = None
        self._reset_preview_state()
        self._notify()

    def _on_frame(self, frame: Frame) -> None:
        """Keep only the newest frame; count unrendered ones as dropped."""
        if self._preview_camera_id is None:
            return
        self._preview_error = None
        if (
            self._latest_frame is not None
            and self._latest_frame.frame_number != self._rendered_frame_number
        ):
            self._dropped_count += 1
        self._latest_frame = frame
        self._frame_count += 1

    def _reset_preview_state(self) -> None:
        self._latest_frame = None
        self._rendered_frame_number = -1
        self._frame_count = 0
        self._dropped_count = 0

    async def _on_camera_disconnected(self, event: Event) -> None:
        if (
            isinstance(event, CameraDisconnected)
            and event.camera_id == self._preview_camera_id
        ):
            self._preview_error = "Camera disconnected"
            await self._teardown_preview(event.camera_id)

    async def _on_camera_closed(self, event: Event) -> None:
        if (
            isinstance(event, CameraClosed)
            and event.camera_id == self._preview_camera_id
        ):
            self._preview_error = None
            await self._teardown_preview(event.camera_id)

    async def _on_camera_capture_failed(self, event: Event) -> None:
        if (
            isinstance(event, CameraCaptureFailed)
            and event.camera_id == self._preview_camera_id
        ):
            self._preview_error = _friendly_camera_error(
                CameraCaptureError(event.reason)
            )
            self._notify()

    async def _teardown_preview(self, camera_id: str) -> None:
        """Clear preview state after a close/disconnect (capture already stopped)."""
        self._preview_camera_id = None
        self._cameras.unsubscribe_frames(camera_id, self._on_frame)
        self._reset_preview_state()
        self._notify()

    def shutdown(self) -> None:
        """Unsubscribe from camera events (idempotent).

        Called by the application shell during teardown so this view
        model stops reacting to camera events once the UI is gone.
        """
        bus = self._cameras.event_bus
        bus.unsubscribe(CameraDisconnected, self._on_camera_disconnected)
        bus.unsubscribe(CameraClosed, self._on_camera_closed)
        bus.unsubscribe(CameraCaptureFailed, self._on_camera_capture_failed)

    # -- Projectors (shell-injected) ------------------------------------------

    def projectors(self) -> list[ProjectorDevice]:
        """Projector outputs registered by the application shell."""
        return list(self._projectors)

    @property
    def projector_count(self) -> int:
        """Number of registered projector outputs."""
        return len(self._projectors)

    def update_projectors(self, projectors: list[ProjectorDevice]) -> None:
        """Replace the projector output list."""
        self._projectors = list(projectors)
        self._notify()
