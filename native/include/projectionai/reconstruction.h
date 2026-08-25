#pragma once

/**
 * @file reconstruction.h
 * @brief C++ reconstruction kernels — direct ports of the NumPy reference.
 *
 * Numerical semantics match src/projectionai/infrastructure/projector_calibration/
 * estimators.py exactly (IEEE division producing inf/nan for degenerate inputs,
 * same as the reference's np.errstate(divide='ignore', invalid='ignore')).
 *
 * All buffers are row-major float64, matching contiguous NumPy arrays.
 * No hard-coded SIMD intrinsics: plain loops let the compiler auto-vectorize,
 * keeping the binary portable across x86-64 (SSE2/AVX2) and ARM (NEON).
 */

#include <cstddef>

namespace projectionai {

/**
 * Intersect normalized camera rays with a plane (normal . p + offset = 0).
 *
 * @param normalized  (n, 2) normalized image coordinates (x, y), z implicit 1.
 * @param n           Number of rays.
 * @param normal      (3,) unit plane normal.
 * @param offset      Scalar d of the plane equation.
 * @return Newly allocated (n, 3) float64 buffer; caller frees with
 *         reconstruction_free(). Degenerate rays (normal . r ~ 0) yield
 *         inf/nan entries, matching the reference.
 */
double* triangulate_plane(const double* normalized, std::size_t n,
                          const double* normal, double offset);

/**
 * Forward-project camera-frame 3D points into projector pixels.
 *
 * Applies p = K @ (inv(pose) @ p_cam) with homogeneous division.
 *
 * @param points      (n, 3) camera-frame points.
 * @param n           Number of points.
 * @param intrinsics  (3, 3) row-major projector intrinsic matrix.
 * @param pose        (4, 4) row-major projector-local -> camera transform.
 * @return Newly allocated (n, 2) float64 buffer; caller frees with
 *         reconstruction_free(). Zero-depth points yield inf/nan.
 */
double* project_points(const double* points, std::size_t n,
                       const double* intrinsics, const double* pose);

/** Free a buffer previously returned by triangulate_plane / project_points. */
void reconstruction_free(double* buffer);

}  // namespace projectionai
