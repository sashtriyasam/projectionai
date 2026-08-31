"""PreviewViewModel — manages warp preview lifecycle and content.

Qt-free. Widgets subscribe to change callbacks or poll ``revision``.
The preview state machine is self-contained and does NOT drive OutputManager.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

import numpy as np

from projectionai.domain.calibration_session import CalibrationResult
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.warp_mesh import WarpMesh
from projectionai.services.calibration import (
    calibration_to_warp_mesh,
    create_projection_mapping,
)
from projectionai.ui.theme import STATE_COLORS

_logger = logging.getLogger(__name__)


class PreviewState(StrEnum):
    """Lifecycle state of the warp preview."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    FROZEN = "frozen"
    BLACKOUT = "blackout"
    ERROR = "error"
    CLOSED = "closed"


class PreviewContent(StrEnum):
    """Preview content types rendered through the warp mesh."""

    IDENTITY = "identity"
    CHECKERBOARD = "checkerboard"
    GRID = "grid"
    CROSSHAIR = "crosshair"
    BORDER = "border"
    CORNER_MARKERS = "corner_markers"
    COLOR_BARS = "color_bars"
    GRADIENT = "gradient"


ChangeHandler = Callable[[PreviewState, PreviewState], None]

#: Valid state transitions. Missing entries are rejected.
_VALID_TRANSITIONS: dict[PreviewState, set[PreviewState]] = {
    PreviewState.IDLE: {PreviewState.LOADING, PreviewState.CLOSED},
    PreviewState.LOADING: {
        PreviewState.READY,
        PreviewState.ERROR,
        PreviewState.CLOSED,
    },
    PreviewState.READY: {
        PreviewState.RUNNING,
        PreviewState.BLACKOUT,
        PreviewState.CLOSED,
    },
    PreviewState.RUNNING: {
        PreviewState.FROZEN,
        PreviewState.BLACKOUT,
        PreviewState.READY,
        PreviewState.CLOSED,
    },
    PreviewState.FROZEN: {
        PreviewState.RUNNING,
        PreviewState.READY,
        PreviewState.BLACKOUT,
        PreviewState.CLOSED,
    },
    PreviewState.BLACKOUT: {
        PreviewState.RUNNING,
        PreviewState.FROZEN,
        PreviewState.READY,
        PreviewState.CLOSED,
    },
    PreviewState.ERROR: {PreviewState.IDLE, PreviewState.CLOSED},
    PreviewState.CLOSED: set(),
}


class MeshDiagnostics:
    """Diagnostics for the active warp mesh."""

    __slots__ = (
        "face_count",
        "generation_method",
        "grid_cols",
        "grid_rows",
        "has_inf",
        "has_nan",
        "projector_uv_range",
        "vertex_count",
    )

    def __init__(self, mesh: WarpMesh) -> None:
        self.vertex_count: int = mesh.num_vertices
        self.face_count: int = mesh.num_faces
        self.grid_rows: int = mesh.grid_rows
        self.grid_cols: int = mesh.grid_cols
        self.generation_method: str = mesh.generation_method.value

        if mesh.vertices.size > 0:
            self.has_nan = bool(np.any(np.isnan(mesh.vertices)))
            self.has_inf = bool(np.any(np.isinf(mesh.vertices)))
        else:
            self.has_nan = False
            self.has_inf = False

        if mesh.projector_uvs.size > 0:
            self.projector_uv_range = (
                float(mesh.projector_uvs.min()),
                float(mesh.projector_uvs.max()),
            )
        else:
            self.projector_uv_range = (0.0, 0.0)

    @property
    def is_valid(self) -> bool:
        """True when diagnostics pass basic sanity checks."""
        return (
            self.vertex_count > 0
            and self.face_count > 0
            and not self.has_nan
            and not self.has_inf
        )

    def summary(self) -> str:
        """Human-readable one-line summary."""
        status = "OK" if self.is_valid else "INVALID"
        return (
            f"{status}: {self.vertex_count} verts, {self.face_count} faces, "
            f"grid={self.grid_rows}x{self.grid_cols}, "
            f"uv=[{self.projector_uv_range[0]:.3f}, {self.projector_uv_range[1]:.3f}]"
        )


class PreviewViewModel:
    """Observable wrapper over the warp preview lifecycle.

    The preview is a **display-only** layer: it consumes a
    ``CalibrationResult``, converts it to a ``WarpMesh`` and
    ``ProjectionMapping``, and renders test content through the mesh.
    It does NOT call ``OutputManager.go_live()`` or ``OutputManager.arm()``.
    """

    def __init__(self) -> None:
        self._state: PreviewState = PreviewState.IDLE
        self._content: PreviewContent = PreviewContent.IDENTITY
        self._calibration_result: CalibrationResult | None = None
        self._warp_mesh: WarpMesh | None = None
        self._projection_mapping: ProjectionMapping | None = None
        self._diagnostics: MeshDiagnostics | None = None
        self._error: str | None = None
        self._handlers: list[ChangeHandler] = []
        self._revision: int = 0
        self._closed: bool = False

    # -- Observation ----------------------------------------------------------

    @property
    def revision(self) -> int:
        """Increment on every state change (cheap poll target)."""
        return self._revision

    @property
    def state(self) -> PreviewState:
        return self._state

    @property
    def content(self) -> PreviewContent:
        return self._content

    @property
    def calibration_result(self) -> CalibrationResult | None:
        return self._calibration_result

    @property
    def warp_mesh(self) -> WarpMesh | None:
        return self._warp_mesh

    @property
    def projection_mapping(self) -> ProjectionMapping | None:
        return self._projection_mapping

    @property
    def diagnostics(self) -> MeshDiagnostics | None:
        return self._diagnostics

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def label(self) -> str:
        """Human-readable state label."""
        return self._state.value.upper()

    @property
    def color(self) -> str:
        """Theme color token for the current state."""
        return STATE_COLORS.get(self._state.value, "#8A8F9C")

    @property
    def is_active(self) -> bool:
        """True when preview is READY, RUNNING, FROZEN, or BLACKOUT."""
        return self._state in {
            PreviewState.READY,
            PreviewState.RUNNING,
            PreviewState.FROZEN,
            PreviewState.BLACKOUT,
        }

    @property
    def is_displayable(self) -> bool:
        """True when preview has a valid mesh and can render."""
        return (
            self._warp_mesh is not None
            and self._projection_mapping is not None
            and self._diagnostics is not None
            and self._diagnostics.is_valid
        )

    # -- Subscription ---------------------------------------------------------

    def subscribe(self, handler: ChangeHandler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: ChangeHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    # -- Lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Release resources. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._transition(PreviewState.CLOSED)

    # -- State transitions ----------------------------------------------------

    def _transition(self, target: PreviewState) -> None:
        allowed = _VALID_TRANSITIONS.get(self._state)
        if allowed is None or target not in allowed:
            raise ValueError(
                f"Invalid preview transition {self._state.value} -> {target.value}"
            )
        old = self._state
        self._state = target
        self._revision += 1
        for handler in list(self._handlers):
            handler(old, target)

    # -- Actions --------------------------------------------------------------

    def update_from_workflow(
        self,
        calibration_result: CalibrationResult | None,
        *,
        surface_width_m: float = 1.0,
        surface_height_m: float = 1.0,
    ) -> None:
        """Accept an accepted CalibrationResult and build the warp mesh.

        Transitions IDLE -> LOADING -> READY (or ERROR on failure).

        Args:
            calibration_result: The accepted calibration result.
            surface_width_m: Physical surface width in metres (default 1.0).
            surface_height_m: Physical surface height in metres (default 1.0).
        """
        if self._state is not PreviewState.IDLE:
            _logger.warning(
                "update_from_workflow called in state %s — ignoring", self._state
            )
            return

        if calibration_result is None:
            self._error = "No calibration result provided"
            self._transition(PreviewState.LOADING)
            self._transition(PreviewState.ERROR)
            return

        self._calibration_result = calibration_result
        self._error = None
        self._transition(PreviewState.LOADING)

        try:
            self._warp_mesh = calibration_to_warp_mesh(
                calibration_result,
                surface_width_m=surface_width_m,
                surface_height_m=surface_height_m,
            )
            warp_mesh_asset_id = f"preview_warp_{self._warp_mesh.surface_id}"
            self._projection_mapping = create_projection_mapping(
                calibration_result,
                self._warp_mesh,
                warp_mesh_asset_id,
            )
            self._diagnostics = MeshDiagnostics(self._warp_mesh)
            self._transition(PreviewState.READY)
        except Exception as exc:
            _logger.exception("Failed to build warp mesh from calibration result")
            self._error = str(exc)
            self._transition(PreviewState.ERROR)

    def start(self) -> bool:
        """Start rendering (READY -> RUNNING). Returns True on success."""
        if self._state is not PreviewState.READY:
            return False
        self._transition(PreviewState.RUNNING)
        return True

    def stop(self) -> bool:
        """Stop rendering (RUNNING/FROZEN/BLACKOUT -> READY). Returns True on success."""
        if self._state in {
            PreviewState.RUNNING,
            PreviewState.FROZEN,
            PreviewState.BLACKOUT,
        }:
            self._transition(PreviewState.READY)
            return True
        return False

    def freeze(self) -> bool:
        """Freeze the current frame (RUNNING -> FROZEN). Returns True on success."""
        if self._state is not PreviewState.RUNNING:
            return False
        self._transition(PreviewState.FROZEN)
        return True

    def unfreeze(self) -> bool:
        """Unfreeze (FROZEN -> RUNNING). Returns True on success."""
        if self._state is not PreviewState.FROZEN:
            return False
        self._transition(PreviewState.RUNNING)
        return True

    def blackout(self) -> bool:
        """Blackout the preview (RUNNING/FROZEN/READY -> BLACKOUT). Returns True on success."""
        if self._state in {
            PreviewState.RUNNING,
            PreviewState.FROZEN,
            PreviewState.READY,
        }:
            self._transition(PreviewState.BLACKOUT)
            return True
        return False

    def unblackout(self) -> bool:
        """Restore from blackout (BLACKOUT -> RUNNING). Returns True on success."""
        if self._state is not PreviewState.BLACKOUT:
            return False
        self._transition(PreviewState.RUNNING)
        return True

    def reset(self) -> bool:
        """Reset to IDLE after ERROR. Returns True on success."""
        if self._state is not PreviewState.ERROR:
            return False
        self._warp_mesh = None
        self._projection_mapping = None
        self._diagnostics = None
        self._error = None
        self._calibration_result = None
        self._transition(PreviewState.IDLE)
        return True

    def set_content(self, content: PreviewContent) -> None:
        """Change the preview content type."""
        self._content = content
        self._revision += 1

    def cycle_content(self) -> None:
        """Cycle to the next content type."""
        contents = list(PreviewContent)
        idx = contents.index(self._content)
        self._content = contents[(idx + 1) % len(contents)]
        self._revision += 1
