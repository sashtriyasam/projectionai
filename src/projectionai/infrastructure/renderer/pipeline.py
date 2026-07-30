"""RenderPipeline — ordered list of render passes executed each frame.

The pipeline is the central orchestration point: it owns the passes,
manages their lifecycle, and coordinates them each frame. Future passes
can be inserted at any position without modifying existing passes.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass
from projectionai.infrastructure.renderer.render_target import (
    ScreenTarget,
)

_logger = logging.getLogger(__name__)


class RenderPipeline:
    """Ordered sequence of render passes.

    Usage::

        pipeline = RenderPipeline()
        pipeline.add_pass(BackgroundPass("background"))
        pipeline.add_pass(ScenePass("scene"))
        pipeline.render(ctx, scene, camera)
    """

    def __init__(self) -> None:
        self._passes: list[RenderPass] = []
        self._pass_map: dict[str, RenderPass] = {}
        self._screen_target: ScreenTarget | None = None

    # -- Pass management ---------------------------------------------------

    def add_pass(self, pass_obj: RenderPass, *, index: int | None = None) -> RenderPass:
        """Add a render pass to the pipeline.

        Args:
            pass_obj: The pass to add.
            index: Insert position (None = append to end).

        Returns:
            The pass for chaining.
        """
        if pass_obj.name in self._pass_map:
            raise ValueError(f"Pass '{pass_obj.name}' already exists in pipeline")

        if index is not None:
            self._passes.insert(index, pass_obj)
        else:
            self._passes.append(pass_obj)
        self._pass_map[pass_obj.name] = pass_obj
        _logger.debug(
            "Pipeline: added pass '%s' at position %d",
            pass_obj.name,
            index if index is not None else len(self._passes) - 1,
        )
        return pass_obj

    def remove_pass(self, name: str) -> None:
        """Remove a pass by name."""
        if name in self._pass_map:
            pass_obj = self._pass_map.pop(name)
            self._passes.remove(pass_obj)
            pass_obj.release()

    def get_pass(self, name: str) -> RenderPass | None:
        """Look up a pass by name."""
        return self._pass_map.get(name)

    def get_pass_at(self, index: int) -> RenderPass | None:
        """Look up a pass by index."""
        if 0 <= index < len(self._passes):
            return self._passes[index]
        return None

    def move_pass(self, name: str, new_index: int) -> None:
        """Move a pass to a new position in the pipeline."""
        if name not in self._pass_map:
            return
        pass_obj = self._pass_map[name]
        self._passes.remove(pass_obj)
        self._passes.insert(new_index, pass_obj)

    @property
    def passes(self) -> list[RenderPass]:
        """All passes in execution order."""
        return list(self._passes)

    @property
    def enabled_passes(self) -> list[RenderPass]:
        """Only enabled passes."""
        return [p for p in self._passes if p.enabled]

    @property
    def pass_count(self) -> int:
        return len(self._passes)

    # -- Lifecycle ---------------------------------------------------------

    def initialize(self, ctx: Any, width: int, height: int) -> None:
        """Set up all passes (called once at startup / resize).

        Args:
            ctx: ModernGL context.
            width: Viewport width in pixels.
            height: Viewport height in pixels.
        """
        self._screen_target = ScreenTarget(ctx, width, height)
        for pass_obj in self._passes:
            try:
                pass_obj.setup(ctx, width, height)
                if pass_obj.target is None:
                    pass_obj.target = self._screen_target
            except Exception as exc:
                _logger.error("Failed to setup pass '%s': %s", pass_obj.name, exc)

    def resize(self, ctx: Any, width: int, height: int) -> None:
        """Resize all passes."""
        if self._screen_target:
            self._screen_target.resize(width, height)
        for pass_obj in self._passes:
            try:
                pass_obj.resize(ctx, width, height)
            except Exception as exc:
                _logger.error("Failed to resize pass '%s': %s", pass_obj.name, exc)

    # -- Frame execution ---------------------------------------------------

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        """Execute all enabled passes in order.

        Args:
            ctx: ModernGL context.
            scene: Scene graph / renderable objects.
            camera: Active camera.
        """
        for pass_obj in self._passes:
            if not pass_obj.enabled:
                continue
            try:
                pass_obj.render(ctx, scene, camera)
            except Exception as exc:
                _logger.error("Pass '%s' failed: %s", pass_obj.name, exc)

    def release(self) -> None:
        """Release all passes."""
        for pass_obj in self._passes:
            with contextlib.suppress(Exception):
                pass_obj.release()
        self._passes.clear()
        self._pass_map.clear()
        self._screen_target = None
