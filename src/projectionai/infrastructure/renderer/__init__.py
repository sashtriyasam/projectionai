"""Rendering engine — lightweight game-engine-style renderer for ProjectionAI.

Architecture
============
The rendering stack follows a layered design:

    Viewport (PySide6 widget)
        │
    Renderer (frame orchestrator)
        │
    RenderPipeline (ordered pass list)
        ├── BackgroundPass
        ├── GridPass
        ├── ScenePass
        ├── OverlayPass
        ├── SelectionPass
        └── DebugPass
        │
    RenderContext (ModernGL wrapper)
        │
    OpenGL 3.3 Core (ModernGL)

Every subsystem is gated behind an interface so future projection-mapping
features (WarpPass, ProjectionPass, LightingPass, etc.) can be slotted in
without modifying existing passes.
"""

from __future__ import annotations

from projectionai.infrastructure.renderer.camera import (
    Camera,
    OrbitCamera,
    OrthographicCamera,
    PerspectiveCamera,
)
from projectionai.infrastructure.renderer.context import RenderContext
from projectionai.infrastructure.renderer.framebuffer import FrameBuffer
from projectionai.infrastructure.renderer.material import Material
from projectionai.infrastructure.renderer.mesh import Mesh, MeshRenderer
from projectionai.infrastructure.renderer.pipeline import RenderPipeline
from projectionai.infrastructure.renderer.pipeline_pass import RenderPass
from projectionai.infrastructure.renderer.render_target import (
    RenderTarget,
    ScreenTarget,
)
from projectionai.infrastructure.renderer.renderer import Renderer
from projectionai.infrastructure.renderer.settings import RendererSettings
from projectionai.infrastructure.renderer.shader import Shader
from projectionai.infrastructure.renderer.statistics import RenderStatistics
from projectionai.infrastructure.renderer.texture import Texture
from projectionai.infrastructure.renderer.viewport import Viewport

__all__ = [
    # Camera
    "Camera",
    # Framebuffer
    "FrameBuffer",
    "Material",
    # Mesh
    "Mesh",
    "MeshRenderer",
    "OrbitCamera",
    "OrthographicCamera",
    "PerspectiveCamera",
    # Context & Renderer
    "RenderContext",
    # Pipeline
    "RenderPass",
    "RenderPipeline",
    "RenderStatistics",
    "RenderTarget",
    "Renderer",
    # Settings & stats
    "RendererSettings",
    "ScreenTarget",
    # Shader / Texture / Material
    "Shader",
    "Texture",
    "Viewport",
]
