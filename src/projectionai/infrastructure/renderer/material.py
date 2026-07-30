"""Material — combines shader program with uniform values and texture bindings.

Designed for future PBR extension: add roughness/metalness maps, IBL, etc.
"""

from __future__ import annotations

import contextlib
from typing import Any

import numpy as np

from projectionai.infrastructure.renderer.shader import Shader
from projectionai.infrastructure.renderer.texture import Texture


class Material:
    """Encapsulates a shader, its uniforms, and bound textures.

    Usage::

        mat = Material(shader)
        mat["color"] = (1.0, 0.0, 0.0, 1.0)
        mat.set_texture("u_diffuse", diffuse_tex, unit=0)
        mat.bind()
        mesh_vao.render()
    """

    def __init__(self, shader: Shader) -> None:
        self._shader = shader
        self._uniforms: dict[str, Any] = {}
        self._textures: dict[str, tuple[Texture, int]] = {}  # name -> (texture, unit)
        self._next_unit: int = 0
        self._wireframe: bool = False
        self._blend: bool = False
        self._depth_test: bool = True
        self._cull_face: bool = True

    # -- Uniform access ----------------------------------------------------

    def __setitem__(self, name: str, value: Any) -> None:
        self._uniforms[name] = value

    def __getitem__(self, name: str) -> Any:
        return self._uniforms[name]

    def __contains__(self, name: str) -> bool:
        return name in self._uniforms

    def set_uniform(self, name: str, value: Any) -> None:
        """Queue a uniform value to be applied when bound."""
        self._uniforms[name] = value

    def set_texture(
        self, uniform_name: str, texture: Texture, unit: int | None = None
    ) -> None:
        """Bind a texture to a uniform sampler.

        Args:
            uniform_name: Shader uniform name (e.g., ``"u_diffuse"``).
            texture: The texture to bind.
            unit: Texture unit (auto-assigned if ``None``).
        """
        if unit is None:
            unit = self._next_unit
            self._next_unit += 1
        self._textures[uniform_name] = (texture, unit)

    # -- Render state ------------------------------------------------------

    @property
    def shader(self) -> Shader:
        return self._shader

    @property
    def wireframe(self) -> bool:
        return self._wireframe

    @wireframe.setter
    def wireframe(self, value: bool) -> None:
        self._wireframe = value

    @property
    def blend(self) -> bool:
        return self._blend

    @blend.setter
    def blend(self, value: bool) -> None:
        self._blend = value

    @property
    def depth_test(self) -> bool:
        return self._depth_test

    @depth_test.setter
    def depth_test(self, value: bool) -> None:
        self._depth_test = value

    @property
    def cull_face(self) -> bool:
        return self._cull_face

    @cull_face.setter
    def cull_face(self, value: bool) -> None:
        self._cull_face = value

    # -- Binding -----------------------------------------------------------

    def bind(self) -> None:
        """Bind the shader, upload uniforms, and bind textures."""
        shader = self._shader
        shader.use()

        for name, value in self._uniforms.items():
            self._apply_uniform(shader, name, value)

        for uniform_name, (texture, unit) in self._textures.items():
            texture.bind(unit)
            shader.set_int(uniform_name, unit)

    def unbind(self) -> None:
        """Unbind textures."""
        for _, (texture, _) in self._textures.items():
            texture.unbind()

    def _apply_uniform(self, shader: Shader, name: str, value: Any) -> None:
        """Dispatch a single uniform to the shader."""
        if isinstance(value, (int, float)):
            if isinstance(value, int):
                shader.set_int(name, value)
            else:
                shader.set_float(name, value)
        elif isinstance(value, tuple):
            if len(value) == 3:
                shader.set_vec3(name, value[0], value[1], value[2])
            elif len(value) == 4:
                shader.set_vec4(name, value[0], value[1], value[2], value[3])
            elif len(value) == 2:
                shader.set_float(name, value[0])  # approximate
        elif isinstance(value, np.ndarray) and value.shape == (4, 4):
            shader.set_mat4(name, value)
        elif isinstance(value, bytes):
            shader[name] = value
        else:
            with contextlib.suppress(Exception):
                shader.set_uniform(name, value)

    # -- Lifecycle ---------------------------------------------------------

    def release(self) -> None:
        """Release GPU resources."""
        self._shader.release()
        self._textures.clear()
        self._uniforms.clear()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.release()
