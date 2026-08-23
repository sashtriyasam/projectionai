"""Tests for the native C++ warp engine binding.

These tests exercise the Python→C++ interface via projectionai._native.
If the native extension is not compiled, all tests are skipped.
"""

from __future__ import annotations

import numpy as np
import pytest

from projectionai._native import AVAILABLE, native_warp

pytestmark = pytest.mark.skipif(
    not AVAILABLE, reason="C++ warp engine extension not compiled"
)


class TestNativeBindingBasic:
    """Basic smoke tests for the native warp binding."""

    def test_single_triangle_identity(self) -> None:
        """Full-quad identity warp produces uniform output from a solid source."""
        assert native_warp is not None

        src = np.full((4, 4, 4), [100, 200, 50, 255], dtype=np.uint8)

        # Projector UVs cover full output quad
        proj_uvs = np.array(
            [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            dtype=np.float64,
        )
        # Content UVs cover full source quad
        con_uvs = np.array(
            [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            dtype=np.float64,
        )
        # Two triangles: (0,1,2) and (1,3,2)
        indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)

        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            4,
            4,
        )

        assert out.shape == (4, 4, 4)
        assert out.dtype == np.uint8
        # All pixels should be close to the source colour
        assert np.all(np.abs(out[:, :, 0].astype(int) - 100) <= 2)
        assert np.all(np.abs(out[:, :, 1].astype(int) - 200) <= 2)
        assert np.all(np.abs(out[:, :, 2].astype(int) - 50) <= 2)

    def test_output_shape(self) -> None:
        """Output dimensions match requested output_width, output_height."""
        assert native_warp is not None

        src = np.zeros((2, 2, 4), dtype=np.uint8)
        proj_uvs = np.array(
            [[0, 0], [1, 0], [0, 1], [1, 1]],
            dtype=np.float64,
        )
        con_uvs = np.array(
            [[0, 0], [1, 0], [0, 1], [1, 1]],
            dtype=np.float64,
        )
        indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)

        out = native_warp(src, proj_uvs, con_uvs, indices, 8, 16)
        assert out.shape == (16, 8, 4)


class TestNativeBindingParams:
    """Test blend, crop, and mask parameters through the binding."""

    def _identity_inputs(
        self, src_size: int = 4
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        src = np.full((src_size, src_size, 4), 200, dtype=np.uint8)
        proj_uvs = np.array(
            [[0, 0], [1, 0], [0, 1], [1, 1]],
            dtype=np.float64,
        )
        con_uvs = np.array(
            [[0, 0], [1, 0], [0, 1], [1, 1]],
            dtype=np.float64,
        )
        indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
        return src, proj_uvs, con_uvs, indices

    def test_blend_left_reduces_intensity(self) -> None:
        """Left blend ramp dims the leftmost columns."""
        assert native_warp is not None

        src, proj_uvs, con_uvs, indices = self._identity_inputs(4)
        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            4,
            4,
            blend_left=0.5,
        )
        # Leftmost column should be dimmer than the rightmost
        left_val = int(out[0, 0, 0])
        right_val = int(out[0, 3, 0])
        assert left_val < right_val
        assert left_val < 50  # Should be heavily dimmed

    def test_crop_blacks_outside(self) -> None:
        """Crop zeroes pixels outside the crop region."""
        assert native_warp is not None

        src, proj_uvs, con_uvs, indices = self._identity_inputs(4)
        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            4,
            4,
            crop_x=0.25,
            crop_y=0.25,
            crop_width=0.5,
            crop_height=0.5,
            crop_enabled=True,
        )
        # Corner should be black
        assert out[0, 0, 0] == 0
        assert out[0, 0, 1] == 0
        assert out[0, 0, 2] == 0

    def test_mask_applied(self) -> None:
        """Mask dims the output according to mask values."""
        assert native_warp is not None

        src, proj_uvs, con_uvs, indices = self._identity_inputs(4)
        mask = np.ones((4, 4), dtype=np.float64)
        mask[0, 0] = 0.0  # Black out top-left

        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            4,
            4,
            mask=mask,
        )
        # Where mask=0, pixel should be black
        assert out[0, 0, 0] == 0
        # Where mask=1, pixel should be bright
        assert out[2, 2, 0] > 100


class TestNativeBindingErrors:
    """Test error handling in the native binding."""

    def test_empty_mesh_raises(self) -> None:
        """Zero-vertex mesh should raise RuntimeError."""
        assert native_warp is not None

        src = np.zeros((2, 2, 4), dtype=np.uint8)
        empty_uvs = np.zeros((0, 2), dtype=np.float64)
        empty_idx = np.zeros((0, 3), dtype=np.int32)

        with pytest.raises(RuntimeError, match="content_uvs must have same shape"):
            native_warp(src, empty_uvs, empty_idx[:, :3], empty_idx, 2, 2)


class TestNativeBindingBlending:
    """Detailed blend parameter tests."""

    def _full_white(
        self, size: int = 8
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        src = np.full((size, size, 4), 255, dtype=np.uint8)
        proj_uvs = np.array(
            [[0, 0], [1, 0], [0, 1], [1, 1]],
            dtype=np.float64,
        )
        con_uvs = np.array(
            [[0, 0], [1, 0], [0, 1], [1, 1]],
            dtype=np.float64,
        )
        indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
        return src, proj_uvs, con_uvs, indices

    def test_right_blend(self) -> None:
        assert native_warp is not None
        src, proj_uvs, con_uvs, indices = self._full_white()
        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            8,
            8,
            blend_right=0.25,
        )
        # Rightmost column should be dimmer
        assert int(out[0, 7, 0]) < 200

    def test_top_blend(self) -> None:
        assert native_warp is not None
        src, proj_uvs, con_uvs, indices = self._full_white()
        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            8,
            8,
            blend_top=0.5,
        )
        # Top row should be dimmer
        assert int(out[0, 4, 0]) < 200

    def test_bottom_blend(self) -> None:
        assert native_warp is not None
        src, proj_uvs, con_uvs, indices = self._full_white()
        out = native_warp(
            src,
            proj_uvs,
            con_uvs,
            indices,
            8,
            8,
            blend_bottom=0.5,
        )
        # Bottom row should be dimmer
        assert int(out[7, 4, 0]) < 200
