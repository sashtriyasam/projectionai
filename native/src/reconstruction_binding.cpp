/**
 * @file reconstruction_binding.cpp
 * @brief pybind11 binding for the C++ reconstruction kernels.
 *
 * Exposes projectionai._reconstruction_native with zero-copy NumPy
 * consumption: inputs are required to be C-contiguous float64 (the
 * binding raises instead of silently copying non-contiguous buffers).
 */

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <cstddef>
#include <stdexcept>

#include "projectionai/reconstruction.h"

namespace py = pybind11;

namespace {

py::array_t<double> py_triangulate_plane(
    py::array_t<double, py::array::c_style> normalized,
    py::array_t<double, py::array::c_style> normal,
    double offset)
{
    auto n_buf = normalized.unchecked<2>();
    auto norm_buf = normal.unchecked<1>();
    if (n_buf.shape(1) != 2) {
        throw std::runtime_error("normalized must have shape (N, 2)");
    }
    if (norm_buf.shape(0) != 3) {
        throw std::runtime_error("normal must have shape (3,)");
    }
    const std::size_t n = static_cast<std::size_t>(n_buf.shape(0));

    double* result = nullptr;
    {
        py::gil_scoped_release release;
        result = projectionai::triangulate_plane(
            n_buf.data(0, 0), n, norm_buf.data(0), offset);
    }
    if (result == nullptr) {
        throw std::runtime_error("triangulate_plane failed (null input)");
    }
    py::capsule free_when_done(result, [](void* p) {
        projectionai::reconstruction_free(static_cast<double*>(p));
    });
    py::array::ShapeContainer shape({static_cast<py::ssize_t>(n), 3});
    py::array::StridesContainer strides(
        {3 * static_cast<py::ssize_t>(sizeof(double)),
         static_cast<py::ssize_t>(sizeof(double))});
    return py::array_t<double>(shape, strides, result, free_when_done);
}

py::array_t<double> py_project_points(
    py::array_t<double, py::array::c_style> points,
    py::array_t<double, py::array::c_style> intrinsics,
    py::array_t<double, py::array::c_style> pose)
{
    auto p_buf = points.unchecked<2>();
    auto k_buf = intrinsics.unchecked<2>();
    auto t_buf = pose.unchecked<2>();
    if (p_buf.shape(1) != 3) {
        throw std::runtime_error("points must have shape (N, 3)");
    }
    if (k_buf.shape(0) != 3 || k_buf.shape(1) != 3) {
        throw std::runtime_error("intrinsics must have shape (3, 3)");
    }
    if (t_buf.shape(0) != 4 || t_buf.shape(1) != 4) {
        throw std::runtime_error("pose must have shape (4, 4)");
    }
    const std::size_t n = static_cast<std::size_t>(p_buf.shape(0));

    double* result = nullptr;
    {
        py::gil_scoped_release release;
        result = projectionai::project_points(
            p_buf.data(0, 0), n, k_buf.data(0, 0), t_buf.data(0, 0));
    }
    if (result == nullptr) {
        throw std::runtime_error("project_points failed (singular pose or null input)");
    }
    py::capsule free_when_done(result, [](void* p) {
        projectionai::reconstruction_free(static_cast<double*>(p));
    });
    py::array::ShapeContainer shape({static_cast<py::ssize_t>(n), 2});
    py::array::StridesContainer strides(
        {2 * static_cast<py::ssize_t>(sizeof(double)),
         static_cast<py::ssize_t>(sizeof(double))});
    return py::array_t<double>(shape, strides, result, free_when_done);
}

}  // namespace

PYBIND11_MODULE(_reconstruction_native, m) {
    m.doc() = "C++ reconstruction kernels — ray-plane triangulation and projection";

    m.def("triangulate_plane", &py_triangulate_plane,
          "Intersect normalized camera rays with a plane.",
          py::arg("normalized"), py::arg("normal"), py::arg("offset"));
    m.def("project_points", &py_project_points,
          "Project camera-frame 3D points into projector pixels.",
          py::arg("points"), py::arg("intrinsics"), py::arg("pose"));
}
