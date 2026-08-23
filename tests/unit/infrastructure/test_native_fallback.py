"""Tests for the _native package import fallback mechanism.

Verifies that importing projectionai._native never fails,
regardless of whether the C++ extension is compiled.
"""

from __future__ import annotations

import importlib

import pytest


class TestNativeImportFallback:
    """Verify graceful degradation when the C++ extension is absent."""

    def test_native_module_importable(self) -> None:
        """projectionai._native always imports without error."""
        from projectionai._native import AVAILABLE

        assert isinstance(AVAILABLE, bool)

    def test_available_matches_import(self) -> None:
        """AVAILABLE flag is True iff the .so/.pyd can actually be loaded."""
        from projectionai._native import AVAILABLE

        if AVAILABLE:
            mod = importlib.import_module("projectionai._warp_engine_native")
            assert hasattr(mod, "warp")
        else:
            with pytest.raises(ImportError):
                importlib.import_module("projectionai._warp_engine_native")

    def test_native_warp_is_callable_when_available(self) -> None:
        """If AVAILABLE=True, native_warp must be callable."""
        from projectionai._native import AVAILABLE, native_warp

        if AVAILABLE:
            assert callable(native_warp)
        else:
            assert native_warp is None
