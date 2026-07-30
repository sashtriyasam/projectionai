"""SelectionPass — renders selection highlights and outlines."""

from __future__ import annotations

from typing import Any

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass


class SelectionPass(RenderPass):
    """Renders selection highlights over selected objects.

    Uses a dedicated shader that renders a translucent overlay on
    selected geometry. Companion to ScenePass — runs after scene
    rendering to overlay selection colours.
    """

    def __init__(self, name: str = "selection") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._selection_color: tuple[float, float, float, float] = (0.0, 0.6, 1.0, 0.3)
        self._selected_objects: set[int] = set()  # IDs of selected objects

    @property
    def selection_color(self) -> tuple[float, float, float, float]:
        return self._selection_color

    @selection_color.setter
    def selection_color(self, value: tuple[float, float, float, float]) -> None:
        self._selection_color = value

    @property
    def selected_objects(self) -> set[int]:
        return self._selected_objects

    @selected_objects.setter
    def selected_objects(self, value: set[int]) -> None:
        self._selected_objects = value

    def setup(self, ctx: Any, width: int, height: int) -> None:
        from projectionai.infrastructure.renderer.shader import Shader

        self._shader = Shader(ctx, "selection")

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        if self._shader is None or not self._selected_objects:
            return
        target = self._target
        if target is None:
            return
        target.bind()

        import moderngl

        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        ctx.wireframe = False

        view = camera.view_matrix
        proj = camera.projection_matrix

        self._shader.use()
        self._shader.set_mat4("u_view", view)
        self._shader.set_mat4("u_projection", proj)
        self._shader.set_vec4("u_selection_color", *self._selection_color)

        # Render selected objects
        try:
            objects = scene.renderables if hasattr(scene, "renderables") else []
        except Exception:
            objects = []

        for obj in objects:
            obj_id = id(obj)
            if obj_id not in self._selected_objects:
                continue

            model = getattr(obj, "model_matrix", None)
            if model is not None:
                self._shader.set_mat4("u_model", model)

            mesh_renderer = getattr(obj, "mesh_renderer", None)
            if mesh_renderer is not None:
                mesh_renderer.render(moderngl.TRIANGLES)

        ctx.disable(moderngl.BLEND)

    def release(self) -> None:
        if self._shader:
            self._shader.release()
            self._shader = None
