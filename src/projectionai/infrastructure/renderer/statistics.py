"""Render statistics — frame timing, draw-call tracking, GPU memory estimate."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class FrameMetrics:
    """Snapshot of a single frame's rendering metrics."""

    frame_time_ms: float = 0.0
    gpu_time_ms: float = 0.0
    draw_calls: int = 0
    triangles: int = 0
    vertices: int = 0
    passes_executed: int = 0


class RenderStatistics:
    """Tracks frame-level rendering statistics over a sliding window.

    Thread-safe design: the render thread writes metrics, the UI thread
    reads the latest snapshot via ``collect()``.
    """

    def __init__(self, window_size: int = 120) -> None:
        self._window_size = window_size
        self._current: FrameMetrics = FrameMetrics()
        self._history: list[FrameMetrics] = []
        self._frame_count = 0
        self._tick_start = 0.0
        self._last_fps_update = 0.0
        self._fps_history: list[float] = []
        self._fps = 0.0

    # -- Per-frame callouts ------------------------------------------------

    def begin_frame(self) -> None:
        """Mark the start of a new frame."""
        self._tick_start = time.perf_counter()
        self._current = FrameMetrics()

    def end_frame(self) -> None:
        """Mark the end of the current frame and record metrics."""
        elapsed = (time.perf_counter() - self._tick_start) * 1000.0
        self._current.frame_time_ms = elapsed
        self._history.append(self._current)
        if len(self._history) > self._window_size:
            self._history.pop(0)

        self._frame_count += 1
        now = time.perf_counter()
        self._fps_history.append(elapsed)
        if len(self._fps_history) > 30:
            self._fps_history.pop(0)

        # Update FPS every 500ms
        if now - self._last_fps_update >= 0.5:
            avg_ms = sum(self._fps_history) / len(self._fps_history)
            self._fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
            self._last_fps_update = now

    def count_draw_call(self, vertices: int = 0, triangles: int = 0) -> None:
        """Increment draw-call counter for the current frame."""
        self._current.draw_calls += 1
        self._current.vertices += vertices
        self._current.triangles += triangles

    def count_pass(self) -> None:
        """Increment pass counter for the current frame."""
        self._current.passes_executed += 1

    # -- Accessors ---------------------------------------------------------

    @property
    def fps(self) -> float:
        """Smoothed frames-per-second."""
        return self._fps

    @property
    def frame_time_ms(self) -> float:
        """Most recent frame time in milliseconds."""
        if self._history:
            return self._history[-1].frame_time_ms
        return 0.0

    @property
    def total_frames(self) -> int:
        """Total frames rendered since creation."""
        return self._frame_count

    def collect(self) -> FrameMetrics:
        """Return the latest frame metrics (safe for cross-thread read)."""
        return self._current

    def average_frame_time_ms(self) -> float:
        """Average frame time over the sliding window."""
        if not self._history:
            return 0.0
        return sum(m.frame_time_ms for m in self._history) / len(self._history)

    def peak_frame_time_ms(self) -> float:
        """Peak frame time in the sliding window."""
        if not self._history:
            return 0.0
        return max(m.frame_time_ms for m in self._history)

    # -- GPU memory estimate ------------------------------------------------

    @staticmethod
    def estimate_gpu_memory() -> str:
        """Return a human-readable GPU memory estimate string.

        This is a best-effort estimate. Real GPU memory querying requires
        platform-specific APIs (NVML, Windows GDIDIAG, etc.).
        """
        return "N/A (platform-specific)"
