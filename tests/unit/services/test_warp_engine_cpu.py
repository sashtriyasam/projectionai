"""Tests for CpuWarpEngine — CPU reference warp engine.

Covers Section 3 (CPU reference), Section 4 (planar reference case),
and Section 6 (blend/mask/crop).
"""

from __future__ import annotations

import numpy as np
import pytest

from projectionai.domain.projection import BlendConfig, CropRegion
from projectionai.domain.warp_mesh import (
    WarpMesh,
    WarpMeshGeneration,
    create_identity_warp_mesh,
    create_planar_grid_warp_mesh,
)
from projectionai.services.warp_engine_cpu import (
    CpuWarpEngine,
    ProjectionWarpEngine,
    _apply_blend,
    _apply_crop,
    _apply_mask,
    _bilinear_sample,
    measure_warp_performance,
)


# =============================================================================
# Helper: create a simple RGB test image
# =============================================================================


def _make_test_image(w: int, h: int, pattern: str = "gradient") -> NDArray[np.uint8]:
    """Create a test RGBA image."""
    img = np.zeros((h, w, 4), dtype=np.uint8)
    if pattern == "gradient":
        for y in range(h):
            for x in range(w):
                img[y, x, 0] = int(255 * x / max(1, w - 1))  # R: left→right
                img[y, x, 1] = int(255 * y / max(1, h - 1))  # G: top→bottom
                img[y, x, 2] = 128  # B: constant
                img[y, x, 3] = 255  # A: full
    elif pattern == "solid_red":
        img[:, :, 0] = 255
        img[:, :, 3] = 255
    elif pattern == "solid_green":
        img[:, :, 1] = 255
        img[:, :, 3] = 255
    elif pattern == "checkerboard":
        for y in range(h):
            for x in range(w):
                c = 255 if (x // 8 + y // 8) % 2 == 0 else 0
                img[y, x, :3] = c
                img[y, x, 3] = 255
    return img


from numpy.typing import NDArray


# =============================================================================
# ProjectionWarpEngine ABC
# =============================================================================


class TestProjectionWarpEngineABC:
    def test_abstract_raises(self) -> None:
        with pytest.raises(TypeError):
            ProjectionWarpEngine()


# =============================================================================
# Identity warp (Section 4: planar reference case)
# =============================================================================


class TestIdentityWarp:
    """Section 4: identity warp = source image reproduced exactly."""

    def test_identity_1x1_grid(self) -> None:
        """1×1 grid identity: single triangle covering the output."""
        engine = CpuWarpEngine()
        src = _make_test_image(8, 8, "solid_red")
        mesh = create_identity_warp_mesh(8, 8, grid_rows=1, grid_cols=1)
        out = engine.warp(src, mesh, 8, 8)

        assert out.shape == (8, 8, 4)
        # All pixels should be red (bilinear sampling at identity = exact)
        assert np.all(out[:, :, 0] == 255)  # R
        assert np.all(out[:, :, 1] == 0)  # G
        assert np.all(out[:, :, 2] == 0)  # B
        assert np.all(out[:, :, 3] == 255)  # A

    def test_identity_2x2_grid(self) -> None:
        """2×2 grid identity: subdivided but still identity."""
        engine = CpuWarpEngine()
        src = _make_test_image(8, 8, "solid_green")
        mesh = create_identity_warp_mesh(8, 8, grid_rows=2, grid_cols=2)
        out = engine.warp(src, mesh, 8, 8)

        assert out.shape == (8, 8, 4)
        # All pixels should be green
        assert np.all(out[:, :, 0] == 0)
        assert np.all(out[:, :, 1] == 255)
        assert np.all(out[:, :, 2] == 0)
        assert np.all(out[:, :, 3] == 255)

    def test_identity_preserves_gradient(self) -> None:
        """Identity warp should preserve a gradient pattern exactly."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "gradient")
        mesh = create_identity_warp_mesh(16, 16, grid_rows=2, grid_cols=2)
        out = engine.warp(src, mesh, 16, 16)

        # Check a few known gradient values
        assert out[0, 0, 0] == 0  # Top-left R=0
        assert out[0, 15, 0] == 255  # Top-right R=255
        assert out[15, 0, 1] == 255  # Bottom-left G=255
        assert out[0, 0, 1] == 0  # Top-left G=0


# =============================================================================
# Planar warp (translation)
# =============================================================================


class TestPlanarTranslation:
    """Test a known planar translation (shift right by 50%)."""

    def test_translate_right_half(self) -> None:
        """Shift the source 50% right: content UVs are offset."""
        engine = CpuWarpEngine()
        src = _make_test_image(8, 8, "solid_red")

        # Create warp mesh where projector UVs are shifted right by 50%
        # content UVs stay at surface UV; projector UVs shifted
        mesh = create_planar_grid_warp_mesh(
            surface_id="s1",
            projector_id="p1",
            width_m=8.0,
            height_m=8.0,
            grid_rows=1,
            grid_cols=1,
            projector_uv_corners=(
                (0.5, 1.0),  # BL shifted right 50%
                (1.0, 1.0),  # BR at right edge
                (1.0, 0.0),  # TR at right edge
                (0.5, 0.0),  # TL shifted right 50%
            ),
        )

        out = engine.warp(src, mesh, 8, 8)
        assert out.shape == (8, 8, 4)

        # Left half should be black (no coverage)
        assert np.all(out[:, :4, :3] == 0)

        # Right half should be red (source coverage)
        assert np.all(out[:, 4:, 0] == 255)


# =============================================================================
# Bilinear sampling
# =============================================================================


class TestBilinearSampling:
    def test_exact_center(self) -> None:
        img = _make_test_image(10, 10, "solid_red")
        r, g, b = _bilinear_sample(img, 0.5, 0.5, 10, 10)
        assert r == 255
        assert g == 0
        assert b == 0

    def test_exact_top_left(self) -> None:
        img = _make_test_image(10, 10, "gradient")
        r, g, b = _bilinear_sample(img, 0.0, 0.0, 10, 10)
        assert r == 0  # Top-left R=0
        assert g == 0  # Top-left G=0

    def test_exact_bottom_right(self) -> None:
        img = _make_test_image(10, 10, "gradient")
        r, g, b = _bilinear_sample(img, 1.0, 1.0, 10, 10)
        assert r == 255  # Bottom-right R=255
        assert g == 255  # Bottom-right G=255


# =============================================================================
# Empty / degenerate cases
# =============================================================================


class TestEdgeCases:
    def test_empty_mesh_returns_black(self) -> None:
        engine = CpuWarpEngine()
        src = _make_test_image(10, 10, "solid_red")
        mesh = WarpMesh()
        out = engine.warp(src, mesh, 10, 10)
        assert out.shape == (10, 10, 4)
        assert np.all(out == 0)

    def test_degenerate_triangle(self) -> None:
        """All three vertices at the same position → degenerate, no output."""
        engine = CpuWarpEngine()
        src = _make_test_image(10, 10, "solid_red")

        verts = np.array([[5, 5, 0], [5, 5, 0], [5, 5, 0]], dtype=np.float64)
        puvs = np.array([[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]], dtype=np.float64)
        cuvs = np.array([[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]], dtype=np.float64)
        idx = np.array([[0, 1, 2]], dtype=np.int32)

        mesh = WarpMesh(
            surface_id="s1",
            projector_id="p1",
            vertices=verts,
            projector_uvs=puvs,
            content_uvs=cuvs,
            indices=idx,
        )
        out = engine.warp(src, mesh, 10, 10)
        # Should be all black (degenerate triangle skipped)
        assert np.all(out[:, :, :3] == 0)


# =============================================================================
# Blend (Section 6)
# =============================================================================


class TestBlend:
    """Section 6: edge-blend reference behaviour."""

    def test_no_blend(self) -> None:
        """BlendConfig() has all zeros → no blending applied."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        out = engine.warp(src, mesh, 16, 16, blend=BlendConfig())
        assert np.all(out[:, :, 0] == 255)

    def test_left_blend(self) -> None:
        """Left edge blend: pixels near left edge should be darker."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        blend = BlendConfig(left=0.5)
        out = engine.warp(src, mesh, 16, 16, blend=blend)

        # Far right should be full red
        assert out[8, 15, 0] == 255
        # Leftmost column should be darker
        assert out[8, 0, 0] < 255

    def test_all_edges_blend(self) -> None:
        """All four edges with blend: centre should be full brightness."""
        engine = CpuWarpEngine()
        src = _make_test_image(32, 32, "solid_red")
        mesh = create_identity_warp_mesh(32, 32)
        blend = BlendConfig(left=0.25, right=0.25, top=0.25, bottom=0.25)
        out = engine.warp(src, mesh, 32, 32, blend=blend)

        # Centre pixel should be full red
        assert out[16, 16, 0] == 255
        # Corner should be darker (both left and top blend)
        assert out[0, 0, 0] < 255


# =============================================================================
# Crop (Section 6)
# =============================================================================


class TestCrop:
    """Section 6: crop reference behaviour."""

    def test_no_crop(self) -> None:
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        out = engine.warp(src, mesh, 16, 16, crop=CropRegion())
        assert np.all(out[:, :, 0] == 255)

    def test_crop_zeros_outside(self) -> None:
        """Crop region: pixels outside should be black."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        # Crop to centre 50%
        crop = CropRegion(x=0.25, y=0.25, width=0.5, height=0.5)
        out = engine.warp(src, mesh, 16, 16, crop=crop)

        # Centre should be red
        assert out[8, 8, 0] == 255
        # Top-left corner (outside crop) should be black
        assert out[0, 0, 0] == 0
        assert out[0, 0, 3] == 0  # alpha zero


# =============================================================================
# Mask (Section 6)
# =============================================================================


class TestMask:
    """Section 6: mask reference behaviour."""

    def test_no_mask(self) -> None:
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        out = engine.warp(src, mesh, 16, 16, mask=None)
        assert np.all(out[:, :, 0] == 255)

    def test_mask_zeros_where_zero(self) -> None:
        """Mask=0 should zero the pixel."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        mask = np.zeros((16, 16), dtype=np.float64)
        out = engine.warp(src, mesh, 16, 16, mask=mask)
        assert np.all(out[:, :, :3] == 0)
        assert np.all(out[:, :, 3] == 0)  # alpha zero

    def test_mask_half(self) -> None:
        """Mask=0.5 should halve the colour values."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        mask = np.full((16, 16), 0.5, dtype=np.float64)
        out = engine.warp(src, mesh, 16, 16, mask=mask)
        # 255 * 0.5 ≈ 127 or 128
        assert np.all(np.abs(out[:, :, 0].astype(int) - 127) <= 1)
        assert np.all(out[:, :, 3] == 255)  # alpha still 255

    def test_mask_resized(self) -> None:
        """Mask of different size should be resized to output."""
        engine = CpuWarpEngine()
        src = _make_test_image(16, 16, "solid_red")
        mesh = create_identity_warp_mesh(16, 16)
        # 4x4 mask → nearest-neighbour resize to 16x16
        mask_small = np.ones((4, 4), dtype=np.float64)
        mask_small[0, 0] = 0.0  # top-left corner zero
        out = engine.warp(src, mesh, 16, 16, mask=mask_small)
        # Most pixels should be red
        assert out[8, 8, 0] == 255


# =============================================================================
# Combined blend + crop + mask
# =============================================================================


class TestCombinedEffects:
    def test_blend_crop_mask_combined(self) -> None:
        engine = CpuWarpEngine()
        src = _make_test_image(32, 32, "solid_red")
        mesh = create_identity_warp_mesh(32, 32)
        blend = BlendConfig(left=0.1, right=0.1, top=0.1, bottom=0.1)
        crop = CropRegion(x=0.1, y=0.1, width=0.8, height=0.8)
        mask = np.ones((32, 32), dtype=np.float64)
        out = engine.warp(src, mesh, 32, 32, blend=blend, crop=crop, mask=mask)

        # Centre should be red
        assert out[16, 16, 0] == 255
        # Far corner outside crop should be black
        assert out[0, 0, 0] == 0


# =============================================================================
# Performance measurement
# =============================================================================


class TestPerformance:
    def test_measure_returns_stats(self) -> None:
        engine = CpuWarpEngine()
        src = _make_test_image(8, 8, "solid_red")
        mesh = create_identity_warp_mesh(8, 8)
        stats = measure_warp_performance(engine, src, mesh, 8, 8, iterations=1)
        assert "mean_ms" in stats
        assert "min_ms" in stats
        assert "max_ms" in stats
        assert stats["source_mp"] == pytest.approx(0.000064, rel=1e-3)
        assert stats["output_mp"] == pytest.approx(0.000064, rel=1e-3)
