/**
 * @file warp_engine.cpp
 * @brief C++ projection warp engine — direct port of Python CpuWarpEngine.
 *
 * Algorithm matches src/projectionai/services/warp_engine_cpu.py exactly:
 *   1. Forward triangle rasterization with barycentric interpolation
 *   2. Bilinear source sampling (UV convention: surface V-up → image V-down)
 *   3. Optional crop / blend / mask post-processing
 */

#include "projectionai/warp_engine.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <new>
#include <vector>

namespace projectionai {

// ---------------------------------------------------------------------------
// Internal: bilinear sampling
// ---------------------------------------------------------------------------

static inline void bilinear_sample(
    const unsigned char* img, int img_h, int img_w,
    double u, double v,
    int& r, int& g, int& b)
{
    // UV convention: (0,0) = top-left, (1,1) = bottom-right
    double x_f = u * (img_w - 1);
    double y_f = v * (img_h - 1);

    int x0 = static_cast<int>(x_f);
    int y0 = static_cast<int>(y_f);

    // Clamp to valid range before deriving neighbours
    x0 = std::max(0, std::min(x0, img_w - 1));
    y0 = std::max(0, std::min(y0, img_h - 1));
    int x1 = std::min(x0 + 1, img_w - 1);
    int y1 = std::min(y0 + 1, img_h - 1);

    double fx = x_f - x0;
    double fy = y_f - y0;

    // Fetch four neighbouring pixels (RGBA)
    const auto* p00 = img + (y0 * img_w + x0) * 4;
    const auto* p10 = img + (y0 * img_w + x1) * 4;
    const auto* p01 = img + (y1 * img_w + x0) * 4;
    const auto* p11 = img + (y1 * img_w + x1) * 4;

    // Bilinear interpolation per channel, round to nearest, clamp [0,255]
    double w00 = (1.0 - fx) * (1.0 - fy);
    double w10 = fx * (1.0 - fy);
    double w01 = (1.0 - fx) * fy;
    double w11 = fx * fy;

    r = static_cast<int>(w00 * p00[0] + w10 * p10[0] + w01 * p01[0] + w11 * p11[0] + 0.5);
    g = static_cast<int>(w00 * p00[1] + w10 * p10[1] + w01 * p01[1] + w11 * p11[1] + 0.5);
    b = static_cast<int>(w00 * p00[2] + w10 * p10[2] + w01 * p01[2] + w11 * p11[2] + 0.5);

    r = std::max(0, std::min(255, r));
    g = std::max(0, std::min(255, g));
    b = std::max(0, std::min(255, b));
}

// ---------------------------------------------------------------------------
// Internal: rasterize mesh
// ---------------------------------------------------------------------------

static void rasterise_mesh(
    unsigned char* out,
    const unsigned char* source, int src_h, int src_w,
    const double* proj_uvs, const double* con_uvs, const int* indices,
    int num_verts, int num_faces,
    int out_w, int out_h)
{
    // Convert projector UVs to pixel coordinates
    std::vector<double> px(num_verts);
    std::vector<double> py(num_verts);

    for (int v = 0; v < num_verts; ++v) {
        px[v] = proj_uvs[v * 2 + 0] * (out_w - 1);
        py[v] = proj_uvs[v * 2 + 1] * (out_h - 1);
    }

    for (int f = 0; f < num_faces; ++f) {
        int i0 = indices[f * 3 + 0];
        int i1 = indices[f * 3 + 1];
        int i2 = indices[f * 3 + 2];

        if (i0 < 0 || i0 >= num_verts || i1 < 0 || i1 >= num_verts || i2 < 0 || i2 >= num_verts)
            continue;

        double x0 = px[i0], y0 = py[i0];
        double x1 = px[i1], y1 = py[i1];
        double x2 = px[i2], y2 = py[i2];

        double cu0 = con_uvs[i0 * 2 + 0], cv0 = con_uvs[i0 * 2 + 1];
        double cu1 = con_uvs[i1 * 2 + 0], cv1 = con_uvs[i1 * 2 + 1];
        double cu2 = con_uvs[i2 * 2 + 0], cv2 = con_uvs[i2 * 2 + 1];

        // Bounding box (clamped to output)
        int min_x = std::max(0, static_cast<int>(std::min({x0, x1, x2})));
        int max_x = std::min(out_w - 1, static_cast<int>(std::max({x0, x1, x2})));
        int min_y = std::max(0, static_cast<int>(std::min({y0, y1, y2})));
        int max_y = std::min(out_h - 1, static_cast<int>(std::max({y0, y1, y2})));

        if (min_x > max_x || min_y > max_y) continue;

        // Edge function denominator (signed area x 2)
        double denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2);
        if (std::abs(denom) < 1e-12) continue;  // Degenerate

        double inv_denom = 1.0 / denom;

        for (int row = min_y; row <= max_y; ++row) {
            for (int col = min_x; col <= max_x; ++col) {
                double xf = static_cast<double>(col);
                double yf = static_cast<double>(row);

                // Barycentric coordinates
                double w0 = ((y1 - y2) * (xf - x2) + (x2 - x1) * (yf - y2)) * inv_denom;
                double w1 = ((y2 - y0) * (xf - x2) + (x0 - x2) * (yf - y2)) * inv_denom;
                double w2 = 1.0 - w0 - w1;

                if (w0 < -1e-6 || w1 < -1e-6 || w2 < -1e-6) continue;

                // Interpolate content UV
                double su = w0 * cu0 + w1 * cu1 + w2 * cu2;
                double sv = w0 * cv0 + w1 * cv1 + w2 * cv2;

                su = std::max(0.0, std::min(1.0, su));
                sv = std::max(0.0, std::min(1.0, sv));

                // Surface UV (V-up) → image convention (V-down)
                int r, g, b;
                bilinear_sample(source, src_h, src_w, su, 1.0 - sv, r, g, b);

                auto* px_out = out + (row * out_w + col) * 4;
                px_out[0] = static_cast<unsigned char>(r);
                px_out[1] = static_cast<unsigned char>(g);
                px_out[2] = static_cast<unsigned char>(b);
                px_out[3] = 255;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Internal: crop
// ---------------------------------------------------------------------------

static void apply_crop(
    unsigned char* out, const CropParams& crop,
    int out_w, int out_h)
{
    if (!crop.enabled) return;

    int cx = static_cast<int>(crop.x * out_w + 0.5);
    int cy = static_cast<int>(crop.y * out_h + 0.5);
    int cw = static_cast<int>(crop.width * out_w + 0.5);
    int ch = static_cast<int>(crop.height * out_h + 0.5);

    int y_end = std::min(cy + ch, out_h);
    int x_end = std::min(cx + cw, out_w);

    for (int row = 0; row < out_h; ++row) {
        for (int col = 0; col < out_w; ++col) {
            if (row < cy || row >= y_end || col < cx || col >= x_end) {
                auto* p = out + (row * out_w + col) * 4;
                p[0] = p[1] = p[2] = p[3] = 0;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Internal: blend
// ---------------------------------------------------------------------------

static void apply_blend(
    unsigned char* out, const BlendParams& blend,
    int out_w, int out_h)
{
    // Compute per-pixel blend factor
    auto* factor = new double[out_w * out_h];

    for (int i = 0; i < out_w * out_h; ++i) factor[i] = 1.0;

    // Left edge
    // Matches Python: np.linspace(0.0, 1.0, ramp_w)
    if (blend.left > 0) {
        int ramp_w = std::max(1, static_cast<int>(blend.left * out_w));
        for (int col = 0; col < ramp_w; ++col) {
            double val = (ramp_w > 1) ? static_cast<double>(col) / (ramp_w - 1) : 0.0;
            for (int row = 0; row < out_h; ++row) {
                double& f = factor[row * out_w + col];
                if (val < f) f = val;
            }
        }
    }

    // Right edge
    // Matches Python: np.linspace(1.0, 0.0, ramp_w)
    if (blend.right > 0) {
        int ramp_w = std::max(1, static_cast<int>(blend.right * out_w));
        for (int col = 0; col < ramp_w; ++col) {
            double val = (ramp_w > 1) ? 1.0 - static_cast<double>(col) / (ramp_w - 1) : 1.0;
            for (int row = 0; row < out_h; ++row) {
                double& f = factor[row * out_w + (out_w - ramp_w + col)];
                if (val < f) f = val;
            }
        }
    }

    // Top edge
    // Matches Python: np.linspace(0.0, 1.0, ramp_h)
    if (blend.top > 0) {
        int ramp_h = std::max(1, static_cast<int>(blend.top * out_h));
        for (int row = 0; row < ramp_h; ++row) {
            double val = (ramp_h > 1) ? static_cast<double>(row) / (ramp_h - 1) : 0.0;
            for (int col = 0; col < out_w; ++col) {
                double& f = factor[row * out_w + col];
                if (val < f) f = val;
            }
        }
    }

    // Bottom edge
    // Matches Python: np.linspace(1.0, 0.0, ramp_h)
    if (blend.bottom > 0) {
        int ramp_h = std::max(1, static_cast<int>(blend.bottom * out_h));
        for (int row = 0; row < ramp_h; ++row) {
            double val = (ramp_h > 1) ? 1.0 - static_cast<double>(row) / (ramp_h - 1) : 1.0;
            for (int col = 0; col < out_w; ++col) {
                double& f = factor[(out_h - ramp_h + row) * out_w + col];
                if (val < f) f = val;
            }
        }
    }

    // Gamma correction
    if (blend.mode == 2 && std::abs(blend.gamma - 1.0f) > 0.01f) {
        double inv_gamma = 1.0 / blend.gamma;
        for (int i = 0; i < out_w * out_h; ++i) {
            factor[i] = std::pow(factor[i], inv_gamma);
        }
    }

    // Apply factor to colour channels (keep alpha)
    for (int i = 0; i < out_w * out_h; ++i) {
        auto* p = out + i * 4;
        double f = factor[i];
        p[0] = static_cast<unsigned char>(std::max(0.0, std::min(255.0, p[0] * f + 0.5)));
        p[1] = static_cast<unsigned char>(std::max(0.0, std::min(255.0, p[1] * f + 0.5)));
        p[2] = static_cast<unsigned char>(std::max(0.0, std::min(255.0, p[2] * f + 0.5)));
    }

    delete[] factor;
}

// ---------------------------------------------------------------------------
// Internal: mask
// ---------------------------------------------------------------------------

static void apply_mask(
    unsigned char* out,
    const double* mask, int mask_h, int mask_w,
    int out_w, int out_h)
{
    if (!mask || mask_h <= 0 || mask_w <= 0) return;

    for (int row = 0; row < out_h; ++row) {
        int m_row = std::min(static_cast<int>(static_cast<double>(row) * mask_h / out_h), mask_h - 1);
        for (int col = 0; col < out_w; ++col) {
            int m_col = std::min(static_cast<int>(static_cast<double>(col) * mask_w / out_w), mask_w - 1);
            double m = mask[m_row * mask_w + m_col];

            auto* p = out + (row * out_w + col) * 4;
            p[0] = static_cast<unsigned char>(std::max(0.0, std::min(255.0, p[0] * m + 0.5)));
            p[1] = static_cast<unsigned char>(std::max(0.0, std::min(255.0, p[1] * m + 0.5)));
            p[2] = static_cast<unsigned char>(std::max(0.0, std::min(255.0, p[2] * m + 0.5)));
            p[3] = (m > 0) ? 255 : 0;
        }
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

unsigned char* warp_engine(
    const unsigned char* source,
    int src_h, int src_w,
    const double* projector_uvs, int num_verts,
    const double* content_uvs,
    const int* indices, int num_faces,
    int out_w, int out_h,
    const BlendParams* blend,
    const CropParams* crop,
    const double* mask, int mask_h, int mask_w)
{
    // Validate
    if (!source || !projector_uvs || !content_uvs || !indices) return nullptr;
    if (src_h <= 0 || src_w <= 0 || out_w <= 0 || out_h <= 0) return nullptr;
    if (num_verts <= 0 || num_faces <= 0) return nullptr;

    // Allocate output
    size_t buf_size = static_cast<size_t>(out_w) * out_h * 4;
    auto* out = new(std::nothrow) unsigned char[buf_size];
    if (!out) return nullptr;

    std::memset(out, 0, buf_size);

    // Rasterise
    rasterise_mesh(out, source, src_h, src_w,
                   projector_uvs, content_uvs, indices,
                   num_verts, num_faces, out_w, out_h);

    // Post-processing
    if (crop && !(crop->enabled && std::abs(crop->x) < 1e-6f && std::abs(crop->y) < 1e-6f
                  && std::abs(crop->width - 1.0f) < 1e-6f
                  && std::abs(crop->height - 1.0f) < 1e-6f)) {
        apply_crop(out, *crop, out_w, out_h);
    }

    if (blend && (blend->left > 0 || blend->right > 0
                  || blend->top > 0 || blend->bottom > 0)) {
        apply_blend(out, *blend, out_w, out_h);
    }

    if (mask && mask_h > 0 && mask_w > 0) {
        apply_mask(out, mask, mask_h, mask_w, out_w, out_h);
    }

    return out;
}

void warp_engine_free(unsigned char* buffer) {
    delete[] buffer;
}

}  // namespace projectionai
