"""Device selection UX model — application-level, reuses existing provider contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from projectionai.hardware.models import DisplayInfo
from projectionai.services.camera import CameraInfo


class SelectionState(StrEnum):
    AVAILABLE = "available"
    SELECTED = "selected"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class CameraSelection:
    camera_id: str
    name: str
    backend: str
    resolution: tuple[int, int]
    fps: int | None
    state: SelectionState
    is_open: bool
    error: str | None = None

    @classmethod
    def from_camera_info(
        cls,
        info: CameraInfo,
        *,
        state: SelectionState,
        is_open: bool = False,
        error: str | None = None,
        fps: int | None = None,
    ) -> CameraSelection:
        return cls(
            camera_id=info.camera_id,
            name=info.name,
            backend=info.backend,
            resolution=info.max_resolution,
            fps=fps,
            state=state,
            is_open=is_open,
            error=error,
        )


@dataclass(frozen=True)
class ProjectorSelection:
    display_id: str
    name: str
    geometry: tuple[int, int, int, int]  # x, y, w, h
    resolution: tuple[int, int]
    refresh_rate: float
    is_primary: bool
    kind: str
    supports_fullscreen: bool
    validation_ok: bool
    state: SelectionState
    error: str | None = None

    @classmethod
    def from_display_info(
        cls,
        info: DisplayInfo,
        *,
        state: SelectionState,
        validation_ok: bool = True,
        error: str | None = None,
    ) -> ProjectorSelection:
        geom = (
            info.position[0],
            info.position[1],
            info.current_mode.width,
            info.current_mode.height,
        )
        raw_kind = getattr(info.capabilities, "kind", str(info.capabilities))
        kind_str = getattr(raw_kind, "value", str(raw_kind))
        supports_fs = bool(info.capabilities.supports_fullscreen)
        is_projector = kind_str == "projector"
        if not is_projector or not supports_fs:
            validation_ok = False
            state = SelectionState.UNAVAILABLE
            if error is None:
                error = "Display not suitable for projector use — projector safety rule violation"
        return cls(
            display_id=info.display_id,
            name=info.name,
            geometry=geom,
            resolution=(info.current_mode.width, info.current_mode.height),
            refresh_rate=info.current_mode.refresh_rate,
            is_primary=info.is_primary,
            kind=kind_str,
            supports_fullscreen=supports_fs,
            validation_ok=validation_ok,
            state=state,
            error=error,
        )


@dataclass
class SelectionStore:
    """In-memory selection state — single source for camera/projector choice."""

    selected_camera_id: str | None = None
    selected_display_id: str | None = None
    selected_resolution: tuple[int, int] | None = None
    selected_backend: str | None = None

    def select_camera(self, camera_id: str | None) -> None:
        self.selected_camera_id = camera_id

    def select_display(self, display_id: str | None) -> None:
        self.selected_display_id = display_id

    def set_resolution(self, resolution: tuple[int, int] | None) -> None:
        if resolution is not None and (resolution[0] <= 0 or resolution[1] <= 0):
            raise ValueError(f"Resolution must be positive, got {resolution}")
        self.selected_resolution = resolution

    def set_backend(self, backend: str | None) -> None:
        self.selected_backend = backend

    def snapshot(self) -> dict[str, Any]:
        return {
            "camera_id": self.selected_camera_id,
            "display_id": self.selected_display_id,
            "resolution": self.selected_resolution,
            "backend": self.selected_backend,
        }
