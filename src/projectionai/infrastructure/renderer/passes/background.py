"""BackgroundPass — fills the render target with a gradient or solid colour."""

from __future__ import annotations

from typing import Any

import numpy as np

from projectionai.infrastructure.renderer.mesh import Mesh
from projectionai.infrastructure.renderer.pipeline_pass import RenderPass


class BackgroundPass(RenderPass):
    """Renders a gradient or solid-colour background.

    Uses a full-screen quad with a simple gradient shader.
    """

    def __init__(self, name: str = "background") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._vao: Any = None
        self._color_top: tuple[float, float, float] = (0.08, 0.08, 0.12)
        self._color_bottom: tuple[float, float, float] = (0.18, 0.18, 0.22)
        self._gradient: bool = True

    @property
    def color_top(self) -> tuple[float, float, float]:
        return self._color_top

    @color_top.setter
    def color_top(self, value: tuple[float, float, float]) -> None:
        self._color_top = value

    @property
    def color_bottom(self) -> tuple[float, float, float]:
        return self._color_bottom

    @color_bottom.setter
    def color_bottom(self, value: tuple[float, float, float]) -> None:
        self._color_bottom = value

    @property
    def gradient(self) -> bool:
        return self._gradient

    @gradient.setter
    def gradient(self, value: bool) -> None:
        self._gradient = value

    def setup(self, ctx: Any, width: int, height: int) -> None:
        from projectionai.infrastructure.renderer.shader import Shader

        self._shader = Shader(ctx, "background")

        # Full-screen quad (two triangles)
        Mesh.plane(2.0)
        # Rotate 90° on X so quad faces the camera
        verts = np.array(
            [
                [-1, -1, 0],
                [1, -1, 0],
                [1, 1, 0],
                [-1, -1, 0],
                [1, 1, 0],
                [-1, 1, 0],
            ],
            dtype=np.float32,
        )
        uvs = np.array(
            [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 0],
                [1, 1],
                [0, 1],
            ],
            dtype=np.float32,
        )
        buf = np.zeros(6 * (3 + 2), dtype=np.float32)
        buf[0::5] = verts[:, 0]
        buf[1::5] = verts[:, 1]
        buf[2::5] = verts[:, 2]
        buf[3::5] = uvs[:, 0]
        buf[4::5] = uvs[:, 1]
        vbo = ctx.buffer(buf.tobytes())
        self._vao = ctx.vertex_array([(vbo, "3f 2f", "in_position", "in_uv")])

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        if self._shader is None or self._vao is None:
            return
        target = self._target
        if target is None:
            return
        target.bind()
        target.clear(0.0, 0.0, 0.0, 1.0)

        self._shader.use()
        self._shader.set_vec3("u_color_top", *self._color_top)
        self._shader.set_vec3("u_color_bottom", *self._color_bottom)
        self._shader.set_int("u_gradient", 1 if self._gradient else 0)
        self._vao.render()

    def release(self) -> None:
        if self._shader:
            self._shader.release()
            self._shader = None
        if self._vao:
            self._vao.release()
            self._vao = None
