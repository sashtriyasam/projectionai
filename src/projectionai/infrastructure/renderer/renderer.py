"""Renderer — the central orchestrator for all rendering operations.

The Renderer owns the context, pipeline, camera, statistics, and settings.
It is the main entry point for the rendering engine.

Implements ``projectionai.services.renderer.Renderer`` for compatibility
with the existing service abstraction.
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast, override

import numpy as np
from numpy.typing import NDArray

from projectionai.core.events import EventBus
from projectionai.infrastructure.renderer.camera import (
    OrbitCamera,
    PerspectiveCamera,
)
from projectionai.infrastructure.renderer.context import RenderContext
from projectionai.infrastructure.renderer.passes import ScenePass
from projectionai.infrastructure.renderer.pipeline import RenderPipeline
from projectionai.infrastructure.renderer.settings import RendererSettings
from projectionai.infrastructure.renderer.statistics import RenderStatistics
from projectionai.services.renderer import Renderer as ServiceRenderer
from projectionai.services.renderer import RenderScene

_logger = logging.getLogger(__name__)


class Renderer(ServiceRenderer):
    """Hardware-accelerated 3D renderer using ModernGL.

    Usage::

        renderer = Renderer()
        await renderer.initialize(event_bus)

        # Each frame:
        renderer.begin_frame()
        renderer.render(scene)
        renderer.end_frame()

    Lifecycle:
        initialize() → [begin_frame → render → end_frame]xN → shutdown()
    """

    def __init__(self, settings: RendererSettings | None = None) -> None:
        super().__init__()
        self._context: RenderContext | None = None
        self._pipeline: RenderPipeline | None = None
        self._settings: RendererSettings = settings or RendererSettings()
        self._statistics: RenderStatistics = RenderStatistics()
        self._camera: OrbitCamera | None = None
        self._event_bus: EventBus | None = None
        self._width: int = self._settings.width
        self._height: int = self._settings.height
        self._initialized: bool = False
        self._scene_objects: list[Any] = []
        self._last_frame_time: float | None = None

        # Default camera
        cam = PerspectiveCamera(
            fov_degrees=60.0,
            aspect_ratio=self._width / max(self._height, 1),
        )
        cam.near = self._settings.near_plane
        cam.far = self._settings.far_plane
        self._camera = OrbitCamera(camera=cam)
        self._camera.distance = 15.0

    # -- Lifecycle ---------------------------------------------------------

    @override
    async def initialize(self, event_bus: EventBus | None = None) -> None:
        """Initialize the renderer and build the pipeline.

        The ModernGL context must already be current (e.g., inside
        ``QOpenGLWidget.initializeGL``). Call ``set_context()`` first
        if using an existing context.

        Args:
            event_bus: Optional event bus for messaging.
        """
        self._event_bus = event_bus
        self._initialized = True
        _logger.info("Renderer initialized (%dx%d)", self._width, self._height)

    def set_context(self, ctx: Any) -> None:
        """Set the ModernGL context and build the render pipeline.

        Releases the previous pipeline and render context (if any) to
        avoid leaking GPU resources when the context is recreated (e.g.
        on widget resize or display change).

        Args:
            ctx: ModernGL context object.
        """
        if self._pipeline is not None:
            self._pipeline.release()
        if self._context is not None:
            self._context.release()
        self._context = RenderContext(ctx)
        self._build_pipeline()
        _logger.info(
            "Renderer context set: %s - %s",
            self._context.vendor,
            self._context.gpu_name,
        )

    @override
    async def shutdown(self) -> None:
        """Release all GPU resources."""
        if self._pipeline:
            self._pipeline.release()
            self._pipeline = None
        if self._context:
            self._context.release()
            self._context = None
        self._initialized = False
        _logger.info("Renderer shut down")

    # -- Context access ----------------------------------------------------

    @property
    def context(self) -> RenderContext | None:
        """Current render context."""
        return self._context

    @property
    def ctx(self) -> Any:
        """Raw ModernGL context (convenience)."""
        return self._context.ctx if self._context else None

    # -- Frame lifecycle ---------------------------------------------------

    def begin_frame(self) -> None:
        """Start a new frame. Must be called before ``render()``."""
        now = time.monotonic()
        if self._last_frame_time is not None:
            dt = now - self._last_frame_time
        else:
            dt = 1.0 / 60.0  # fallback for the very first frame
        self._last_frame_time = now
        self._statistics.begin_frame()
        if self._camera:
            self._camera.update(dt=dt)

    def end_frame(self) -> None:
        """Finalize the current frame and record statistics."""
        self._statistics.end_frame()

    # -- Rendering ---------------------------------------------------------

    @override
    def render(self, scene: RenderScene) -> NDArray[np.uint8] | None:
        """Render a scene to the current framebuffer.

        Args:
            scene: Scene description (from services.renderer).

        Returns:
            ``None`` (renders to screen by default).
        """
        if not self._initialized or self._pipeline is None or self._context is None:
            return None
        if self._camera is None:
            return None

        try:
            self._pipeline.render(self._context.ctx, self._scene_objects, self._camera)
        except Exception as exc:
            _logger.error("Render error: %s", exc)

        return None

    @override
    def render_offscreen(self, scene: RenderScene) -> NDArray[np.uint8]:
        """Render to an off-screen framebuffer and return pixel data.

        Args:
            scene: Scene description (provides ``width`` and ``height``).

        Returns:
            RGBA uint8 numpy array.

        Raises:
            RuntimeError: Renderer is not initialized or no camera is set.
        """
        if not self._initialized or self._context is None or self._pipeline is None:
            raise RuntimeError("Renderer not initialized — cannot render offscreen")
        if self._camera is None:
            raise RuntimeError("No camera set — cannot render offscreen")

        ctx = self._context.ctx
        prev_fbo = ctx.fbo
        fbo = ctx.simple_framebuffer((scene.width, scene.height))
        fbo.use()
        try:
            self._context.clear()
            self._pipeline.render(ctx, self._scene_objects, self._camera)
            return np.frombuffer(fbo.read(components=4), dtype=np.uint8).reshape(
                (scene.height, scene.width, 4)
            )
        except Exception as exc:
            _logger.error("Offscreen render error: %s", exc)
            raise
        finally:
            try:
                prev_fbo.use()
            finally:
                fbo.release()

    @override
    def resize(self, width: int, height: int) -> None:
        """Handle viewport resize."""
        self._width = width
        self._height = height
        if self._pipeline and self._context:
            self._pipeline.resize(self._context.ctx, width, height)
        if self._camera:
            inner = self._camera.inner
            if isinstance(inner, PerspectiveCamera):
                inner.aspect_ratio = width / max(height, 1)
        self._settings.width = width
        self._settings.height = height
        _logger.debug("Renderer resized to %dx%d", width, height)

    # -- Scene objects -----------------------------------------------------

    def set_scene_objects(self, objects: list[Any]) -> None:
        """Set the list of renderable objects for the scene.

        Each object should have:
        - ``mesh_renderer`` (MeshRenderer)
        - ``model_matrix`` (4x4 ndarray, optional)
        - ``visible`` (bool, optional)
        - ``color`` (tuple, optional)
        - ``wireframe`` (bool, optional)
        """
        self._scene_objects = list(objects)

    # -- Camera ------------------------------------------------------------

    @property
    def camera(self) -> OrbitCamera | None:
        """Active orbit camera."""
        return self._camera

    @camera.setter
    def camera(self, value: OrbitCamera) -> None:
        self._camera = value

    # -- Pipeline ----------------------------------------------------------

    def _build_pipeline(self) -> None:
        """Create and configure the render pipeline with default passes."""
        from projectionai.infrastructure.renderer.passes import (
            BackgroundPass,
            DebugPass,
            GridPass,
            OverlayPass,
            ScenePass,
            SelectionPass,
        )

        ctx = self._context.ctx if self._context else None
        if ctx is None:
            return

        pipeline = RenderPipeline()

        # Initial passes (in render order)
        pipeline.add_pass(BackgroundPass())
        pipeline.add_pass(GridPass())
        pipeline.add_pass(ScenePass())
        pipeline.add_pass(SelectionPass())
        pipeline.add_pass(OverlayPass())
        pipeline.add_pass(DebugPass())

        pipeline.initialize(ctx, self._width, self._height)

        self._pipeline = pipeline
        self._apply_pass_settings()

    @property
    def pipeline(self) -> RenderPipeline | None:
        """Current render pipeline."""
        return self._pipeline

    # -- Settings & statistics ---------------------------------------------

    @property
    def settings(self) -> RendererSettings:
        """Current renderer settings (mutable)."""
        return self._settings

    @settings.setter
    def settings(self, value: RendererSettings) -> None:
        self._settings = value
        self.resize(value.width, value.height)
        self._apply_pass_settings()

    def _apply_pass_settings(self) -> None:
        """Apply all non-size settings to active passes and camera.

        Called after a settings change to push values to the live
        pipeline and camera without rebuilding.
        """
        if self._pipeline is None:
            return

        # Scene pass — wireframe overlay & bounding boxes
        scene_pass = cast("ScenePass | None", self._pipeline.get_pass("scene"))
        if scene_pass is not None:
            scene_pass.wireframe = self._settings.wireframe_overlay
            scene_pass.show_bounding_boxes = self._settings.show_bounding_boxes

        # Camera clipping planes
        if self._camera is not None:
            inner = self._camera.inner
            if isinstance(inner, PerspectiveCamera):
                inner.near = self._settings.near_plane
                inner.far = self._settings.far_plane

    @property
    def statistics(self) -> RenderStatistics:
        """Per-frame rendering statistics."""
        return self._statistics

    @property
    def fps(self) -> float:
        """Smoothed frames-per-second."""
        return self._statistics.fps

    @property
    def frame_time_ms(self) -> float:
        """Most recent frame time."""
        return self._statistics.frame_time_ms
