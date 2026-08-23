/**
 * @file binding.cpp
 * @brief pybind11 binding for the C++ warp engine.
 *
 * Exposes projectionai._warp_engine_native.warp() to Python.
 */

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <cstring>
#include <stdexcept>

#include "projectionai/warp_engine.h"

namespace py = pybind11;

static py::array_t<uint8_t> py_warp(
    py::array_t<uint8_t, py::array::c_style | py::array::forcecast> source,
    py::array_t<double, py::array::c_style | py::array::forcecast> projector_uvs,
    py::array_t<double, py::array::c_style | py::array::forcecast> content_uvs,
    py::array_t<int32_t, py::array::c_style | py::array::forcecast> indices,
    int out_w,
    int out_h,
    float blend_left,
    float blend_right,
    float blend_top,
    float blend_bottom,
    int blend_mode,
    float blend_gamma,
    float crop_x,
    float crop_y,
    float crop_width,
    float crop_height,
    bool crop_enabled,
    py::object mask_obj)
{
    // --- Validate source shape (H, W, 4) ---
    auto src_buf = source.unchecked<3>();
    if (src_buf.shape(2) != 4) {
        throw std::runtime_error("source must have 4 channels (RGBA)");
    }
    int src_h = static_cast<int>(src_buf.shape(0));
    int src_w = static_cast<int>(src_buf.shape(1));

    // --- Validate projector_uvs shape (V, 2) ---
    auto pu_buf = projector_uvs.unchecked<2>();
    if (pu_buf.shape(1) != 2) {
        throw std::runtime_error("projector_uvs must have shape (V, 2)");
    }
    int num_verts = static_cast<int>(pu_buf.shape(0));

    // --- Validate content_uvs shape (V, 2) ---
    auto cu_buf = content_uvs.unchecked<2>();
    if (cu_buf.shape(0) != num_verts || cu_buf.shape(1) != 2) {
        throw std::runtime_error("content_uvs must have same shape as projector_uvs");
    }

    // --- Validate indices shape (F, 3) ---
    auto idx_buf = indices.unchecked<2>();
    if (idx_buf.shape(1) != 3) {
        throw std::runtime_error("indices must have shape (F, 3)");
    }
    int num_faces = static_cast<int>(idx_buf.shape(0));

    // --- Optional mask ---
    const double* mask_ptr = nullptr;
    int mask_h = 0;
    int mask_w = 0;
    py::array_t<double, py::array::c_style | py::array::forcecast> mask_arr;
    if (!mask_obj.is_none()) {
        mask_arr = mask_obj.cast<py::array_t<double, py::array::c_style | py::array::forcecast>>();
        auto m_buf = mask_arr.unchecked<2>();
        mask_h = static_cast<int>(m_buf.shape(0));
        mask_w = static_cast<int>(m_buf.shape(1));
        mask_ptr = m_buf.data(0, 0);
    }

    // --- Build params ---
    projectionai::BlendParams blend;
    blend.left   = blend_left;
    blend.right  = blend_right;
    blend.top    = blend_top;
    blend.bottom = blend_bottom;
    blend.mode   = blend_mode;
    blend.gamma  = blend_gamma;

    const auto* blend_ptr = &blend;

    projectionai::CropParams crop;
    crop.x       = crop_x;
    crop.y       = crop_y;
    crop.width   = crop_width;
    crop.height  = crop_height;
    crop.enabled = crop_enabled;

    const auto* crop_ptr = &crop;

    // --- Call C++ engine (release GIL — pure C++ computation) ---
    unsigned char* result = nullptr;
    {
        py::gil_scoped_release gil_release;
        result = projectionai::warp_engine(
            src_buf.data(0, 0, 0),
            src_h, src_w,
            pu_buf.data(0, 0), num_verts,
            cu_buf.data(0, 0),
            idx_buf.data(0, 0), num_faces,
            out_w, out_h,
            blend_ptr, crop_ptr,
            mask_ptr, mask_h, mask_w);
    }

    if (!result) {
        throw std::runtime_error("warp_engine returned nullptr (empty mesh or invalid inputs)");
    }

    // --- Copy to NumPy and free C buffer ---
    size_t out_size = static_cast<size_t>(out_w) * out_h * 4;
    py::array_t<uint8_t> out({out_h, out_w, 4});
    std::memcpy(out.mutable_data(0, 0, 0), result, out_size);

    projectionai::warp_engine_free(result);

    return out;
}

PYBIND11_MODULE(_warp_engine_native, m) {
    m.doc() = "C++ projection warp engine — deterministic forward triangle rasterization";

    m.def("warp", &py_warp,
          "Warp a source RGBA texture onto projector output space.",
          py::arg("source"),
          py::arg("projector_uvs"),
          py::arg("content_uvs"),
          py::arg("indices"),
          py::arg("output_width"),
          py::arg("output_height"),
          py::arg("blend_left")   = 0.0f,
          py::arg("blend_right")  = 0.0f,
          py::arg("blend_top")    = 0.0f,
          py::arg("blend_bottom") = 0.0f,
          py::arg("blend_mode")   = 0,
          py::arg("blend_gamma")  = 2.2f,
          py::arg("crop_x")       = 0.0f,
          py::arg("crop_y")       = 0.0f,
          py::arg("crop_width")   = 1.0f,
          py::arg("crop_height")  = 1.0f,
          py::arg("crop_enabled") = true,
          py::arg("mask")         = py::none());
}
