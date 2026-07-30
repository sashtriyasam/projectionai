"""GridPass — renders a ground-plane reference grid."""

from __future__ import annotations

from typing import Any

import numpy as np

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass


class GridPass(RenderPass):
    """Renders a grid on the XZ plane with axis highlighting."""

    def __init__(self, name: str = "grid") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._vao: Any = None
        self._grid_size: int = 20
        self._grid_color: tuple[float, float, float] = (0.3, 0.3, 0.3)
        self._axis_color: tuple[float, float, float] = (0.5, 0.5, 0.5)
        self._fade_distance: float = 50.0

    @property
    def grid_size(self) -> int:
        return self._grid_size

    @grid_size.setter
    def grid_size(self, value: int) -> None:
        self._grid_size = value

    @property
    def grid_color(self) -> tuple[float, float, float]:
        return self._grid_color

    @grid_color.setter
    def grid_color(self, value: tuple[float, float, float]) -> None:
        self._grid_color = value

    @property
    def axis_color(self) -> tuple[float, float, float]:
        return self._axis_color

    @axis_color.setter
    def axis_color(self, value: tuple[float, float, float]) -> None:
        self._axis_color = value

    def setup(self, ctx: Any, width: int, height: int) -> None:
        from projectionai.infrastructure.renderer.shader import Shader

        self._shader = Shader(ctx, "grid")

        # Build grid line vertices
        half = self._grid_size // 2
        lines: list[float] = []
        for i in range(-half, half + 1):
            # X-axis line
            lines.extend([-half, 0.0, i, half, 0.0, i])
            # Z-axis line
            lines.extend([i, 0.0, -half, i, 0.0, half])

        verts = np.array(lines, dtype=np.float32)
        vbo = ctx.buffer(verts.tobytes())
        self._vao = ctx.vertex_array([(vbo, "3f", "in_position")], layout="lines")

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        if self._shader is None or self._vao is None:
            return
        target = self._target
        if target is None:
            return
        target.bind()

        import moderngl

        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

        self._shader.use()
        view = camera.view_matrix
        proj = camera.projection_matrix
        self._shader.set_mat4("u_view", view)
        self._shader.set_mat4("u_projection", proj)
        self._shader.set_vec3("u_grid_color", *self._grid_color)
        self._shader.set_vec3("u_axis_color", *self._axis_color)
        self._shader.set_float("u_fade_distance", self._fade_distance)

        self._vao.render(moderngl.LINES)

        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    def release(self) -> None:
        if self._shader:
            self._shader.release()
            self._shader = None
        if self._vao:
            self._vao.release()
            self._vao = None
