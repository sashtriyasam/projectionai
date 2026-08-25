"""Benchmark reconstruction backends (reference NumPy vs native C++).

Run: uv run python scripts/bench_reconstruction.py
"""

from __future__ import annotations

import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from projectionai.services.reconstruction import (
    NativeReconstructionBackend,
    ReconstructionBackend,
    ReconstructionBackendFactory,
    ReferenceReconstructionBackend,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from unit.calibration.reconstruction_synth import make_synthetic_case  # noqa: E402


def _percentiles(times: list[float]) -> tuple[float, float, float, float]:
    s = sorted(times)
    n = len(s)
    return s[n // 2], s[int(0.95 * (n - 1))], s[int(0.99 * (n - 1))], s[-1]


def bench_single(
    backend: ReconstructionBackend, max_points: int, iters: int = 100, warmup: int = 50
) -> tuple[list[float], float]:
    corr = make_synthetic_case("offset_cam", n_points=20000)["correspondences"]
    cam = make_synthetic_case("offset_cam", n_points=20000)["camera"]
    surf = make_synthetic_case("offset_cam", n_points=20000)["surface"]
    for _ in range(warmup):
        backend.reconstruct(corr, cam, surf, max_points)
    times: list[float] = []
    tracemalloc.start()
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        backend.reconstruct(corr, cam, surf, max_points)
        times.append((time.perf_counter_ns() - t0) / 1e6)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return times, peak / 1e6


def bench_ops(
    backend: ReconstructionBackend, max_points: int, iters: int = 100
) -> dict[str, tuple[float, float, float, float]]:
    c = make_synthetic_case("offset_cam", n_points=max_points)
    corr = c["correspondences"]
    cam = c["camera"]
    surf = c["surface"]
    from projectionai.infrastructure.projector_calibration.estimators import (
        sample_correspondences,
        undistort_points,
    )
    from projectionai.services.projector_calibration import CorrespondenceMap

    cmap = CorrespondenceMap(
        projector_x=corr.projector_x,
        projector_y=corr.projector_y,
        mask=corr.mask,
        image_size=corr.image_size,
    )
    cam_px, proj_px = sample_correspondences(cmap, max_points)
    norm = undistort_points(cam_px, cam)

    def bench(fn):
        for _ in range(30):
            fn()
        times = []
        for _ in range(iters):
            t0 = time.perf_counter_ns()
            fn()
            times.append((time.perf_counter_ns() - t0) / 1e6)
        return _percentiles(times)

    results: dict[str, tuple[float, float, float, float]] = {}
    results["sampling"] = bench(lambda: sample_correspondences(cmap, max_points))
    results["undistort"] = bench(lambda: undistort_points(cam_px, cam))
    results["triangulate"] = bench(lambda: backend.triangulate(norm, surf))
    k = c["projector_intrinsics"]
    pose = c["projector_pose"]
    pts = backend.triangulate(norm, surf)
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    results["project"] = bench(lambda: backend.project(pts, k, pose))
    return results


def main() -> None:
    native = ReconstructionBackendFactory.is_native_available()
    print(f"native available: {native}")
    backends: list[ReconstructionBackend] = [ReferenceReconstructionBackend()]
    if native:
        backends.append(NativeReconstructionBackend())

    print("\n=== FULL reconstruct() ===")
    print(
        f"{'backend':<12}{'N':>6}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'max ms':>10}{'peak MB':>10}"
    )
    for max_points in (4000, 8000, 20000):
        for backend in backends:
            times, peak = bench_single(backend, max_points)
            p50, p95, p99, mx = _percentiles(times)
            print(
                f"{backend.name:<12}{max_points:>6}{p50:>10.3f}{p95:>10.3f}{p99:>10.3f}{mx:>10.3f}{peak:>10.2f}"
            )

    print("\n=== Per-op breakdown (offset_cam case) ===")
    for max_points in (4000, 20000):
        print(f"N={max_points}:")
        for backend in backends:
            r = bench_ops(backend, max_points)
            print(
                f"  {backend.name:<12}"
                f" sampling p50={r['sampling'][0]:.3f}ms"
                f" undistort p50={r['undistort'][0]:.3f}ms"
                f" triangulate p50={r['triangulate'][0]:.3f}ms"
                f" project p50={r['project'][0]:.3f}ms"
            )


if __name__ == "__main__":
    main()
