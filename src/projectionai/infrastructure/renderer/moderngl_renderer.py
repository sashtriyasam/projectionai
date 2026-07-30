"""ModernGL-based renderer implementation."""

from __future__ import annotations

import logging
from typing import Any, override

import numpy as np
from numpy.typing import NDArray

from projectionai.core.events import EventBus
from projectionai.domain.geometry import Mesh, Pose
from projectionai.services.renderer import (
    RenderCamera,
    Renderer,
    RenderScene,
    WarpEngine,
)

_logger = logging.getLogger(__name__)


class ModernGLRenderer(Renderer):
    """Renderer using ModernGL for hardware-accelerated 3D rendering."""

    def __init__(self) -> None:
        self._ctx: Any = None

    @override
    async def initialize(self, event_bus: EventBus | None = None) -> None:
        _logger.debug("ModernGL renderer initialized")

    @override
    async def shutdown(self) -> None:
        self._ctx = None

    @override
    def render(self, scene: RenderScene) -> NDArray[np.uint8] | None:
        raise NotImplementedError(
            "ModernGLRenderer is a stub — no OpenGL context available"
        )

    @override
    def render_offscreen(self, scene: RenderScene) -> NDArray[np.uint8]:
        raise NotImplementedError(
            "ModernGLRenderer is a stub — no OpenGL context available"
        )

    @override
    def resize(self, width: int, height: int) -> None:
        _logger.debug("resize(%d, %d) — stub, no-op", width, height)


class ModernGLWarpEngine(WarpEngine):
    """Warp engine using ModernGL shaders for real-time texture warping."""

    @override
    async def initialize(self) -> None:
        _logger.debug("ModernGLWarpEngine initialized — stub, no-op")

    @override
    async def shutdown(self) -> None:
        _logger.debug("ModernGLWarpEngine shut down — stub, no-op")

    @override
    def warp(
        self,
        texture: NDArray[np.uint8],
        target_mesh: Mesh,
        source_pose: Pose,
        camera: RenderCamera,
    ) -> NDArray[np.uint8]:
        raise NotImplementedError(
            "ModernGLWarpEngine is a stub — no OpenGL context available"
        )
