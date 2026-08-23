"""CppWarpEngine — ProjectionWarpEngine backed by C++ native extension.

Initialization raises RuntimeError if the native extension is unavailable.
Fallback to CpuWarpEngine is handled by WarpEngineFactory.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt

from projectionai._native import AVAILABLE, native_warp
from projectionai.domain.projection import BlendConfig, CropRegion
from projectionai.domain.warp_mesh import WarpMesh
from projectionai.services.warp_engine_cpu import ProjectionWarpEngine

logger = logging.getLogger(__name__)


_BLEND_MODE_MAP: dict[str, int] = {
    "alpha_blend": 0,
    "linear": 1,
    "gamma_correct": 2,
}


def _blend_mode_int(mode: str) -> int:
    if mode not in _BLEND_MODE_MAP:
        raise ValueError(
            f"Unknown blend mode {mode!r}; expected one of {list(_BLEND_MODE_MAP)}"
        )
    return _BLEND_MODE_MAP[mode]


def _blend_params(blend: BlendConfig) -> dict[str, Any]:
    return {
        "blend_left": blend.left,
        "blend_right": blend.right,
        "blend_top": blend.top,
        "blend_bottom": blend.bottom,
        "blend_mode": _blend_mode_int(blend.mode),
        "blend_gamma": blend.gamma,
    }


def _crop_params(crop: CropRegion) -> dict[str, Any]:
    return {
        "crop_x": crop.x,
        "crop_y": crop.y,
        "crop_width": crop.width,
        "crop_height": crop.height,
        "crop_enabled": crop.enabled,
    }


class CppWarpEngine(ProjectionWarpEngine):
    """ProjectionWarpEngine that delegates to the C++ warp engine.

    If the native extension is not compiled, ``warp()`` raises at runtime
    with a clear error message.
    """

    def __init__(self) -> None:
        if not AVAILABLE:
            raise RuntimeError(
                "C++ warp engine extension is not compiled. "
                "Run 'pip install -e .' to build it, or use CpuWarpEngine instead."
            )
        self._native_warp = native_warp

    def warp(
        self,
        source: npt.NDArray[np.uint8],
        warp_mesh: WarpMesh,
        output_width: int,
        output_height: int,
        blend: BlendConfig | None = None,
        crop: CropRegion | None = None,
        mask: npt.NDArray[np.float64] | None = None,
    ) -> npt.NDArray[np.uint8]:
        """Delegate to the C++ warp engine.

        Parameters match the ``ProjectionWarpEngine.warp`` signature exactly.
        """
        # Default to no-op configs when None is passed
        _blend = blend if blend is not None else BlendConfig()
        _crop = crop if crop is not None else CropRegion()

        result: npt.NDArray[np.uint8] = self._native_warp(
            source,
            warp_mesh.projector_uvs,
            warp_mesh.content_uvs,
            warp_mesh.indices,
            output_width,
            output_height,
            **_blend_params(_blend),
            **_crop_params(_crop),
            mask=mask,
        )
        return result
