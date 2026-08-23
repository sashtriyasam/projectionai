"""Service abstractions: vision, AI, renderer, calibration, storage interfaces.

The canonical way to obtain a projection warp engine is via
:class:`WarpEngineFactory` — callers never import CpuWarpEngine or
CppWarpEngine directly.
"""

from projectionai.services.warp_engine_factory import EngineMode, WarpEngineFactory

__all__ = ["EngineMode", "WarpEngineFactory"]
