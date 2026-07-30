"""DebugPass — renders bounding boxes, normals, and other debug visualisations."""

from __future__ import annotations

from typing import Any

import numpy as np

from projectionai.infrastructure.renderer.pipeline_pass import RenderPass


class DebugPass(RenderPass):
    """Renders debug overlays: bounding boxes, axes, and normals.

    Designed to be enabled/disabled at runtime from the settings panel.
    """

    def __init__(self, name: str = "debug") -> None:
        super().__init__(name)
        self._shader: Any = None
        self._bbox_vao: Any = None
        self._show_bounding_boxes: bool = False
        self._show_normals: bool = False
        self._bb_color: tuple[float, float, float, float] = (0.0, 1.0, 0.0, 1.0)
        self._normal_color: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 1.0)

        # Shared wireframe cube for bounding boxes
        self._cube_verts: Any = None
        self._cube_vbo: Any = None

    @property
    def show_bounding_boxes(self) -> bool:
        return self._show_bounding_boxes

    @show_bounding_boxes.setter
    def show_bounding_boxes(self, value: bool) -> None:
        self._show_bounding_boxes = value

    @property
    def show_normals(self) -> bool:
        return self._show_normals

    @show_normals.setter
    def show_normals(self, value: bool) -> None:
        self._show_normals = value

    def setup(self, ctx: Any, width: int, height: int) -> None:
        from projectionai.infrastructure.renderer.shader import Shader

        self._shader = Shader(ctx, "debug")

        # Unit cube wireframe (12 edges)
        corners = np.array(
            [
                [-1, -1, -1],
                [1, -1, -1],
                [1, 1, -1],
                [-1, 1, -1],
                [-1, -1, 1],
                [1, -1, 1],
                [1, 1, 1],
                [-1, 1, 1],
            ],
            dtype=np.float32,
        )
        edges = np.array(
            [
                [0, 1],
                [1, 2],
                [2, 3],
                [3, 0],
                [4, 5],
                [5, 6],
                [6, 7],
                [7, 4],
                [0, 4],
                [1, 5],
                [2, 6],
                [3, 7],
            ],
            dtype=np.uint32,
        )

        line_verts = corners[edges.flatten()]
        colors = np.tile(
            np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32), (len(line_verts), 1)
        )
        buf = np.zeros(len(line_verts) * (3 + 4), dtype=np.float32)
        buf[0::7] = line_verts[:, 0]
        buf[1::7] = line_verts[:, 1]
        buf[2::7] = line_verts[:, 2]
        buf[3::7] = colors[:, 0]
        buf[4::7] = colors[:, 1]
        buf[5::7] = colors[:, 2]
        buf[6::7] = colors[:, 3]

        self._cube_vbo = ctx.buffer(buf.tobytes())
        self._bbox_vao = ctx.vertex_array(
            [(self._cube_vbo, "3f 4f", "in_position", "in_color")], layout="lines"
        )

    def render(self, ctx: Any, scene: Any, camera: Any) -> None:
        if self._shader is None or not (
            self._show_bounding_boxes or self._show_normals
        ):
            return
        if self._bbox_vao is None:
            return
        target = self._target
        if target is None:
            return
        target.bind()

        import moderngl

        ctx.disable(moderngl.CULL_FACE)
        ctx.enable(moderngl.DEPTH_TEST)

        view = camera.view_matrix
        proj = camera.projection_matrix

        self._shader.use()
        self._shader.set_mat4("u_view", view)
        self._shader.set_mat4("u_projection", proj)

        if self._show_bounding_boxes:
            try:
                objects = scene.renderables if hasattr(scene, "renderables") else []
            except Exception:
                objects = []

            for obj in objects:
                mesh = getattr(obj, "mesh", None)
                if mesh is None:
                    continue
                bbox_min, bbox_max = mesh.bounding_box
                center = (bbox_min + bbox_max) * 0.5
                scale = (bbox_max - bbox_min) * 0.5

                model = np.eye(4, dtype=np.float32)
                model[:3, 3] = center
                model[0, 0] = scale[0] if scale[0] > 0 else 0.01
                model[1, 1] = scale[1] if scale[1] > 0 else 0.01
                model[2, 2] = scale[2] if scale[2] > 0 else 0.01

                self._shader.set_mat4(
                    "u_model" if "u_model" in self._shader else "u_view", model
                )
                self._shader.set_mat4("u_view", view)
                self._shader.set_mat4("u_projection", proj)
                self._bbox_vao.render(moderngl.LINES)

        ctx.enable(moderngl.CULL_FACE)

    def release(self) -> None:
        if self._shader:
            self._shader.release()
            self._shader = None
        if self._cube_vbo:
            self._cube_vbo.release()
            self._cube_vbo = None
        if self._bbox_vao:
            self._bbox_vao.release()
            self._bbox_vao = None
