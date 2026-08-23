"""Tests for CppWarpEngine — Python wrapper around the C++ warp engine.

Covers: construction, delegation, fallback, parameter translation.
If the native extension is not compiled, only fallback/construction tests run.
"""

from __future__ import annotations

import numpy as np
import pytest

from projectionai._native import AVAILABLE
from projectionai.domain.projection import BlendConfig, CropRegion
from projectionai.domain.warp_mesh import WarpMesh
from projectionai.services.warp_engine_cpu import CpuWarpEngine


def _identity_mesh() -> WarpMesh:
    """Create an identity warp mesh that maps source directly to output."""
    verts = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        dtype=np.float64,
    )
    # Projector UV: full quad, V-down (image convention)
    projector_uvs = np.array(
        [[0, 0], [1, 0], [0, 1], [1, 1]],
        dtype=np.float64,
    )
    # Content UV: same as projector for identity
    content_uvs = np.array(
        [[0, 0], [1, 0], [0, 1], [1, 1]],
        dtype=np.float64,
    )
    indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    return WarpMesh(
        vertices=verts,
        projector_uvs=projector_uvs,
        content_uvs=content_uvs,
        indices=indices,
    )


class TestCppWarpEngineConstruction:
    """Test CppWarpEngine instantiation."""

    def test_init_with_native(self) -> None:
        """If native is available, CppWarpEngine constructs successfully."""
        if not AVAILABLE:
            pytest.skip("Native extension not compiled")

        from projectionai.services.warp_engine_cpp import CppWarpEngine

        engine = CppWarpEngine()
        assert engine is not None

    def test_init_without_native_raises(self) -> None:
        """If native is NOT available, CppWarpEngine raises RuntimeError."""
        if AVAILABLE:
            pytest.skip("Native extension is compiled — cannot test fallback")

        from projectionai.services.warp_engine_cpp import CppWarpEngine

        with pytest.raises(RuntimeError, match="not compiled"):
            CppWarpEngine()


class TestCppWarpEngineWarp:
    """Test CppWarpEngine.warp() delegation — only if native is available."""

    @pytest.fixture(autouse=True)
    def _require_native(self) -> None:
        if not AVAILABLE:
            pytest.skip("Native extension not compiled")

    def test_identity_warp(self) -> None:
        """Identity warp preserves source content."""
        from projectionai.services.warp_engine_cpp import CppWarpEngine

        engine = CppWarpEngine()
        src = np.full((4, 4, 4), [100, 200, 50, 255], dtype=np.uint8)
        mesh = _identity_mesh()

        out = engine.warp(src, mesh, 4, 4, BlendConfig(), CropRegion())

        assert out.shape == (4, 4, 4)
        assert np.all(np.abs(out[:, :, 0].astype(int) - 100) <= 2)
        assert np.all(np.abs(out[:, :, 1].astype(int) - 200) <= 2)

    def test_matches_cpu_engine(self) -> None:
        """CppWarpEngine produces the same result as CpuWarpEngine."""
        from projectionai.services.warp_engine_cpp import CppWarpEngine

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        rng = np.random.default_rng(42)
        src = rng.integers(0, 255, size=(8, 8, 4), dtype=np.uint8)
        mesh = _identity_mesh()
        blend = BlendConfig(left=0.2, right=0.2)
        crop = CropRegion(x=0.1, y=0.1, width=0.8, height=0.8)

        out_cpp = cpp.warp(src, mesh, 16, 16, blend, crop)
        out_cpu = cpu.warp(src, mesh, 16, 16, blend, crop)

        # atol=1: C++ and Python blend ramps now match (np.linspace semantics).
        # Remaining diff of 1 is from float64→uint8 rounding in both paths.
        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_with_mask(self) -> None:
        """Mask parameter is passed through correctly."""
        from projectionai.services.warp_engine_cpp import CppWarpEngine

        engine = CppWarpEngine()
        src = np.full((4, 4, 4), 200, dtype=np.uint8)
        mesh = _identity_mesh()
        mask = np.ones((4, 4), dtype=np.float64)
        mask[0, 0] = 0.0

        out = engine.warp(src, mesh, 4, 4, BlendConfig(), CropRegion(), mask=mask)
        assert out[0, 0, 0] == 0  # Masked to black

    def test_none_blend_and_crop_defaults(self) -> None:
        """Passing None for blend/crop uses defaults (full output, no blend)."""
        from projectionai.services.warp_engine_cpp import CppWarpEngine

        engine = CppWarpEngine()
        src = np.full((4, 4, 4), 180, dtype=np.uint8)
        mesh = _identity_mesh()

        out = engine.warp(src, mesh, 4, 4, None, None)
        assert out.shape == (4, 4, 4)
        # Should be nearly uniform
        assert np.all(np.abs(out[:, :, 0].astype(int) - 180) <= 2)
