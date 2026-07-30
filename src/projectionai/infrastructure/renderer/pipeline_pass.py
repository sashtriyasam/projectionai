"""RenderPass — abstract base for all render passes in the pipeline.

Each pass represents a single rendering stage. Passes are ordered and
executed sequentially by ``RenderPipeline``. Future passes (WarpPass,
ProjectionPass, etc.) extend this same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from projectionai.infrastructure.renderer.render_target import RenderTarget


class RenderPass(ABC):
    """A single stage in the render pipeline.

    Each pass renders to its assigned ``RenderTarget`` (screen or off-screen
    framebuffer). Passes declare their input dependencies and can be
    toggled on/off at runtime.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._enabled: bool = True
        self._target: RenderTarget | None = None
        self._visible: bool = True  # whether the result is displayed

    # -- Abstract interface ------------------------------------------------

    @abstractmethod
    def setup(self, ctx: Any, width: int, height: int) -> None:
        """Allocate GPU resources for this pass.

        Called once during pipeline initialization and again on viewport resize.
        """
        ...

    @abstractmethod
    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        """Execute the pass.

        Args:
            ctx: ModernGL context.
            scene: The scene graph / renderable objects to draw.
            camera: The active camera for view/projection transforms.
        """
        ...

    # -- Properties --------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = value

    @property
    def target(self) -> RenderTarget | None:
        return self._target

    @target.setter
    def target(self, value: RenderTarget | None) -> None:
        self._target = value

    # -- Lifecycle ---------------------------------------------------------

    def resize(self, ctx: Any, width: int, height: int) -> None:
        """Handle viewport resize. Recreates GPU resources."""
        self.release()
        self.setup(ctx, width, height)

    def release(self) -> None:
        """Release GPU resources. Override in subclasses."""
        return
