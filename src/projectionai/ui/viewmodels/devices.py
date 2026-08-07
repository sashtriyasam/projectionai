"""DevicesViewModel — cameras and projector outputs for the Devices panel.

Qt-free. Camera enumeration is async on the manager side, so the
viewmodel caches the last refresh and exposes it as a snapshot; widgets
call ``refresh_cameras()`` through a worker task and then re-render on
``revision``. Projector outputs are injected by the app shell
(``update_projectors()``) — there is no projector backend yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from projectionai.core.errors import CameraError
from projectionai.managers.camera_manager import CameraManager
from projectionai.services.camera import CameraInfo
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


class DevicesViewModel(Observable):
    """Observable camera/projector device facade."""

    def __init__(self, camera_manager: CameraManager) -> None:
        super().__init__()
        self._cameras = camera_manager
        self._camera_infos: tuple[CameraInfo, ...] = ()
        self._projectors: list[ProjectorDevice] = []

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
