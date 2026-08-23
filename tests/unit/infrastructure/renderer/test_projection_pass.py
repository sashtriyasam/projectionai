"""Tests for ProjectionPass (state only, no GL).

Follows the repository convention for render-pass tests
(see test_pattern_pass.py): GPU resources are replaced by
small fakes so behaviour is verified without a GL context.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from projectionai.domain.warp_mesh import WarpMesh
from projectionai.infrastructure.renderer.passes.projection import ProjectionPass


class FakeShader:
    """Stand-in for Shader recording uniform/release calls."""

    def __init__(self) -> None:
        self.program = object()
        self.ints: dict[str, int] = {}
        self.floats: dict[str, float] = {}
        self.vec2s: dict[str, tuple[float, float]] = {}
        self.vec4s: dict[str, tuple[float, float, float, float]] = {}
        self.released = False

    def set_int(self, name: str, value: int) -> None:
        self.ints[name] = value

    def set_float(self, name: str, value: float) -> None:
        self.floats[name] = value

    def set_vec2(self, name: str, x: float, y: float) -> None:
        self.vec2s[name] = (x, y)

    def set_vec4(self, name: str, x: float, y: float, z: float, w: float) -> None:
        self.vec4s[name] = (x, y, z, w)

    def release(self) -> None:
        self.released = True


class FakeVao:
    """Stand-in for a ModernGL VAO recording render/release calls."""

    def __init__(self) -> None:
        self.rendered = 0
        self.released = False

    def render(self, mode: Any = None) -> None:
        self.rendered += 1

    def release(self) -> None:
        self.released = True


class FakeVbo:
    """Stand-in for a ModernGL buffer recording write/release calls."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.released = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def release(self) -> None:
        self.released = True


class FakeTexture:
    """Stand-in for Texture recording bind/unbind calls."""

    def __init__(self, name: str = "tex") -> None:
        self.name = name
        self.bound_units: list[int] = []
        self.unbound = 0

    def bind(self, unit: int = 0) -> None:
        self.bound_units.append(unit)

    def unbind(self) -> None:
        self.unbound += 1


class FakeTarget:
    """Stand-in for a RenderTarget recording bind/clear calls."""

    def __init__(self) -> None:
        self.width = 1920
        self.height = 1080
        self.binds = 0
        self.clears: list[tuple[float, float, float, float]] = []

    def bind(self) -> None:
        self.binds += 1

    def unbind(self) -> None:
        pass

    def clear(
        self,
        r: float = 0.0,
        g: float = 0.0,
        b: float = 0.0,
        a: float = 1.0,
        depth: float = 1.0,
    ) -> None:
        self.clears.append((r, g, b, a))


def _make_quad_mesh() -> WarpMesh:
    """Create a minimal 2-triangle (4-vertex) identity warp mesh."""
    return WarpMesh(
        surface_id="test",
        projector_id="proj",
        vertices=np.array(
            [[-1.0, -1.0, 0.0], [1.0, -1.0, 0.0], [1.0, 1.0, 0.0], [-1.0, 1.0, 0.0]],
            dtype=np.float64,
        ),
        projector_uvs=np.array(
            [[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]],
            dtype=np.float64,
        ),
        content_uvs=np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            dtype=np.float64,
        ),
        indices=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
        grid_rows=1,
        grid_cols=1,
    )


def _seeded_pass(
    *,
    shader: bool = True,
    vao: bool = True,
    vbo: bool = True,
    target: bool = True,
    ctx: bool = True,
) -> tuple[ProjectionPass, FakeShader, FakeVao, FakeVbo, FakeTarget]:
    """Create a ProjectionPass with fake GPU resources injected."""
    pp = ProjectionPass()
    fake_shader = FakeShader()
    fake_vao = FakeVao()
    fake_vbo = FakeVbo()
    fake_target = FakeTarget()
    if shader:
        pp._shader = fake_shader
    if vao:
        pp._vao = fake_vao
    if vbo:
        pp._vbo = fake_vbo
    if target:
        pp._target = fake_target
    if ctx:
        pp._ctx = _FakeCtx()
    return pp, fake_shader, fake_vao, fake_vbo, fake_target


# ---------------------------------------------------------------------------
# A. Initialization / setup
# ---------------------------------------------------------------------------


def test_initial_state() -> None:
    pp = ProjectionPass()
    assert pp.name == "projection"
    assert pp._shader is None
    assert pp._ctx is None
    assert pp._vao is None
    assert pp._vbo is None
    assert pp._ibo is None
    assert pp._source_texture is None
    assert pp._warp_mesh is None
    assert pp._mesh_id == -1
    assert pp._index_count == 0
    assert pp._blend == 1.0
    assert pp._crop == (0.0, 0.0, 1.0, 1.0)
    assert pp._mask_enabled is False
    assert pp._mask_center == (0.5, 0.5)
    assert pp._mask_radius == 0.5
    assert pp.target is None
    assert pp.enabled
    assert pp.visible


# ---------------------------------------------------------------------------
# B. Shader creation (setup)
# ---------------------------------------------------------------------------


class _FakeCtx:
    """Minimal stand-in for a ModernGL context."""

    def __init__(self) -> None:
        self.buffers: list[FakeVbo] = []
        self.vaos: list[tuple[Any, ...]] = []
        self.enabled: set[int] = set()
        self.blend_func: tuple[int, int] = (0, 0)

    def buffer(self, data_or_reserve: Any = None, *, reserve: int = 0) -> FakeVbo:
        vbo = FakeVbo()
        if data_or_reserve is not None and not isinstance(data_or_reserve, int):
            vbo.write(data_or_reserve if isinstance(data_or_reserve, bytes) else b"")
        self.buffers.append(vbo)
        return vbo

    def vertex_array(self, *args: Any) -> FakeVao:
        vao = FakeVao()
        self.vaos.append(args)
        return vao

    def enable(self, cap: int) -> None:
        self.enabled.add(cap)

    def disable(self, cap: int) -> None:
        self.enabled.discard(cap)


class _FakeShaderForSetup:
    def __init__(self) -> None:
        self.program = object()


def test_setup_creates_shader_stores_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """setup() compiles the projection shader and stores the context."""
    fake_shader = _FakeShaderForSetup()

    def _fake_shader_factory(_ctx: Any, _name: str) -> _FakeShaderForSetup:
        return fake_shader

    monkeypatch.setattr(
        "projectionai.infrastructure.renderer.shader.Shader",
        _fake_shader_factory,
    )
    ctx = _FakeCtx()
    pp = ProjectionPass()
    pp.setup(ctx, 1920, 1080)

    assert pp._shader is fake_shader
    assert pp._ctx is ctx
    # VBO/IBO/VAO are not created until first mesh upload
    assert pp._vbo is None
    assert pp._vao is None
    assert pp._ibo is None


# ---------------------------------------------------------------------------
# C. WarpMesh upload
# ---------------------------------------------------------------------------


def test_ensure_mesh_upload_interleaves_vertices() -> None:
    """_ensure_mesh_uploaded interleaves projector_uvs and content_uvs into VBO."""
    pp, _, _, _, _ = _seeded_pass()
    mesh = _make_quad_mesh()

    pp.set_warp_mesh(mesh)
    pp._ensure_mesh_uploaded()

    # VBO was created via _ctx.buffer(data) — check the first buffer (VBO comes before IBO)
    ctx = pp._ctx
    assert len(ctx.buffers) >= 2  # VBO + IBO
    vbo = ctx.buffers[0]
    assert len(vbo.written) == 1
    data = vbo.written[0]
    # 4 vertices * 4 floats (x, y, u, v) * 4 bytes = 64 bytes
    assert len(data) == 4 * 4 * 4

    # Verify interleaving: first vertex should be (-1, -1, 0, 0)
    arr = np.frombuffer(data, dtype=np.float32).reshape(4, 4)
    np.testing.assert_array_almost_equal(arr[0], [-1.0, -1.0, 0.0, 0.0])
    # Second vertex: (1, -1, 1, 0)
    np.testing.assert_array_almost_equal(arr[1], [1.0, -1.0, 1.0, 0.0])
    # Third: (1, 1, 1, 1)
    np.testing.assert_array_almost_equal(arr[2], [1.0, 1.0, 1.0, 1.0])
    # Fourth: (-1, 1, 0, 1)
    np.testing.assert_array_almost_equal(arr[3], [-1.0, 1.0, 0.0, 1.0])

    # IBO was also created and VAO was rebuilt with it
    assert pp._ibo is not None
    assert pp._vao is not None
    assert pp._index_count == 6  # 2 triangles * 3 indices


# ---------------------------------------------------------------------------
# D. Mesh replacement / change detection
# ---------------------------------------------------------------------------


def test_mesh_change_detection_skips_reupload() -> None:
    """Same mesh object identity → no re-upload."""
    pp, _, _, _, _ = _seeded_pass()
    mesh = _make_quad_mesh()

    pp.set_warp_mesh(mesh)
    pp._ensure_mesh_uploaded()
    first_buffer_count = len(pp._ctx.buffers)

    # Same object → mesh_id matches → skip
    pp._ensure_mesh_uploaded()
    assert len(pp._ctx.buffers) == first_buffer_count


def test_mesh_replacement_triggers_reupload() -> None:
    """Different mesh object → re-upload."""
    pp, _, _, _, _ = _seeded_pass()
    mesh1 = _make_quad_mesh()
    mesh2 = _make_quad_mesh()  # same data, different identity

    pp.set_warp_mesh(mesh1)
    pp._ensure_mesh_uploaded()
    assert len(pp._ctx.buffers) >= 1

    pp.set_warp_mesh(mesh2)
    pp._ensure_mesh_uploaded()
    # New buffers created: VBO + IBO + VAO for second mesh
    assert len(pp._ctx.buffers) >= 2


def test_set_warp_mesh_none_resets_mesh_id() -> None:
    pp, _, _, _, _ = _seeded_pass()
    # _mesh_id is only updated by _ensure_mesh_uploaded, not set_warp_mesh.
    # After uploading a mesh, _mesh_id should be non-negative.
    pp.set_warp_mesh(_make_quad_mesh())
    pp._ensure_mesh_uploaded()
    assert pp._mesh_id != -1
    pp.set_warp_mesh(None)
    assert pp._mesh_id == -1


def test_ensure_mesh_upload_noop_without_mesh() -> None:
    """No mesh → _ensure_mesh_uploaded is a no-op."""
    pp, _, _, _, _ = _seeded_pass()
    buffer_count = len(pp._ctx.buffers)
    pp._ensure_mesh_uploaded()
    assert len(pp._ctx.buffers) == buffer_count


def test_ensure_mesh_upload_noop_without_ctx() -> None:
    """No _ctx → _ensure_mesh_uploaded is a no-op (no crash)."""
    pp = ProjectionPass()
    pp.set_warp_mesh(_make_quad_mesh())
    pp._ensure_mesh_uploaded()  # must not raise


# ---------------------------------------------------------------------------
# E. Source texture binding
# ---------------------------------------------------------------------------


def test_set_source_texture_stores_and_clears() -> None:
    pp = ProjectionPass()
    tex = FakeTexture()
    pp.set_source_texture(tex)
    assert pp._source_texture is tex
    pp.set_source_texture(None)
    assert pp._source_texture is None


# ---------------------------------------------------------------------------
# F. Blend / crop / mask setters
# ---------------------------------------------------------------------------


def test_set_blend_stores_value() -> None:
    pp = ProjectionPass()
    pp.set_blend(0.75)
    assert pp._blend == 0.75


def test_set_crop_stores_tuple() -> None:
    pp = ProjectionPass()
    pp.set_crop(0.1, 0.2, 0.3, 0.4)
    assert pp._crop == (0.1, 0.2, 0.3, 0.4)


def test_set_mask_stores_parameters() -> None:
    pp = ProjectionPass()
    pp.set_mask(True, (0.3, 0.4), 0.6)
    assert pp._mask_enabled is True
    assert pp._mask_center == (0.3, 0.4)
    assert pp._mask_radius == 0.6


# ---------------------------------------------------------------------------
# G. Render — without resources (noop)
# ---------------------------------------------------------------------------


def test_render_without_resources_is_noop() -> None:
    ProjectionPass().render(None, None, None)  # must not raise


def test_render_without_target_is_noop() -> None:
    pp, _shader, _vao, _vbo, _ = _seeded_pass(target=False)
    pp.render(None, None, None)
    assert _shader.floats == {}
    assert _vao.rendered == 0


# ---------------------------------------------------------------------------
# H. Render — with texture + mesh (full path)
# ---------------------------------------------------------------------------


def test_render_with_texture_and_mesh_binds_and_draws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full render: bind texture, set uniforms, draw VAO, unbind texture."""
    _mock_moderngl(monkeypatch)

    pp, fake_shader, fake_vao, _, fake_target = _seeded_pass()
    mesh = _make_quad_mesh()
    tex = FakeTexture("content")

    pp.set_warp_mesh(mesh)
    pp.set_source_texture(tex)
    pp.set_blend(0.8)
    pp.set_crop(0.1, 0.2, 0.3, 0.4)
    pp.set_mask(True, (0.5, 0.5), 0.7)

    # Trigger upload first so _vao is set, then pre-set _mesh_id to skip re-upload
    pp._ensure_mesh_uploaded()
    # Replace with our trackable fake_vao
    pp._vao = fake_vao

    pp.render(None, None, None)

    assert fake_target.binds == 1
    assert fake_target.clears == [(0.0, 0.0, 0.0, 1.0)]
    # Texture bound at unit 0
    assert tex.bound_units == [0]
    assert tex.unbound == 1
    # Uniforms set
    assert fake_shader.ints["u_texture"] == 0
    assert fake_shader.ints["u_mask_enabled"] == 1
    assert fake_shader.floats["u_blend"] == pytest.approx(0.8)
    assert fake_shader.floats["u_mask_radius"] == pytest.approx(0.7)
    assert fake_shader.vec2s["u_mask_center"] == (0.5, 0.5)
    assert fake_shader.vec4s["u_crop"] == (0.1, 0.2, 0.3, 0.4)
    # VAO drawn
    assert fake_vao.rendered == 1


def _mock_moderngl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake moderngl module with required constants."""
    import sys
    import types

    fake_moderngl = types.ModuleType("moderngl")
    fake_moderngl.TRIANGLES = 0x0004
    fake_moderngl.BLEND = 0x0BE2
    fake_moderngl.SRC_ALPHA = 0x0302
    fake_moderngl.ONE_MINUS_SRC_ALPHA = 0x0303
    monkeypatch.setitem(sys.modules, "moderngl", fake_moderngl)


def test_render_mask_disabled_sends_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_moderngl(monkeypatch)
    pp, fake_shader, fake_vao, _, _ = _seeded_pass()
    pp.set_warp_mesh(_make_quad_mesh())
    pp.set_source_texture(FakeTexture())
    pp.set_mask(False, (0.5, 0.5), 0.5)

    pp._ensure_mesh_uploaded()
    pp._vao = fake_vao

    pp.render(None, None, None)

    assert fake_shader.ints["u_mask_enabled"] == 0


def test_render_without_texture_skips_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No source texture → target cleared but nothing drawn."""
    _mock_moderngl(monkeypatch)
    pp, fake_shader, fake_vao, _, fake_target = _seeded_pass()
    pp.set_warp_mesh(_make_quad_mesh())

    pp._ensure_mesh_uploaded()
    pp._vao = fake_vao

    pp.render(None, None, None)

    assert fake_target.binds == 1
    assert fake_target.clears == [(0.0, 0.0, 0.0, 1.0)]
    assert fake_vao.rendered == 0
    # Shader uniforms not set
    assert fake_shader.ints == {}
    assert fake_shader.floats == {}


def test_render_without_mesh_skips_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No warp mesh → target cleared but nothing drawn."""
    _mock_moderngl(monkeypatch)
    pp, _shader, _vao, _, fake_target = _seeded_pass()
    pp.set_source_texture(FakeTexture())

    pp.render(None, None, None)

    assert fake_target.binds == 1
    assert fake_target.clears == [(0.0, 0.0, 0.0, 1.0)]
    assert _vao.rendered == 0


# ---------------------------------------------------------------------------
# I. Release / cleanup
# ---------------------------------------------------------------------------


def test_release_releases_all_gpu_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_moderngl(monkeypatch)
    pp, fake_shader, fake_vao, fake_vbo, _ = _seeded_pass()
    pp.set_source_texture(FakeTexture())
    pp.set_warp_mesh(_make_quad_mesh())

    # Upload creates resources via _ctx, then we also seed old-style for release
    pp._ensure_mesh_uploaded()
    pp._vao = fake_vao
    pp._vbo = fake_vbo

    pp.release()

    assert fake_shader.released
    assert fake_vao.released
    assert fake_vbo.released
    assert pp._shader is None
    assert pp._vao is None
    assert pp._vbo is None
    assert pp._ibo is None
    assert pp._index_count == 0
    assert pp._source_texture is None
    assert pp._warp_mesh is None


def test_release_is_idempotent() -> None:
    pp, fake_shader, fake_vao, fake_vbo, _ = _seeded_pass()
    fake_ibo = FakeVbo()
    pp._ibo = fake_ibo
    pp.release()
    pp.release()
    assert fake_shader.released
    assert fake_vao.released
    assert fake_vbo.released
    assert fake_ibo.released


def test_release_without_resources_is_noop() -> None:
    pp = ProjectionPass()
    pp.release()  # must not raise


# ---------------------------------------------------------------------------
# J. Empty / invalid mesh handling
# ---------------------------------------------------------------------------


def test_render_with_empty_mesh_vertices_skips_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WarpMesh with 0 vertices → cleared but no draw."""
    _mock_moderngl(monkeypatch)
    pp, _, fake_vao, _, fake_target = _seeded_pass()
    empty_mesh = WarpMesh(
        surface_id="empty",
        projector_id="proj",
        vertices=np.zeros((0, 3), dtype=np.float64),
        projector_uvs=np.zeros((0, 2), dtype=np.float64),
        content_uvs=np.zeros((0, 2), dtype=np.float64),
        indices=np.zeros((0, 3), dtype=np.int32),
    )
    pp.set_warp_mesh(empty_mesh)
    pp.set_source_texture(FakeTexture())
    pp._ensure_mesh_uploaded()
    pp._vao = fake_vao

    pp.render(None, None, None)

    # Empty mesh → _index_count is 0 → draw skipped
    assert fake_target.clears == [(0.0, 0.0, 0.0, 1.0)]


# ---------------------------------------------------------------------------
# K. Render target binding (FBO integration)
# ---------------------------------------------------------------------------


def test_render_binds_current_target_not_fbo0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ProjectionPass renders into whatever target is assigned (the widget FBO)."""
    _mock_moderngl(monkeypatch)
    pp, _, fake_vao, _, fake_target = _seeded_pass()
    pp.set_warp_mesh(_make_quad_mesh())
    pp.set_source_texture(FakeTexture())
    pp._ensure_mesh_uploaded()
    pp._vao = fake_vao

    pp.render(None, None, None)

    # The fake_target represents the ScreenTarget wrapping the widget FBO
    assert fake_target.binds == 1
    # ProjectionPass never touches FBO 0 directly — ScreenTarget handles that


# ---------------------------------------------------------------------------
# L. Memory / resource lifecycle validation
# ---------------------------------------------------------------------------


def test_full_lifecycle_render_release_rerender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full cycle: configure → render → release → re-seed → render again.

    Verifies no leaked state prevents a fresh pass from working after
    the previous one was released.
    """
    _mock_moderngl(monkeypatch)

    # First cycle
    pp1, _, fake_vao1, _, _ = _seeded_pass()
    pp1.set_warp_mesh(_make_quad_mesh())
    pp1.set_source_texture(FakeTexture())
    t1 = FakeTarget()
    pp1._target = t1
    pp1._ensure_mesh_uploaded()
    pp1._vao = fake_vao1
    pp1.render(None, None, None)
    assert t1.clears == [(0.0, 0.0, 0.0, 1.0)]

    pp1.release()
    assert pp1._shader is None
    assert pp1._vbo is None
    assert pp1._vao is None

    # Second cycle — fresh pass, no shared state
    pp2, _, fake_vao2, _, _ = _seeded_pass()
    pp2.set_warp_mesh(_make_quad_mesh())
    pp2.set_source_texture(FakeTexture())
    t2 = FakeTarget()
    pp2._target = t2
    pp2._ensure_mesh_uploaded()
    pp2._vao = fake_vao2
    pp2.render(None, None, None)
    assert t2.clears == [(0.0, 0.0, 0.0, 1.0)]
    pp2.release()


def test_multiple_render_cycles_without_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple renders in succession don't leak or accumulate VBO uploads."""
    _mock_moderngl(monkeypatch)
    pp, _, fake_vao, _, _ = _seeded_pass()
    mesh = _make_quad_mesh()
    pp.set_warp_mesh(mesh)
    pp._ensure_mesh_uploaded()
    pp._vao = fake_vao

    for _ in range(5):
        t = FakeTarget()
        pp._target = t
        pp.set_source_texture(FakeTexture())
        pp.render(None, None, None)
        assert t.clears == [(0.0, 0.0, 0.0, 1.0)]

    pp.release()


def test_mesh_id_resets_on_release() -> None:
    """_mesh_id resets to -1 after release, allowing fresh mesh upload."""
    pp, _, _, _, _ = _seeded_pass()
    pp.set_warp_mesh(_make_quad_mesh())
    pp._ensure_mesh_uploaded()
    assert pp._mesh_id != -1

    pp.release()
    assert pp._mesh_id == -1

    # After seeding fresh resources, _mesh_id stays -1 until upload fires
    fake_shader2 = FakeShader()
    fake_vao2 = FakeVao()
    fake_vbo2 = FakeVbo()
    pp._shader = fake_shader2
    pp._vao = fake_vao2
    pp._vbo = fake_vbo2
    pp._ctx = _FakeCtx()
    assert pp._mesh_id == -1
    pp.set_warp_mesh(_make_quad_mesh())
    assert pp._mesh_id == -1  # not yet uploaded
    pp._ensure_mesh_uploaded()
    assert pp._mesh_id != -1
    pp.release()


def test_set_warp_mesh_after_release_does_not_leak() -> None:
    """Setting a new mesh after release doesn't create GPU resources."""
    pp, _, _, _, _ = _seeded_pass()
    pp.release()
    pp.set_warp_mesh(_make_quad_mesh())
    # No shader, VBO, or VAO should have been created
    assert pp._shader is None
    assert pp._vbo is None
    assert pp._vao is None


def test_release_nulls_source_texture_and_mesh() -> None:
    """Release clears _source_texture and _warp_mesh references."""
    pp, _, _, _, _ = _seeded_pass()
    pp.set_warp_mesh(_make_quad_mesh())
    pp.set_source_texture(FakeTexture())
    assert pp._source_texture is not None
    assert pp._warp_mesh is not None

    pp.release()
    assert pp._source_texture is None
    assert pp._warp_mesh is None
