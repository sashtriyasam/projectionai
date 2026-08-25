/**
 * @file reconstruction.cpp
 * @brief C++ reconstruction kernels — direct ports of the NumPy reference.
 */

#include "projectionai/reconstruction.h"

#include <cstddef>
#include <new>

namespace projectionai {

double* triangulate_plane(const double* normalized, std::size_t n,
                          const double* normal, double offset) {
    if (normalized == nullptr || normal == nullptr || n == 0) {
        return nullptr;
    }
    double* out = new (std::nothrow) double[n * 3];
    if (out == nullptr) {
        return nullptr;
    }
    const double nx = normal[0];
    const double ny = normal[1];
    const double nz = normal[2];
    for (std::size_t i = 0; i < n; ++i) {
        const double x = normalized[i * 2 + 0];
        const double y = normalized[i * 2 + 1];
        const double denom = x * nx + y * ny + nz;
        // IEEE division: degenerate rays produce inf/nan, matching reference.
        const double scale = -offset / denom;
        out[i * 3 + 0] = x * scale;
        out[i * 3 + 1] = y * scale;
        out[i * 3 + 2] = scale;
    }
    return out;
}

namespace {

// General 4x4 row-major inverse via Gauss-Jordan with partial pivoting.
// Numerically equivalent to np.linalg.inv for well-conditioned rigid poses.
bool invert4x4(const double* m, double* inv) {
    double a[4][8];
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            a[r][c] = m[r * 4 + c];
            a[r][c + 4] = (r == c) ? 1.0 : 0.0;
        }
    }
    for (int col = 0; col < 4; ++col) {
        int pivot = col;
        double best = a[col][col] < 0 ? -a[col][col] : a[col][col];
        for (int r = col + 1; r < 4; ++r) {
            double cand = a[r][col] < 0 ? -a[r][col] : a[r][col];
            if (cand > best) {
                best = cand;
                pivot = r;
            }
        }
        if (best < 1e-15) {
            return false;
        }
        if (pivot != col) {
            for (int c = 0; c < 8; ++c) {
                double t = a[col][c];
                a[col][c] = a[pivot][c];
                a[pivot][c] = t;
            }
        }
        const double d = a[col][col];
        for (int c = 0; c < 8; ++c) {
            a[col][c] /= d;
        }
        for (int r = 0; r < 4; ++r) {
            if (r == col) continue;
            const double f = a[r][col];
            for (int c = 0; c < 8; ++c) {
                a[r][c] -= f * a[col][c];
            }
        }
    }
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            inv[r * 4 + c] = a[r][c + 4];
        }
    }
    return true;
}

}  // namespace

double* project_points(const double* points, std::size_t n,
                       const double* intrinsics, const double* pose) {
    if (points == nullptr || intrinsics == nullptr || pose == nullptr || n == 0) {
        return nullptr;
    }
    double pose_inv[16];
    if (!invert4x4(pose, pose_inv)) {
        return nullptr;
    }
    double* out = new (std::nothrow) double[n * 2];
    if (out == nullptr) {
        return nullptr;
    }
    const double* K = intrinsics;
    // K row-major: [fx 0 cx; 0 fy cy; 0 0 1]
    const double fx = K[0], cx = K[2], fy = K[4], cy = K[5];
    const double* T = pose_inv;
    for (std::size_t i = 0; i < n; ++i) {
        const double px = points[i * 3 + 0];
        const double py = points[i * 3 + 1];
        const double pz = points[i * 3 + 2];
        // local = T @ [px, py, pz, 1]
        const double lx = T[0] * px + T[1] * py + T[2] * pz + T[3];
        const double ly = T[4] * px + T[5] * py + T[6] * pz + T[7];
        const double lz = T[8] * px + T[9] * py + T[10] * pz + T[11];
        // projected = K @ [lx, ly, lz]; depth lz == 0 -> inf/nan (IEEE)
        out[i * 2 + 0] = (fx * lx + cx * lz) / lz;
        out[i * 2 + 1] = (fy * ly + cy * lz) / lz;
    }
    return out;
}

void reconstruction_free(double* buffer) {
    delete[] buffer;
}

}  // namespace projectionai
