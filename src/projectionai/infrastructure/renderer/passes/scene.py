"""ScenePass — renders the main scene geometry (meshes)."""

from __future__ import annotations

from typing import Any

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass
from projectionai.infrastructure.renderer.shader import Shader


class ScenePass(RenderPass):
    """Renders scene objects with the active camera.

    Supports wireframe overlay, selection highlighting, and
    per-object visibility / layer filtering.
    """

    def __init__(self, name: str = "scene") -> None:
        super().__init__(name)
        self._shader: Shader | None = None
        self._wireframe: bool = False
        self._show_bounding_boxes: bool = False

    @property
    def wireframe(self) -> bool:
        return self._wireframe

    @wireframe.setter
    def wireframe(self, value: bool) -> None:
        self._wireframe = value

    @property
    def show_bounding_boxes(self) -> bool:
        return self._show_bounding_boxes

    @show_bounding_boxes.setter
    def show_bounding_boxes(self, value: bool) -> None:
        self._show_bounding_boxes = value

    def setup(self, ctx: Any, width: int, height: int) -> None:
        from projectionai.infrastructure.renderer.shader import (
            Shader as _Shader,
        )

        self._shader = _Shader(ctx, "mesh")

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        if self._shader is None:
            return
        target = self._target
        if target is None:
            return
        target.bind()

        import moderngl

        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.CULL_FACE)

        view = camera.view_matrix
        proj = camera.projection_matrix

        self._shader.use()
        self._shader.set_mat4("u_view", view)
        self._shader.set_mat4("u_projection", proj)
        self._shader.set_int("u_wireframe", 1 if self._wireframe else 0)

        # Render each visible object
        self._render_scene_objects(scene)

    def _render_scene_objects(self, scene: Any) -> None:
        """Iterate scene objects and issue draw calls.

        Args:
            scene: Scene object with ``renderables`` iterable.

        Returns:
            None.
        """
        if self._shader is None:
            return

        objects = scene if isinstance(scene, (list, tuple)) else []

        for obj in objects:
            # Visibility check
            visible = True
            if hasattr(obj, "visible"):
                visible = obj.visible
            if not visible:
                continue

            # Layer filtering
            layer = getattr(obj, "layer", 0)
            if hasattr(scene, "visible_layers") and layer not in scene.visible_layers:
                continue

            # Model matrix
            model = getattr(obj, "model_matrix", None)
            if model is not None:
                self._shader.set_mat4("u_model", model)

            # Color
            color = getattr(obj, "color", (1.0, 1.0, 1.0, 1.0))
            if len(color) == 3:
                color = (color[0], color[1], color[2], 1.0)
            self._shader.set_vec4("u_color", *color)

            # Draw
            mesh_renderer = getattr(obj, "mesh_renderer", None)
            if mesh_renderer is not None:
                import moderngl

                mode = (
                    moderngl.LINES
                    if getattr(obj, "wireframe", False)
                    else moderngl.TRIANGLES
                )
                mesh_renderer.render(mode)

    def release(self) -> None:
        if self._shader:
            self._shader.release()
            self._shader = None
