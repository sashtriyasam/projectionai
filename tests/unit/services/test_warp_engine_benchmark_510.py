"""CPU vs C++ Warp Engine Benchmark (Phase 5.10).

Benchmarks both engines at multiple resolutions with deterministic workloads.
Measures median, mean, p95, worst, throughput, and memory behavior.
"""

from __future__ import annotations

import gc
import statistics
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from projectionai.domain.projection import BlendConfig, CropRegion
from projectionai.domain.warp_mesh import WarpMesh, create_identity_warp_mesh
from projectionai.services import EngineMode, WarpEngineFactory
from projectionai.services.warp_engine_cpu import ProjectionWarpEngine


@dataclass
class BenchmarkResult:
    """Statistical results for a benchmark run."""

    name: str
    engine_type: str
    resolution: tuple[int, int]
    grid_size: tuple[int, int]
    iterations: int
    times_ms: list[float]

    @property
    def median_ms(self) -> float:
        return float(np.median(self.times_ms))

    @property
    def mean_ms(self) -> float:
        return float(np.mean(self.times_ms))

    @property
    def p95_ms(self) -> float:
        return float(np.percentile(self.times_ms, 95))

    @property
    def worst_ms(self) -> float:
        return float(np.max(self.times_ms))

    @property
    def throughput_mps(self) -> float:
        """Million pixels per second."""
        if self.median_ms <= 0:
            return 0.0
        pixels = self.resolution[0] * self.resolution[1]
        return (pixels * 1000 / self.median_ms) / 1_000_000


def make_source_texture(width: int, height: int) -> np.ndarray:
    """Create deterministic source texture with known pattern."""
    # Use a gradient pattern that exercises bilinear sampling
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    xx, yy = np.meshgrid(x, y)
    rgba = np.stack(
        [
            xx,  # R = x gradient
            yy,  # G = y gradient
            (xx + yy) // 2,  # B = mixed
            np.full_like(xx, 255),  # A = opaque
        ],
        axis=-1,
    )
    return rgba


def make_blend_config() -> BlendConfig:
    """Create a blend config with non-trivial blend zones."""
    from projectionai.domain.projection import BlendMode

    return BlendConfig(
        left=0.1,
        right=0.1,
        top=0.1,
        bottom=0.1,
        mode=BlendMode.GAMMA_CORRECT,
        gamma=2.2,
    )


def make_crop_config() -> CropRegion:
    """Create a crop config with non-trivial crop."""
    return CropRegion(x=0.1, y=0.1, width=0.8, height=0.8, enabled=True)


def make_mask(output_width: int, output_height: int) -> np.ndarray:
    """Create a feathered circular mask."""
    cy, cx = output_height // 2, output_width // 2
    radius = min(cx, cy) * 0.8
    yy, xx = np.ogrid[:output_height, :output_width]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    feather = radius * 0.1
    mask = np.clip((radius - dist + feather) / feather, 0, 1)
    return mask


def run_benchmark(
    engine: Any,
    source: np.ndarray,
    mesh: WarpMesh,
    output_width: int,
    output_height: int,
    iterations: int,
    blend: BlendConfig | None = None,
    crop: CropRegion | None = None,
    mask: np.ndarray | None = None,
) -> list[float]:
    """Run benchmark iterations and return list of times in ms."""
    times = []

    # Warmup
    for _ in range(3):
        engine.warp(source, mesh, output_width, output_height, blend, crop, mask)

    # Force garbage collection before timing
    gc.collect()

    for _ in range(iterations):
        start = time.perf_counter()
        result = engine.warp(
            source, mesh, output_width, output_height, blend, crop, mask
        )
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

        # Prevent optimization from eliding work
        assert result is not None
        assert result.shape == (output_height, output_width, 4)

    return times


class TestWarpEngineBenchmark:
    """Phase 5.10 CPU vs C++ benchmarks."""

    # Test configurations: (output_width, output_height, grid_rows, grid_cols, iterations)
    CONFIGS = [
        (256, 256, 2, 2, 20),
        (512, 512, 4, 4, 15),
        (1280, 720, 8, 8, 10),
        (1920, 1080, 16, 16, 5),
    ]

    VARIANTS = [
        ("baseline", None, None),
        ("with_blend", make_blend_config(), None),
        ("with_crop", None, make_crop_config()),
        ("with_mask", None, None),  # mask created per-resolution
        (
            "full",
            make_blend_config(),
            make_crop_config(),
        ),  # mask created per-resolution
    ]

    cpu_engine: ProjectionWarpEngine
    cpp_engine: ProjectionWarpEngine | None
    native_available: bool

    @pytest.fixture(autouse=True)
    def setup_engines(self) -> None:
        """Ensure both engines are available."""
        self.cpu_engine = WarpEngineFactory.create(EngineMode.CPU)
        self.native_available = WarpEngineFactory.is_native_available()
        if self.native_available:
            self.cpp_engine = WarpEngineFactory.create(EngineMode.NATIVE)
        else:
            self.cpp_engine = None
            pytest.skip("Native engine not available")

    def test_both_engines_available(self) -> None:
        """Sanity check: both engines should be creatable."""
        assert self.cpu_engine is not None
        assert self.cpp_engine is not None

    @pytest.mark.slow
    @pytest.mark.parametrize("width,height,grid_rows,grid_cols,iters", CONFIGS)
    @pytest.mark.parametrize("variant_name,blend,crop", VARIANTS)
    def test_benchmark_cpu_vs_cpp(
        self,
        width: int,
        height: int,
        grid_rows: int,
        grid_cols: int,
        iters: int,
        variant_name: str,
        blend: BlendConfig | None,
        crop: CropRegion | None,
    ) -> None:
        """Compare CPU vs C++ at each resolution and variant."""
        source = make_source_texture(width, height)
        mesh = create_identity_warp_mesh(
            width=width,
            height=height,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
        )

        # Create mask for this resolution if needed
        mask = (
            make_mask(width, height) if variant_name in ("with_mask", "full") else None
        )

        # Benchmark CPU
        cpu_times = run_benchmark(
            self.cpu_engine, source, mesh, width, height, iters, blend, crop, mask
        )
        cpu_result = BenchmarkResult(
            name=f"CPU-{variant_name}",
            engine_type="CPU",
            resolution=(width, height),
            grid_size=(grid_rows, grid_cols),
            iterations=iters,
            times_ms=cpu_times,
        )

        # Benchmark C++
        cpp_times = run_benchmark(
            self.cpp_engine, source, mesh, width, height, iters, blend, crop, mask
        )
        cpp_result = BenchmarkResult(
            name=f"CPP-{variant_name}",
            engine_type="C++",
            resolution=(width, height),
            grid_size=(grid_rows, grid_cols),
            iterations=iters,
            times_ms=cpp_times,
        )

        # Print comparison
        print(f"\n{'=' * 80}")
        print(
            f"Resolution: {width}x{height}, Grid: {grid_rows}x{grid_cols}, Variant: {variant_name}"
        )
        print(f"{'=' * 80}")
        print(f"{'Metric':<20} {'CPU (ms)':>12} {'C++ (ms)':>12} {'Speedup':>10}")
        print(f"{'-' * 54}")
        print(
            f"{'Median':<20} {cpu_result.median_ms:>12.2f} {cpp_result.median_ms:>12.2f} {cpu_result.median_ms / cpp_result.median_ms:>9.2f}x"
        )
        print(
            f"{'Mean':<20} {cpu_result.mean_ms:>12.2f} {cpp_result.mean_ms:>12.2f} {cpu_result.mean_ms / cpp_result.mean_ms:>9.2f}x"
        )
        print(
            f"{'P95':<20} {cpu_result.p95_ms:>12.2f} {cpp_result.p95_ms:>12.2f} {cpu_result.p95_ms / cpp_result.p95_ms:>9.2f}x"
        )
        print(
            f"{'Worst':<20} {cpu_result.worst_ms:>12.2f} {cpp_result.worst_ms:>12.2f} {cpu_result.worst_ms / cpp_result.worst_ms:>9.2f}x"
        )
        print(
            f"{'Throughput (Mpx/s)':<20} {cpu_result.throughput_mps:>12.2f} {cpp_result.throughput_mps:>12.2f} {cpp_result.throughput_mps / cpu_result.throughput_mps:>9.2f}x"
        )

        # Verify C++ is not significantly slower than CPU (allow 20% overhead for data transfer)
        # Enforce only for the largest configuration; smaller configs report without failing
        is_largest = width == 1920 and height == 1080
        if is_largest:
            assert cpp_result.median_ms <= cpu_result.median_ms * 1.2, (
                f"C++ median ({cpp_result.median_ms:.2f}ms) > 1.2x CPU median ({cpu_result.median_ms:.2f}ms)"
            )

    @pytest.mark.slow
    @pytest.mark.parametrize("width,height,grid_rows,grid_cols,iters", CONFIGS)
    def test_correctness_cpu_vs_cpp(
        self,
        width: int,
        height: int,
        grid_rows: int,
        grid_cols: int,
        iters: int,
    ) -> None:
        """Verify CPU and C++ produce numerically equivalent output."""
        source = make_source_texture(width, height)
        mesh = create_identity_warp_mesh(
            width=width, height=height, grid_rows=grid_rows, grid_cols=grid_cols
        )
        blend = make_blend_config()
        crop = make_crop_config()
        mask = make_mask(width, height)

        cpu_out = self.cpu_engine.warp(source, mesh, width, height, blend, crop, mask)
        cpp_out = self.cpp_engine.warp(source, mesh, width, height, blend, crop, mask)

        # Allow small numerical differences (1 LSB in uint8)
        np.testing.assert_allclose(cpu_out, cpp_out, atol=1, rtol=0)

    @pytest.mark.slow
    def test_memory_allocation_behavior(self) -> None:
        """Verify memory allocation patterns don't cause excessive growth."""
        import tracemalloc

        source = make_source_texture(512, 512)
        mesh = create_identity_warp_mesh(
            width=512, height=512, grid_rows=4, grid_cols=4
        )

        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        try:
            for _ in range(100):
                self.cpu_engine.warp(source, mesh, 512, 512)
                self.cpp_engine.warp(source, mesh, 512, 512)
        finally:
            snapshot_after = tracemalloc.take_snapshot()
            tracemalloc.stop()

        # Compare peak memory growth (top 10 allocations by size)
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        # Allow up to 10 MB of growth for 200 warp calls
        assert total_growth < 10 * 1024 * 1024, (
            f"Excessive memory growth: {total_growth / 1024:.0f} KB over 200 warp calls"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "slow"])
