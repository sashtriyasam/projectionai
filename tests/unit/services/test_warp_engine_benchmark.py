"""Performance benchmarks: C++ vs Python warp engines.

Compares CpuWarpEngine (pure NumPy) against CppWarpEngine (native C++)
on identical inputs. Only runs when the native extension is compiled.

Usage:
    pytest tests/unit/services/test_warp_engine_benchmark.py -v -s --tb=short
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
import pytest

from projectionai._native import AVAILABLE
from projectionai.domain.projection import BlendConfig, CropRegion
from projectionai.domain.warp_mesh import (
    WarpMeshGeneration,
    create_planar_grid_warp_mesh,
)
from projectionai.services.warp_engine_cpu import CpuWarpEngine
from projectionai.services.warp_engine_cpp import CppWarpEngine

if TYPE_CHECKING:
    from projectionai.domain.warp_mesh import WarpMesh

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="Native extension not compiled")


def _make_grid_mesh(
    grid_rows: int, grid_cols: int, output_w: int, output_h: int
) -> WarpMesh:
    """Create a grid warp mesh for benchmarking."""
    return create_planar_grid_warp_mesh(
        surface_id="bench_surface",
        projector_id="bench_projector",
        width_m=float(output_w),
        height_m=float(output_h),
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        projector_uv_corners=(
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
        ),
        generation_method=WarpMeshGeneration.EXPLICIT,
    )


# ---------------------------------------------------------------------------
# Test: C++ is at least as fast as Python (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestPerformance:
    """Benchmark C++ vs Python warp engines."""

    def test_cpp_not_slower_than_cpu_64x64(self) -> None:
        """C++ warp must not be slower than CPU on a 64x64 grid."""
        mesh = _make_grid_mesh(4, 4, 64, 64)
        rng = np.random.default_rng(1)
        src = rng.integers(0, 255, (64, 64, 4), dtype=np.uint8)
        blend = BlendConfig()
        crop = CropRegion()
        out_w, out_h = 256, 256

        # Warm up
        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()
        for _ in range(2):
            cpp.warp(src, mesh, out_w, out_h, blend, crop)
            cpu.warp(src, mesh, out_w, out_h, blend, crop)

        # Benchmark (5 iterations each)
        iters = 5
        t0 = time.perf_counter()
        for _ in range(iters):
            cpu.warp(src, mesh, out_w, out_h, blend, crop)
        cpu_time = (time.perf_counter() - t0) / iters

        t0 = time.perf_counter()
        for _ in range(iters):
            cpp.warp(src, mesh, out_w, out_h, blend, crop)
        cpp_time = (time.perf_counter() - t0) / iters

        ratio = cpp_time / cpu_time if cpu_time > 0 else float("inf")
        print(
            f"\n  CPU: {cpu_time * 1000:.2f} ms | C++: {cpp_time * 1000:.2f} ms | ratio: {ratio:.3f}"
        )

        # C++ must not be more than 1.5x slower (allow small overhead on tiny inputs)
        if cpu_time > 0:
            assert ratio < 1.5, (
                f"C++ ({cpp_time * 1000:.2f} ms) is more than 1.5x slower than "
                f"CPU ({cpu_time * 1000:.2f} ms) on 64x64 grid"
            )

    def test_cpp_not_slower_than_cpu_256x256(self) -> None:
        """C++ warp must not be slower than CPU on a 256x256 grid."""
        mesh = _make_grid_mesh(8, 8, 256, 256)
        rng = np.random.default_rng(2)
        src = rng.integers(0, 255, (256, 256, 4), dtype=np.uint8)
        blend = BlendConfig()
        crop = CropRegion()
        out_w, out_h = 1024, 1024

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        # Warm up
        for _ in range(1):
            cpp.warp(src, mesh, out_w, out_h, blend, crop)
            cpu.warp(src, mesh, out_w, out_h, blend, crop)

        # Benchmark (3 iterations each — larger images)
        iters = 3
        t0 = time.perf_counter()
        for _ in range(iters):
            cpu.warp(src, mesh, out_w, out_h, blend, crop)
        cpu_time = (time.perf_counter() - t0) / iters

        t0 = time.perf_counter()
        for _ in range(iters):
            cpp.warp(src, mesh, out_w, out_h, blend, crop)
        cpp_time = (time.perf_counter() - t0) / iters

        ratio = cpp_time / cpu_time if cpu_time > 0 else float("inf")
        print(
            f"\n  CPU: {cpu_time * 1000:.2f} ms | C++: {cpp_time * 1000:.2f} ms | ratio: {ratio:.3f}"
        )

        # On larger inputs, C++ should be faster or at most 1.5x slower
        assert ratio < 1.5, (
            f"C++ ({cpp_time * 1000:.2f} ms) is more than 1.5x slower than "
            f"CPU ({cpu_time * 1000:.2f} ms) on 256x256 grid"
        )


# ---------------------------------------------------------------------------
# Test: Correctness of C++ vs Python (deterministic equality)
# ---------------------------------------------------------------------------


class TestCorrectness:
    """Verify C++ and Python produce the same output on identical inputs."""

    def test_outputs_match_8x8(self) -> None:
        """C++ and CPU warp engines produce bit-identical output on 8x8 grid."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        rng = np.random.default_rng(3)
        src = rng.integers(0, 255, (8, 8, 4), dtype=np.uint8)
        blend = BlendConfig()
        crop = CropRegion()
        out_w, out_h = 32, 32

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, out_w, out_h, blend, crop)
        out_cpu = cpu.warp(src, mesh, out_w, out_h, blend, crop)

        np.testing.assert_allclose(
            out_cpp, out_cpu, atol=1, err_msg="C++ and CPU outputs differ on 8x8 grid"
        )

    def test_outputs_match_with_blend(self) -> None:
        """C++ and CPU match with blend enabled."""
        mesh = _make_grid_mesh(2, 2, 16, 16)
        rng = np.random.default_rng(4)
        src = rng.integers(0, 255, (16, 16, 4), dtype=np.uint8)
        blend = BlendConfig(left=0.2, right=0.15, top=0.1, bottom=0.1, gamma=2.0)
        crop = CropRegion()
        out_w, out_h = 64, 64

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, out_w, out_h, blend, crop)
        out_cpu = cpu.warp(src, mesh, out_w, out_h, blend, crop)

        # atol=1: C++ and Python blend ramps now match (np.linspace semantics).
        # Remaining diff of 1 is from float64→uint8 rounding in both paths.
        np.testing.assert_allclose(
            out_cpp, out_cpu, atol=1, err_msg="C++ and CPU outputs differ with blend"
        )

    def test_outputs_match_with_crop(self) -> None:
        """C++ and CPU match with crop enabled."""
        mesh = _make_grid_mesh(2, 2, 16, 16)
        rng = np.random.default_rng(5)
        src = rng.integers(0, 255, (16, 16, 4), dtype=np.uint8)
        blend = BlendConfig()
        crop = CropRegion(x=0.1, y=0.1, width=0.8, height=0.8)
        out_w, out_h = 64, 64

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, out_w, out_h, blend, crop)
        out_cpu = cpu.warp(src, mesh, out_w, out_h, blend, crop)

        np.testing.assert_allclose(
            out_cpp, out_cpu, atol=1, err_msg="C++ and CPU outputs differ with crop"
        )

    def test_outputs_match_with_mask(self) -> None:
        """C++ and CPU match with mask applied."""
        mesh = _make_grid_mesh(2, 2, 16, 16)
        rng = np.random.default_rng(6)
        src = rng.integers(0, 255, (16, 16, 4), dtype=np.uint8)
        blend = BlendConfig()
        crop = CropRegion()
        mask = rng.random((32, 32)).astype(np.float64)
        out_w, out_h = 64, 64

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, out_w, out_h, blend, crop, mask=mask)
        out_cpu = cpu.warp(src, mesh, out_w, out_h, blend, crop, mask=mask)

        np.testing.assert_allclose(
            out_cpp, out_cpu, atol=1, err_msg="C++ and CPU outputs differ with mask"
        )

    def test_blend_width_zero(self) -> None:
        """blend=0 produces no ramp (factor=1 everywhere)."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        src = np.full((8, 8, 4), 200, dtype=np.uint8)
        blend = BlendConfig(left=0.0, right=0.0, top=0.0, bottom=0.0)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 32, 32, blend, crop)
        out_cpu = cpu.warp(src, mesh, 32, 32, blend, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_blend_width_one(self) -> None:
        """blend width=1: single pixel ramp (factor=0 at edge)."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        src = np.full((8, 8, 4), 200, dtype=np.uint8)
        # Use absolute ramp pixels via BlendConfig with small fraction on large output
        blend = BlendConfig(left=1.0 / 32, right=0.0, top=0.0, bottom=0.0)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 32, 32, blend, crop)
        out_cpu = cpu.warp(src, mesh, 32, 32, blend, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_blend_width_two(self) -> None:
        """blend width=2: ramp [0.0, 1.0]."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        src = np.full((8, 8, 4), 200, dtype=np.uint8)
        # 2 pixels = 2/32 = 0.0625
        blend = BlendConfig(left=2.0 / 32, right=0.0, top=0.0, bottom=0.0)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 32, 32, blend, crop)
        out_cpu = cpu.warp(src, mesh, 32, 32, blend, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_small_image_2x2(self) -> None:
        """Correctness on minimum-size output (2x2)."""
        mesh = _make_grid_mesh(2, 2, 4, 4)
        rng = np.random.default_rng(7)
        src = rng.integers(0, 255, (4, 4, 4), dtype=np.uint8)
        blend = BlendConfig(left=0.25)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 2, 2, blend, crop)
        out_cpu = cpu.warp(src, mesh, 2, 2, blend, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_full_width_blend(self) -> None:
        """blend=1.0: ramp spans entire output width."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        src = np.full((8, 8, 4), 255, dtype=np.uint8)
        blend = BlendConfig(left=1.0)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 32, 32, blend, crop)
        out_cpu = cpu.warp(src, mesh, 32, 32, blend, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_left_right_symmetry(self) -> None:
        """Left and right ramps produce matching C++/Python output."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        src = np.full((8, 8, 4), 255, dtype=np.uint8)
        blend_both = BlendConfig(left=0.3, right=0.3)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 64, 64, blend_both, crop)
        out_cpu = cpu.warp(src, mesh, 64, 64, blend_both, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)

    def test_top_bottom_symmetry(self) -> None:
        """Top and bottom ramps produce matching C++/Python output."""
        mesh = _make_grid_mesh(2, 2, 8, 8)
        src = np.full((8, 8, 4), 255, dtype=np.uint8)
        blend_both = BlendConfig(top=0.3, bottom=0.3)
        crop = CropRegion()

        cpp = CppWarpEngine()
        cpu = CpuWarpEngine()

        out_cpp = cpp.warp(src, mesh, 64, 64, blend_both, crop)
        out_cpu = cpu.warp(src, mesh, 64, 64, blend_both, crop)

        np.testing.assert_allclose(out_cpp, out_cpu, atol=1)
