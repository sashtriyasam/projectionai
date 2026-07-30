"""Mesh and MeshRenderer — geometry data and GPU drawable.

Provides:
- ``Mesh``: CPU-side vertex data with bounding-box computation.
- ``MeshRenderer``: GPU-side VAO / VBO management for ModernGL.
"""

from __future__ import annotations

import contextlib
import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CPU-side Mesh
# ---------------------------------------------------------------------------


@dataclass
class Mesh:
    """Vertex geometry data stored on the CPU.

    Supports:
    - Vertices (required)
    - Normals (optional, computed if missing)
    - UV coordinates (optional)
    - Vertex colours (optional)
    - Indices (optional, for indexed rendering)
    - Bounding box (computed on creation)
    """

    vertices: NDArray[np.float32]
    """(N, 3) float32 vertex positions."""

    normals: NDArray[np.float32] | None = None
    """(N, 3) float32 vertex normals."""

    uvs: NDArray[np.float32] | None = None
    """(N, 2) float32 texture coordinates."""

    colors: NDArray[np.float32] | None = None
    """(N, 4) float32 RGBA vertex colours."""

    indices: NDArray[np.uint32] | None = None
    """(M,) uint32 triangle indices (3 per triangle)."""

    vertex_count: int = 0
    """Cached vertex count (auto-computed if zero)."""

    def __post_init__(self) -> None:
        if self.vertex_count == 0 and self.vertices is not None:
            self.vertex_count = self.vertices.shape[0]
        if self.normals is None and self.vertices is not None and self.vertex_count > 0:
            self.normals = _compute_normals(self.vertices, self.indices)

    @property
    def triangle_count(self) -> int:
        """Number of triangles."""
        if self.indices is not None:
            return int(self.indices.shape[0]) // 3
        return self.vertex_count // 3

    @property
    def bounding_box(self) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """Return ``(min_corner, max_corner)`` of the axis-aligned bounding box."""
        if self.vertices is None or self.vertex_count == 0:
            return np.zeros(3, dtype=np.float32), np.ones(3, dtype=np.float32)
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    @property
    def bounding_center(self) -> NDArray[np.float32]:
        """Centre of the bounding box."""
        vmin, vmax = self.bounding_box
        return (vmin + vmax) * 0.5

    @property
    def bounding_radius(self) -> float:
        """Radius of the bounding sphere."""
        vmin, vmax = self.bounding_box
        center = (vmin + vmax) * 0.5
        return float(np.linalg.norm(vmax - center))

    @staticmethod
    def cube(size: float = 1.0) -> Mesh:
        """Create a unit cube mesh centred at origin."""
        s = size * 0.5
        verts = np.array(
            [
                [-s, -s, -s],
                [s, -s, -s],
                [s, s, -s],
                [-s, s, -s],
                [-s, -s, s],
                [s, -s, s],
                [s, s, s],
                [-s, s, s],
            ],
            dtype=np.float32,
        )
        idx = np.array(
            [
                0,
                1,
                2,
                0,
                2,
                3,
                1,
                5,
                6,
                1,
                6,
                2,
                5,
                4,
                7,
                5,
                7,
                6,
                4,
                0,
                3,
                4,
                3,
                7,
                3,
                2,
                6,
                3,
                6,
                7,
                4,
                5,
                1,
                4,
                1,
                0,
            ],
            dtype=np.uint32,
        )
        uvs = np.array(
            [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 1],
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 1],
            ],
            dtype=np.float32,
        )
        return Mesh(vertices=verts, indices=idx, uvs=uvs)

    @staticmethod
    def plane(size: float = 1.0) -> Mesh:
        """Create a flat quad mesh on the XZ plane."""
        s = size * 0.5
        verts = np.array(
            [
                [-s, 0, -s],
                [s, 0, -s],
                [s, 0, s],
                [-s, 0, s],
            ],
            dtype=np.float32,
        )
        idx = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
        norms = np.array(
            [
                [0, 1, 0],
                [0, 1, 0],
                [0, 1, 0],
                [0, 1, 0],
            ],
            dtype=np.float32,
        )
        uvs = np.array(
            [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 1],
            ],
            dtype=np.float32,
        )
        return Mesh(vertices=verts, normals=norms, indices=idx, uvs=uvs)

    @staticmethod
    def sphere(radius: float = 1.0, segments: int = 32) -> Mesh:
        """Create a UV sphere mesh."""
        verts: list[list[float]] = []
        uvs_list: list[list[float]] = []
        idx: list[int] = []

        for j in range(segments + 1):
            theta = math.pi * j / segments
            for i in range(segments + 1):
                phi = 2.0 * math.pi * i / segments
                x = radius * math.sin(theta) * math.cos(phi)
                y = radius * math.cos(theta)
                z = radius * math.sin(theta) * math.sin(phi)
                verts.append([x, y, z])
                uvs_list.append([i / segments, j / segments])

        for j in range(segments):
            for i in range(segments):
                a = j * (segments + 1) + i
                b = a + 1
                c = (j + 1) * (segments + 1) + i
                d = c + 1
                idx.extend([a, b, c, b, d, c])

        v_arr = np.array(verts, dtype=np.float32)
        norms = v_arr / (np.linalg.norm(v_arr, axis=1, keepdims=True) + 1e-30)
        return Mesh(
            vertices=v_arr,
            normals=norms.astype(np.float32),
            uvs=np.array(uvs_list, dtype=np.float32),
            indices=np.array(idx, dtype=np.uint32),
        )


def _compute_normals(
    vertices: NDArray[np.float32], indices: NDArray[np.uint32] | None
) -> NDArray[np.float32]:
    """Compute vertex normals by averaging face normals."""
    norms = np.zeros_like(vertices)
    if indices is not None:
        for i in range(0, len(indices), 3):
            a, b, c = indices[i], indices[i + 1], indices[i + 2]
            v0, v1, v2 = vertices[a], vertices[b], vertices[c]
            face_normal = np.cross(v1 - v0, v2 - v0)
            fn_len = np.linalg.norm(face_normal)
            if fn_len > 1e-30:
                face_normal /= fn_len
                norms[a] += face_normal
                norms[b] += face_normal
                norms[c] += face_normal
    else:
        # Non-indexed: each triangle is 3 consecutive vertices
        for i in range(0, len(vertices), 3):
            v0, v1, v2 = vertices[i], vertices[i + 1], vertices[i + 2]
            face_normal = np.cross(v1 - v0, v2 - v0)
            fn_len = np.linalg.norm(face_normal)
            if fn_len > 1e-30:
                face_normal /= fn_len
                norms[i] += face_normal
                norms[i + 1] += face_normal
                norms[i + 2] += face_normal
    # Normalize
    row_norms = np.linalg.norm(norms, axis=1, keepdims=True) + 1e-30
    return (norms / row_norms).astype(np.float32)


# ---------------------------------------------------------------------------
# GPU-side MeshRenderer
# ---------------------------------------------------------------------------


class MeshRenderer:
    """GPU representation of a mesh.

    Manages ModernGL vertex array objects (VAO), vertex buffer objects (VBO),
    and index buffer objects (EBO). Created once per mesh and reused each frame.
    """

    def __init__(self, ctx: Any, mesh: Mesh) -> None:
        """Upload *mesh* data to the GPU via *ctx* (ModernGL context).

        Args:
            ctx: ModernGL context object.
            mesh: CPU-side mesh data to upload.
        """
        self._ctx = ctx
        self._mesh = mesh
        self._vao: Any = None
        self._vbo: Any = None
        self._ibo: Any = None
        self._vertex_count: int = mesh.vertex_count
        self._index_count: int = len(mesh.indices) if mesh.indices is not None else 0
        self._upload()

    def _upload(self) -> None:
        """Upload vertex data to GPU buffers."""
        mesh = self._mesh

        # Build interleaved vertex buffer: pos3 + norm3 + uv2 + col4
        stride = 3 + 3 + 2 + 4
        n = mesh.vertex_count
        buf = np.zeros(n * stride, dtype=np.float32)

        # Positions (3 floats)
        buf[0::stride] = mesh.vertices[:, 0]
        buf[1::stride] = mesh.vertices[:, 1]
        buf[2::stride] = mesh.vertices[:, 2]

        # Normals (3 floats)
        norms = (
            mesh.normals
            if mesh.normals is not None
            else np.zeros((n, 3), dtype=np.float32)
        )
        buf[3::stride] = norms[:, 0]
        buf[4::stride] = norms[:, 1]
        buf[5::stride] = norms[:, 2]

        # UVs (2 floats)
        uv = mesh.uvs if mesh.uvs is not None else np.zeros((n, 2), dtype=np.float32)
        buf[6::stride] = uv[:, 0]
        buf[7::stride] = uv[:, 1]

        # Colours (4 floats)
        col = (
            mesh.colors
            if mesh.colors is not None
            else np.ones((n, 4), dtype=np.float32)
        )
        buf[8::stride] = col[:, 0]
        buf[9::stride] = col[:, 1]
        buf[10::stride] = col[:, 2]
        buf[11::stride] = col[:, 3]

        self._vbo = self._ctx.buffer(buf.tobytes())

        # Index buffer
        if mesh.indices is not None:
            self._ibo = self._ctx.buffer(mesh.indices.tobytes())

        # Vertex array object
        vao_content = [
            (self._vbo, "3f 3f 2f 4f", "in_position", "in_normal", "in_uv", "in_color"),
        ]
        if self._ibo:
            self._vao = self._ctx.vertex_array(vao_content, self._ibo)
        else:
            self._vao = self._ctx.vertex_array(vao_content)

        _logger.debug("Uploaded mesh: %d vertices, %d indices", n, self._index_count)

    @property
    def vao(self) -> Any:
        """ModernGL vertex array object."""
        return self._vao

    @property
    def vertex_count(self) -> int:
        return self._vertex_count

    @property
    def index_count(self) -> int:
        return self._index_count

    @property
    def mesh(self) -> Mesh:
        """Original CPU-side mesh data."""
        return self._mesh

    def render(self, mode: int | None = None) -> None:
        """Issue the draw call for this mesh.

        Args:
            mode: ModernGL primitive mode (e.g., ``moderngl.TRIANGLES``).
                  Defaults to ``moderngl.TRIANGLES``.
        """
        if self._vao is None:
            return
        if mode is not None:
            self._vao.render(mode)
        elif self._ibo:
            self._vao.render()
        else:
            self._vao.render(self._vertex_count)

    def release(self) -> None:
        """Release GPU resources."""
        if self._vao:
            self._vao.release()
            self._vao = None
        if self._vbo:
            self._vbo.release()
            self._vbo = None
        if self._ibo:
            self._ibo.release()
            self._ibo = None

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()
