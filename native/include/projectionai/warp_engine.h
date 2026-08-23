#pragma once

/**
 * @file warp_engine.h
 * @brief C++ projection warp engine — deterministic forward triangle rasterization.
 *
 * This is a direct port of the Python CpuWarpEngine from
 * src/projectionai/services/warp_engine_cpu.py. The algorithm produces
 * identical output for the same inputs.
 *
 * Data layout conventions (row-major, matching NumPy):
 *   - source:     uint8  (H, W, 4)   — RGBA pixels, pixel[row][col] at offset row*W*4 + col*4
 *   - uvs:        double (V, 2)      — [vertex][0]=u, [vertex][1]=v
 *   - indices:    int32  (F, 3)      — [face][0..2] = vertex indices
 *   - output:     uint8  (out_h, out_w, 4) — caller frees with warp_engine_free()
 *   - mask:       double (mask_h, mask_w)  — alpha mask in [0,1]
 */

#include <cstdint>

#ifdef _WIN32
    #define WARP_ENGINE_API __declspec(dllexport)
#else
    #define WARP_ENGINE_API __attribute__((visibility("default")))
#endif

namespace projectionai {

/** Edge-blend parameters. All fractions in [0, 1]. */
struct BlendParams {
    float left   = 0.0f;
    float right  = 0.0f;
    float top    = 0.0f;
    float bottom = 0.0f;
    /** 0 = alpha_blend, 1 = linear, 2 = gamma_correct */
    int   mode   = 0;
    float gamma  = 2.2f;
};

/** Normalised crop region in [0, 1] x [0, 1]. */
struct CropParams {
    float x      = 0.0f;
    float y      = 0.0f;
    float width  = 1.0f;
    float height = 1.0f;
    bool  enabled = true;
};

/**
 * Warp a source RGBA texture onto projector output space.
 *
 * @param source        RGBA source texture, row-major (src_h, src_w, 4).
 * @param src_h         Source height in pixels.
 * @param src_w         Source width in pixels.
 * @param projector_uvs Projector UV coords, row-major (num_verts, 2).
 * @param num_verts     Number of vertices.
 * @param content_uvs   Content UV coords, row-major (num_verts, 2).
 * @param indices       Triangle indices, row-major (num_faces, 3).
 * @param num_faces     Number of faces.
 * @param out_w         Output width in pixels.
 * @param out_h         Output height in pixels.
 * @param blend         Edge-blend params (nullable = no blend).
 * @param crop          Crop params (nullable = no crop).
 * @param mask          Alpha mask, row-major (mask_h, mask_w) (nullable = no mask).
 * @param mask_h        Mask height (0 if mask is null).
 * @param mask_w        Mask width  (0 if mask is null).
 * @return  Newly allocated RGBA buffer (out_h, out_w, 4). Caller frees with warp_engine_free().
 *          Returns nullptr on error (empty mesh, degenerate inputs).
 */
WARP_ENGINE_API unsigned char* warp_engine(
    const unsigned char* source,
    int src_h, int src_w,
    const double* projector_uvs, int num_verts,
    const double* content_uvs,
    const int* indices, int num_faces,
    int out_w, int out_h,
    const BlendParams* blend,
    const CropParams* crop,
    const double* mask, int mask_h, int mask_w
);

/** Free a buffer previously returned by warp_engine(). */
WARP_ENGINE_API void warp_engine_free(unsigned char* buffer);

}  // namespace projectionai
