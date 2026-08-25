"""CPU reference warp engine for projection mapping.

Pure-Python/NumPy implementation of the projection-mapping warp.
This is the deterministic reference that the future native (C++) engine
will be validated against.

Algorithm
=========
Forward triangle rasterisation with bilinear source sampling:

1. For each triangle in the warp mesh, project the three vertices to
   output pixel coordinates (via ``projector_uvs``).
2. Rasterise the triangle using barycentric interpolation.
3. For each covered output pixel, interpolate the ``content_uvs`` via
   the same barycentric weights.
4. Sample the source texture at the interpolated content UV using
   bilinear interpolation.
5. Write the sampled colour to the output buffer.

Boundary behaviour: pixels outside the crop region or outside any
triangle are black (0, 0, 0, 255).

Blend / Mask / Crop
===================

- **Blend**: per-edge linear falloff applied after rasterisation.
- **Crop**: pixels outside the normalised crop rectangle are zeroed.
- **Mask**: per-pixel alpha mask multiplied onto the output.

All three are optional (disabled = no-op).

Dependencies
============
- ``numpy`` only (no OpenCV, no Qt, no ModernGL).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.projection import BlendConfig, CropRegion
from projectionai.domain.warp_mesh import WarpMesh

_logger = logging.getLogger(__name__)


# =============================================================================
# ProjectionWarpEngine ABC
# =============================================================================


class ProjectionWarpEngine(ABC):
    """Abstract base for projection-mapping warp engines (offline/reference).

    This is the projection-mapping counterpart to the scene-based
    ``WarpEngine`` ABC in ``services/renderer.py``.  It operates on
    warp meshes and source textures rather than 3D scene meshes.

    Used for CPU/native preprocessing and golden-reference validation.
    Realtime GPU projection uses ``ProjectionPass`` (ModernGL), not this.
    """

    @abstractmethod
    def warp(
        self,
        source: NDArray[np.uint8],
        warp_mesh: WarpMesh,
        output_width: int,
        output_height: int,
        blend: BlendConfig | None = None,
        crop: CropRegion | None = None,
        mask: NDArray[np.float64] | None = None,
    ) -> NDArray[np.uint8]:
        """Warp *source* onto the projector output.

        Parameters
        ----------
        source : NDArray[np.uint8]
            ``(H, W, 4)`` RGBA source texture.
        warp_mesh : WarpMesh
            The warp mesh defining per-vertex mappings.
        output_width, output_height : int
            Projector output resolution (pixels).
        blend : BlendConfig or None
            Edge-blend configuration (None = no blending).
        crop : CropRegion or None
            Normalised crop region (None = full output).
        mask : NDArray[np.float64] or None
            ``(H_m, W_m)`` alpha mask in [0,1].  None = no mask.

        Returns
        -------
        NDArray[np.uint8]
            ``(output_height, output_width, 4)`` RGBA output.
        """
        ...


# =============================================================================
# CpuWarpEngine
# =============================================================================


class CpuWarpEngine(ProjectionWarpEngine):
    """Deterministic CPU reference warp engine.

    Uses forward triangle rasterisation with bilinear source sampling.
    """

    def warp(
        self,
        source: NDArray[np.uint8],
        warp_mesh: WarpMesh,
        output_width: int,
        output_height: int,
        blend: BlendConfig | None = None,
        crop: CropRegion | None = None,
        mask: NDArray[np.float64] | None = None,
    ) -> NDArray[np.uint8]:
        """Warp *source* onto the projector output using CPU rasterisation."""
        if not warp_mesh.has_content:
            return np.zeros((output_height, output_width, 4), dtype=np.uint8)

        out = np.zeros((output_height, output_width, 4), dtype=np.uint8)

        # -- Rasterise all triangles -----------------------------------------
        _rasterise_mesh(out, source, warp_mesh, output_width, output_height)

        # -- Apply crop ------------------------------------------------------
        if crop is not None and not crop.is_full:
            _apply_crop(out, crop, output_width, output_height)

        # -- Apply blend edges -----------------------------------------------
        if blend is not None and blend.has_any_blend:
            _apply_blend(out, blend, output_width, output_height)

        # -- Apply mask ------------------------------------------------------
        if mask is not None and mask.size > 0:
            _apply_mask(out, mask, output_width, output_height)

        return out


# =============================================================================
# Internal: triangle rasterisation
# =============================================================================


def _rasterise_mesh(
    out: NDArray[np.uint8],
    source: NDArray[np.uint8],
    mesh: WarpMesh,
    out_w: int,
    out_h: int,
) -> None:
    """Rasterise all triangles in *mesh* into *out*."""
    proj_uvs = mesh.projector_uvs  # (V, 2)
    con_uvs = mesh.content_uvs  # (V, 2)
    indices = mesh.indices  # (F, 3)
    src_h, src_w = source.shape[:2]

    # Convert projector UVs to output pixel coordinates
    px = proj_uvs[:, 0] * (out_w - 1)  # (V,)
    py = proj_uvs[:, 1] * (out_h - 1)  # (V,)

    for tri in indices:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])

        # Triangle vertex pixel positions
        x0, y0 = float(px[i0]), float(py[i0])
        x1, y1 = float(px[i1]), float(py[i1])
        x2, y2 = float(px[i2]), float(py[i2])

        # Content UVs for this triangle
        cu0, cv0 = float(con_uvs[i0, 0]), float(con_uvs[i0, 1])
        cu1, cv1 = float(con_uvs[i1, 0]), float(con_uvs[i1, 1])
        cu2, cv2 = float(con_uvs[i2, 0]), float(con_uvs[i2, 1])

        # Bounding box (clamped to output)
        min_x = max(0, int(min(x0, x1, x2)))
        max_x = min(out_w - 1, int(max(x0, x1, x2)))
        min_y = max(0, int(min(y0, y1, y2)))
        max_y = min(out_h - 1, int(max(y0, y1, y2)))

        if min_x > max_x or min_y > max_y:
            continue

        # Edge function denominators (signed area x 2)
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-12:
            continue  # Degenerate triangle

        inv_denom = 1.0 / denom

        # Build pixel grid for bounding box
        cols = np.arange(min_x, max_x + 1, dtype=np.float64)
        rows = np.arange(min_y, max_y + 1, dtype=np.float64)
        xf, yf = np.meshgrid(cols, rows)  # (H, W) each

        # Barycentric coordinates (vectorized)
        w0 = ((y1 - y2) * (xf - x2) + (x2 - x1) * (yf - y2)) * inv_denom
        w1 = ((y2 - y0) * (xf - x2) + (x0 - x2) * (yf - y2)) * inv_denom
        w2 = 1.0 - w0 - w1

        # Inside-triangle mask
        mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not mask.any():
            continue

        # Interpolate content UVs (vectorized)
        su = w0 * cu0 + w1 * cu1 + w2 * cu2
        sv = w0 * cv0 + w1 * cv1 + w2 * cv2
        su = np.clip(su, 0.0, 1.0)
        sv = np.clip(sv, 0.0, 1.0)

        # Sample source texture (vectorized bilinear gather)
        # content_uvs use surface convention (V-up, origin bottom-left)
        # image convention is V-down, so flip: tex_v = 1.0 - sv
        tex_u = su * (src_w - 1)
        tex_v = (1.0 - sv) * (src_h - 1)
        tx0 = np.clip(np.floor(tex_u).astype(np.int32), 0, src_w - 1)
        ty0 = np.clip(np.floor(tex_v).astype(np.int32), 0, src_h - 1)
        tx1 = np.minimum(tx0 + 1, src_w - 1)
        ty1 = np.minimum(ty0 + 1, src_h - 1)
        fx = (tex_u - tx0).astype(np.float64)
        fy = (tex_v - ty0).astype(np.float64)

        # Gather four neighbours
        c00 = source[ty0, tx0].astype(np.float64)
        c10 = source[ty0, tx1].astype(np.float64)
        c01 = source[ty1, tx0].astype(np.float64)
        c11 = source[ty1, tx1].astype(np.float64)

        fx3 = fx[:, :, np.newaxis]
        fy3 = fy[:, :, np.newaxis]
        top = c00 * (1 - fx3) + c10 * fx3
        bot = c01 * (1 - fx3) + c11 * fx3
        sampled = top * (1 - fy3) + bot * fy3  # (H, W, 4) float64

        # Write masked pixels to output
        r = np.floor(np.clip(sampled[:, :, 0] + 0.5, 0, 255)).astype(np.uint8)
        g = np.floor(np.clip(sampled[:, :, 1] + 0.5, 0, 255)).astype(np.uint8)
        b = np.floor(np.clip(sampled[:, :, 2] + 0.5, 0, 255)).astype(np.uint8)

        yy = np.arange(min_y, max_y + 1)
        xx = np.arange(min_x, max_x + 1)
        yy2, xx2 = np.meshgrid(yy, xx, indexing="ij")

        out[yy2[mask], xx2[mask], 0] = r[mask]
        out[yy2[mask], xx2[mask], 1] = g[mask]
        out[yy2[mask], xx2[mask], 2] = b[mask]
        out[yy2[mask], xx2[mask], 3] = 255


def _bilinear_sample(
    img: NDArray[np.uint8],
    u: float,
    v: float,
    img_w: int,
    img_h: int,
) -> tuple[int, int, int]:
    """Bilinearly sample an RGBA image at normalised UV (u, v).

    UV convention: (0,0) = top-left, (1,1) = bottom-right.
    """
    # Map UV to pixel coordinates (top-left origin)
    x_f = u * (img_w - 1)
    y_f = v * (img_h - 1)

    x0 = int(x_f)
    y0 = int(y_f)
    x1 = min(x0 + 1, img_w - 1)
    y1 = min(y0 + 1, img_h - 1)

    fx = x_f - x0
    fy = y_f - y0

    # Fetch four neighbouring pixels (RGBA)
    p00 = img[y0, x0]
    p10 = img[y0, x1]
    p01 = img[y1, x0]
    p11 = img[y1, x1]

    # Bilinear interpolation (per channel, integer-safe)
    r = int(
        (1 - fx) * (1 - fy) * float(p00[0])
        + fx * (1 - fy) * float(p10[0])
        + (1 - fx) * fy * float(p01[0])
        + fx * fy * float(p11[0])
        + 0.5
    )
    g = int(
        (1 - fx) * (1 - fy) * float(p00[1])
        + fx * (1 - fy) * float(p10[1])
        + (1 - fx) * fy * float(p01[1])
        + fx * fy * float(p11[1])
        + 0.5
    )
    b = int(
        (1 - fx) * (1 - fy) * float(p00[2])
        + fx * (1 - fy) * float(p10[2])
        + (1 - fx) * fy * float(p01[2])
        + fx * fy * float(p11[2])
        + 0.5
    )

    return (min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)))


# =============================================================================
# Internal: blend / mask / crop
# =============================================================================


def _apply_blend(
    out: NDArray[np.uint8],
    blend: BlendConfig,
    out_w: int,
    out_h: int,
) -> None:
    """Apply per-edge linear blend falloff to *out*.

    Blend factors are linear ramps from the edge inward, spanning the
    configured fraction of the output dimension.  The final factor is
    clamped to [0, 1].
    """
    factor = np.ones((out_h, out_w), dtype=np.float64)

    # Left edge
    if blend.left > 0:
        ramp_w = max(1, int(blend.left * out_w))
        ramp = np.linspace(0.0, 1.0, ramp_w, dtype=np.float64)
        factor[:, :ramp_w] = np.minimum(factor[:, :ramp_w], ramp[np.newaxis, :])

    # Right edge
    if blend.right > 0:
        ramp_w = max(1, int(blend.right * out_w))
        ramp = np.linspace(1.0, 0.0, ramp_w, dtype=np.float64)
        factor[:, out_w - ramp_w :] = np.minimum(
            factor[:, out_w - ramp_w :], ramp[np.newaxis, :]
        )

    # Top edge
    if blend.top > 0:
        ramp_h = max(1, int(blend.top * out_h))
        ramp = np.linspace(0.0, 1.0, ramp_h, dtype=np.float64)
        factor[:ramp_h, :] = np.minimum(factor[:ramp_h, :], ramp[:, np.newaxis])

    # Bottom edge
    if blend.bottom > 0:
        ramp_h = max(1, int(blend.bottom * out_h))
        ramp = np.linspace(1.0, 0.0, ramp_h, dtype=np.float64)
        factor[out_h - ramp_h :, :] = np.minimum(
            factor[out_h - ramp_h :, :], ramp[:, np.newaxis]
        )

    # Apply gamma correction if requested
    if blend.mode.value == "gamma_correct" and abs(blend.gamma - 1.0) > 0.01:
        factor = np.power(factor, 1.0 / blend.gamma)

    # Multiply colour channels by factor (keep alpha)
    factor3 = factor[:, :, np.newaxis].astype(np.float64)
    out_f = out.astype(np.float64)
    out_f[:, :, :3] = np.clip(out_f[:, :, :3] * factor3 + 0.5, 0, 255)
    out[:] = out_f.astype(np.uint8)


def _apply_crop(
    out: NDArray[np.uint8],
    crop: CropRegion,
    out_w: int,
    out_h: int,
) -> None:
    """Zero pixels outside the normalised crop region."""
    if crop.is_full:
        return

    px = crop.to_projector_pixels(out_w, out_h)
    cx, cy, cw, ch = px

    # Create mask
    mask = np.zeros((out_h, out_w), dtype=np.bool_)
    y_end = min(cy + ch, out_h)
    x_end = min(cx + cw, out_w)
    mask[cy:y_end, cx:x_end] = True

    # Zero outside
    out[~mask] = 0


def _apply_mask(
    out: NDArray[np.uint8],
    mask: NDArray[np.float64],
    out_w: int,
    out_h: int,
) -> None:
    """Apply per-pixel alpha mask (resize if necessary).

    Mask modulates RGB channels; alpha becomes 255 where mask>0, else 0.
    """
    mask_h, mask_w = mask.shape[:2]

    if mask_w == out_w and mask_h == out_h:
        mask_2d = mask
    else:
        # Nearest-neighbour resize
        row_idx = np.clip(
            (np.arange(out_h) * mask_h / out_h).astype(int), 0, mask_h - 1
        )
        col_idx = np.clip(
            (np.arange(out_w) * mask_w / out_w).astype(int), 0, mask_w - 1
        )
        mask_2d = mask[np.ix_(row_idx, col_idx)]

    # Apply: multiply colour channels by mask
    factor = mask_2d[:, :, np.newaxis].astype(np.float64)
    out_f = out.astype(np.float64)
    out_f[:, :, :3] = np.clip(out_f[:, :, :3] * factor + 0.5, 0, 255)
    # Alpha: 255 where mask > 0, else 0 (matches C++ semantics)
    out_f[:, :, 3] = np.where(mask_2d > 0, 255, 0)
    out[:] = out_f.astype(np.uint8)


# =============================================================================
# Performance measurement
# =============================================================================


def measure_warp_performance(
    engine: CpuWarpEngine,
    source: NDArray[np.uint8],
    warp_mesh: WarpMesh,
    output_width: int,
    output_height: int,
    iterations: int = 3,
) -> dict[str, float]:
    """Measure warp performance over *iterations* runs.

    Returns dict with keys:
    - ``mean_ms``: mean wall-clock time per warp (ms)
    - ``min_ms``: minimum time (ms)
    - ``max_ms``: maximum time (ms)
    - ``source_mp``: source megapixels
    - ``output_mp``: output megapixels
    """
    times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        engine.warp(source, warp_mesh, output_width, output_height)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)

    src_h, src_w = source.shape[:2]
    return {
        "mean_ms": float(np.mean(times)),
        "min_ms": float(np.min(times)),
        "max_ms": float(np.max(times)),
        "source_mp": float(src_w * src_h / 1_000_000),
        "output_mp": float(output_width * output_height / 1_000_000),
    }
