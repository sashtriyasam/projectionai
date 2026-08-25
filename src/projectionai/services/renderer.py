"""Renderer abstraction.

The renderer takes a scene graph and renders it to a display surface
(viewport widget, projector output, or off-screen buffer).

Design decisions:
- The abstraction is minimal — geometry in, pixels out.
- All frame-buffer management, shader compilation, and GPU resource
  lifecycle is the implementation's responsibility.
- The scene graph is represented as a list of ``Renderable`` objects
  so the renderer does not depend on the full domain model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from projectionai.core.events import EventBus
from projectionai.domain.geometry import Mesh, Pose

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderCamera:
    """Camera definition for rendering."""

    pose: Pose
    fov_degrees: float = 60.0
    near_plane: float = 0.01
    far_plane: float = 100.0


@dataclass(frozen=True)
class RenderLight:
    """Simple light source."""

    position: tuple[float, float, float]
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0


@dataclass(frozen=True)
class Renderable:
    """A renderable object in the scene."""

    mesh: Mesh
    pose: Pose
    texture_path: str | None = None
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    wireframe: bool = False
    visible: bool = True


@dataclass(frozen=True)
class RenderScene:
    """Complete scene description for one render call."""

    objects: tuple[Renderable, ...] = ()
    camera: RenderCamera | None = None
    lights: tuple[RenderLight, ...] = ()
    background_color: tuple[float, float, float] = (0.1, 0.1, 0.1)
    width: int = 1920
    height: int = 1080
    settings: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Renderer interface
# ---------------------------------------------------------------------------


class Renderer(ABC):
    """Abstract renderer.

    Concrete implementations (ModernGL, OpenGL, Vulkan) provide the
    initialization and rendering logic.
    """

    @abstractmethod
    async def initialize(self, event_bus: EventBus | None = None) -> None:
        """Initialize the rendering context.

        Must be called from the thread that owns the GL context.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Release all GPU resources."""

    @abstractmethod
    def render(self, scene: RenderScene) -> NDArray[np.uint8] | None:
        """Render *scene* and return an RGBA image, or ``None`` if
        rendering to a window (not off-screen)."""

    @abstractmethod
    def render_offscreen(self, scene: RenderScene) -> NDArray[np.uint8]:
        """Render *scene* to an off-screen framebuffer and return
        the pixel data as an RGBA numpy array."""

    @abstractmethod
    def resize(self, width: int, height: int) -> None:
        """Handle viewport resize."""


# ---------------------------------------------------------------------------
# Warp engine — 3D scene warp (NOT projection mapping).
# ---------------------------------------------------------------------------
#
# NOTE: This WarpEngine operates on 3D scene geometry (Mesh + Pose +
#   RenderCamera).  It is the viewport/scene warp for 3D rendering,
#   NOT the projection-mapping warp.
#
# For projection mapping (WarpMesh → projector output), see:
#   services/warp_engine_cpu.ProjectionWarpEngine (CPU/native reference)
#   infrastructure/renderer/passes/projection.ProjectionPass (realtime GPU)
#
# Rule:
#   CPU/native warp engines = preprocessing/reference (offline)
#   ProjectionPass          = realtime GPU rendering (production)
# ---------------------------------------------------------------------------


class WarpEngine(ABC):
    """Warp a flat image / video onto a 3D surface (scene warp).

    This is the 3D-scene counterpart to ProjectionWarpEngine.
    Given a source texture and a 3D target mesh, compute the
    per-pixel mapping via scene camera.  Used for viewport preview,
    NOT for projector calibration/mapping.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Allocate warp resources."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release warp resources."""

    @abstractmethod
    def warp(
        self,
        texture: NDArray[np.uint8],
        target_mesh: Mesh,
        source_pose: Pose,
        camera: RenderCamera,
    ) -> NDArray[np.uint8]:
        """Return the warped texture for the given target geometry."""
