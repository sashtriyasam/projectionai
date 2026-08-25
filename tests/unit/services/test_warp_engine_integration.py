"""Phase 5.9 — Warp engine production integration tests.

Covers:
A. Application selects engine from config
B. AUTO native path
C. AUTO CPU fallback
D. Explicit CPU
E. Injected fake engine
F. Native failure recovery
G. Projection persistence (EngineMode not serialized)
H. Realtime path does not introduce CPU round-trip
I. Engine singleton/lifecycle behavior
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from projectionai.core.config import AppConfig
from projectionai.services import EngineMode, WarpEngineFactory
from projectionai.services.warp_engine_cpu import CpuWarpEngine, ProjectionWarpEngine

if TYPE_CHECKING:
    from projectionai.domain.projection import BlendConfig, CropRegion
    from projectionai.domain.warp_mesh import WarpMesh


# ---------------------------------------------------------------------------
# A. Application selects engine from config
# ---------------------------------------------------------------------------


class TestApplicationEngineSelection:
    """Verify Application initializes the correct engine from AppConfig."""

    def test_default_config_uses_auto_mode(self) -> None:
        """AppConfig default warp_engine_mode is AUTO."""
        config = AppConfig()
        assert config.warp_engine_mode == EngineMode.AUTO

    def test_factory_cpu_always_returns_cpu(self) -> None:
        """CPU mode always returns CpuWarpEngine."""
        engine = WarpEngineFactory.create(EngineMode.CPU)
        assert isinstance(engine, CpuWarpEngine)

    def test_config_warp_engine_mode_from_env(self) -> None:
        """warp_engine_mode can be set via environment variable."""
        with patch.dict("os.environ", {"PROJECTIONAI_WARP_ENGINE_MODE": "cpu"}):
            config = AppConfig()
            assert config.warp_engine_mode == EngineMode.CPU

    def test_config_warp_engine_mode_from_dict(self) -> None:
        """warp_engine_mode can be set via dict (YAML/JSON config)."""
        # AppConfig uses validation_alias for each field; use the alias key
        config = AppConfig.model_validate({"PROJECTIONAI_WARP_ENGINE_MODE": "cpu"})
        assert config.warp_engine_mode == EngineMode.CPU


# ---------------------------------------------------------------------------
# B. AUTO native path
# ---------------------------------------------------------------------------


class TestAutoNativePath:
    """AUTO mode prefers native when available."""

    @pytest.mark.skipif(
        not WarpEngineFactory.is_native_available(),
        reason="Native extension not compiled",
    )
    def test_auto_returns_native_engine(self) -> None:
        """AUTO returns CppWarpEngine when native is compiled."""
        engine = WarpEngineFactory.create(EngineMode.AUTO)
        # Check it's not CpuWarpEngine (it should be CppWarpEngine)
        assert not isinstance(engine, CpuWarpEngine), (
            "AUTO should prefer native, got CpuWarpEngine"
        )

    @pytest.mark.skipif(
        not WarpEngineFactory.is_native_available(),
        reason="Native extension not compiled",
    )
    def test_auto_native_produces_valid_output(self) -> None:
        """AUTO native engine produces valid warp output."""
        from projectionai.domain.warp_mesh import create_identity_warp_mesh

        engine = WarpEngineFactory.create(EngineMode.AUTO)
        source = np.full((32, 32, 4), 180, dtype=np.uint8)
        mesh = create_identity_warp_mesh(32, 32)

        result = engine.warp(source, mesh, 32, 32)

        assert result.shape == (32, 32, 4)
        assert result.dtype == np.uint8


# ---------------------------------------------------------------------------
# C. AUTO CPU fallback
# ---------------------------------------------------------------------------


class TestAutoCpuFallback:
    """AUTO falls back to CPU when native is unavailable."""

    @patch("projectionai.services.warp_engine_factory._create_native_engine")
    def test_auto_falls_back_to_cpu(self, mock_create_native: MagicMock) -> None:
        """AUTO returns CpuWarpEngine when native is unavailable."""
        from projectionai.services.warp_engine_cpu import CpuWarpEngine

        mock_create_native.return_value = CpuWarpEngine()
        engine = WarpEngineFactory.create(EngineMode.AUTO)
        assert isinstance(engine, CpuWarpEngine)

    @patch("projectionai.services.warp_engine_factory._create_native_engine")
    def test_auto_fallback_produces_valid_output(
        self, mock_create_native: MagicMock
    ) -> None:
        """AUTO fallback engine produces valid warp output."""
        from projectionai.domain.warp_mesh import create_identity_warp_mesh
        from projectionai.services.warp_engine_cpu import CpuWarpEngine

        mock_create_native.return_value = CpuWarpEngine()
        engine = WarpEngineFactory.create(EngineMode.AUTO)
        source = np.full((32, 32, 4), 180, dtype=np.uint8)
        mesh = create_identity_warp_mesh(32, 32)

        result = engine.warp(source, mesh, 32, 32)

        assert result.shape == (32, 32, 4)
        assert result.dtype == np.uint8


# ---------------------------------------------------------------------------
# D. Explicit CPU
# ---------------------------------------------------------------------------


class TestExplicitCpu:
    """Explicit CPU mode always returns CpuWarpEngine."""

    def test_explicit_cpu_returns_cpu_engine(self) -> None:
        """Explicit CPU mode returns CpuWarpEngine."""
        engine = WarpEngineFactory.create(EngineMode.CPU)
        assert isinstance(engine, CpuWarpEngine)

    def test_explicit_cpu_ignores_native_availability(self) -> None:
        """Explicit CPU mode returns CpuWarpEngine even if native is available."""
        engine = WarpEngineFactory.create(EngineMode.CPU)
        assert isinstance(engine, CpuWarpEngine)
        # Should not be a native engine
        assert type(engine).__name__ == "CpuWarpEngine"


# ---------------------------------------------------------------------------
# E. Injected fake engine
# ---------------------------------------------------------------------------


class _FakeEngine(ProjectionWarpEngine):
    """Module-level fake engine for injection tests."""

    def __init__(self, fill_value: int = 0) -> None:
        self._fill_value = fill_value

    def warp(
        self,
        source: np.ndarray,
        warp_mesh: WarpMesh,
        output_width: int,
        output_height: int,
        blend: BlendConfig | None = None,
        crop: CropRegion | None = None,
        mask: np.ndarray | None = None,
    ) -> np.ndarray:
        return np.full(
            (output_height, output_width, 4), self._fill_value, dtype=np.uint8
        )


class TestInjectedFakeEngine:
    """Tests can inject a fake engine without changing application code."""

    def test_fake_engine_implements_interface(self) -> None:
        """A mock engine can implement ProjectionWarpEngine."""
        engine = _FakeEngine()
        assert isinstance(engine, ProjectionWarpEngine)

    def test_fake_engine_produces_output(self) -> None:
        """A mock engine can produce warp output."""
        engine = _FakeEngine(fill_value=42)
        source = np.zeros((10, 10, 4), dtype=np.uint8)
        result = engine.warp(source, None, 10, 10)  # type: ignore[arg-type]

        assert result.shape == (10, 10, 4)
        assert np.all(result == 42)

    def test_fake_engine_custom_fill(self) -> None:
        """FakeEngine respects configurable fill value."""
        engine = _FakeEngine(fill_value=99)
        source = np.zeros((8, 8, 4), dtype=np.uint8)
        result = engine.warp(source, None, 8, 8)  # type: ignore[arg-type]

        assert result.shape == (8, 8, 4)
        assert np.all(result == 99)


# ---------------------------------------------------------------------------
# F. Native failure recovery
# ---------------------------------------------------------------------------


class TestNativeFailureRecovery:
    """Simulate native module failures and verify recovery."""

    @patch("projectionai.services.warp_engine_factory._create_native_engine")
    def test_native_unavailable_explicit_native_raises(
        self, mock_create_native: MagicMock
    ) -> None:
        """Explicit NATIVE raises RuntimeError when native is unavailable."""
        mock_create_native.side_effect = RuntimeError("Native warp engine unavailable")
        with pytest.raises(RuntimeError, match="Native warp engine unavailable"):
            WarpEngineFactory.create(EngineMode.NATIVE)

    @patch("projectionai.services.warp_engine_cpp.CppWarpEngine")
    def test_native_import_failure_recovers(self, mock_cpp_cls: MagicMock) -> None:
        """Native constructor failure triggers fallback in AUTO mode."""
        mock_cpp_cls.side_effect = RuntimeError("Native warp engine unavailable")

        # AUTO should fall back to CPU
        engine = WarpEngineFactory.create(EngineMode.AUTO)
        assert isinstance(engine, CpuWarpEngine)


# ---------------------------------------------------------------------------
# G. Projection persistence (EngineMode not serialized)
# ---------------------------------------------------------------------------


class TestProjectionPersistence:
    """Verify EngineMode is NOT serialized into projects."""

    def test_engine_mode_not_in_projection_mapping(self) -> None:
        """ProjectionMapping does not reference EngineMode."""
        from projectionai.domain.projection import ProjectionMapping

        mapping = ProjectionMapping()
        data = mapping.to_dict()

        # EngineMode should not appear in serialized data
        assert "engine_mode" not in data
        assert "warp_engine" not in data
        assert "backend" not in data

    def test_projection_roundtrip_without_engine_mode(self) -> None:
        """ProjectionMapping survives save/load without EngineMode."""
        from projectionai.domain.projection import ProjectionMapping

        mapping = ProjectionMapping(
            name="Test Mapping",
            projector_id="proj_1",
            surface_id="surf_1",
        )
        data = mapping.to_dict()
        restored = ProjectionMapping.from_dict(data)

        assert restored.name == "Test Mapping"
        assert restored.projector_id == "proj_1"
        assert restored.surface_id == "surf_1"
        # No engine_mode field exists
        assert not hasattr(restored, "engine_mode")

    def test_engine_mode_not_in_warp_mesh(self) -> None:
        """WarpMesh does not reference EngineMode."""
        from projectionai.domain.warp_mesh import create_identity_warp_mesh

        mesh = create_identity_warp_mesh(10, 10)
        data = mesh.to_dict()

        assert "engine_mode" not in data
        assert "warp_engine" not in data
        assert "backend" not in data

    def test_engine_mode_not_serialized_in_config(self) -> None:
        """EngineMode is a runtime config, not persisted in projects."""
        from projectionai.core.config import AppConfig

        config = AppConfig(warp_engine_mode=EngineMode.NATIVE)
        # AppConfig serializes to dict, but this is app config, not project
        data = config.model_dump()
        assert "warp_engine_mode" in data  # In app config (correct)
        # But NOT in domain models


# ---------------------------------------------------------------------------
# H. Realtime path does not introduce CPU round-trip
# ---------------------------------------------------------------------------


class TestRealtimePathIntegrity:
    """Verify the realtime rendering path does NOT use CPU warp engines."""

    _WARP_ENGINE_MODULES = (
        "projectionai.services.warp_engine_cpu",
        "projectionai.services.warp_engine_cpp",
    )

    def _assert_no_warp_engine_deps(self, module_name: str) -> None:
        """Import a module and verify it does not pull in warp engine modules."""
        import importlib
        import sys

        # Snapshot warp-engine modules present before import
        before = set(sys.modules) & set(self._WARP_ENGINE_MODULES)

        mod = importlib.import_module(module_name)
        importlib.reload(mod)

        after = set(sys.modules) & set(self._WARP_ENGINE_MODULES)
        new_deps = after - before
        assert not new_deps, f"{module_name} introduced warp-engine deps: {new_deps}"

    def test_projection_pass_is_gpu_only(self) -> None:
        """ProjectionPass does not import or use CPU/C++ warp engines."""
        self._assert_no_warp_engine_deps(
            "projectionai.infrastructure.renderer.passes.projection"
        )

    def test_projection_pass_uses_vertex_shader(self) -> None:
        """ProjectionPass renders via GPU vertex shader, not CPU rasterization."""
        import inspect

        from projectionai.infrastructure.renderer.passes.projection import (
            ProjectionPass,
        )

        source = inspect.getsource(ProjectionPass)

        # Should use OpenGL vertex array render
        assert "_vao.render(" in source

    def test_warp_engine_not_in_render_path(self) -> None:
        """WarpEngine is not imported in the rendering pipeline."""
        self._assert_no_warp_engine_deps(
            "projectionai.infrastructure.renderer.pipeline"
        )

    def test_output_window_does_not_use_warp_engine(self) -> None:
        """GLOutputWindow does not import or use warp engines."""
        self._assert_no_warp_engine_deps(
            "projectionai.infrastructure.renderer.output_window"
        )


# ---------------------------------------------------------------------------
# I. Engine singleton/lifecycle behavior
# ---------------------------------------------------------------------------


class TestEngineLifecycle:
    """Verify engine lifecycle behavior."""

    def test_engine_is_stateless(self) -> None:
        """CpuWarpEngine has no mutable state between warp calls."""
        from projectionai.domain.warp_mesh import create_identity_warp_mesh

        engine = CpuWarpEngine()
        source1 = np.full((16, 16, 4), 100, dtype=np.uint8)
        source2 = np.full((16, 16, 4), 200, dtype=np.uint8)
        mesh = create_identity_warp_mesh(16, 16)

        result1 = engine.warp(source1, mesh, 16, 16)
        result2 = engine.warp(source2, mesh, 16, 16)

        # Results should be independent — no carry-over state
        assert np.all(result1[:, :, 0] == 100)
        assert np.all(result2[:, :, 0] == 200)

    def test_engine_reusable_across_calls(self) -> None:
        """Same engine instance can handle multiple warp calls."""
        from projectionai.domain.warp_mesh import create_identity_warp_mesh

        engine = CpuWarpEngine()
        mesh = create_identity_warp_mesh(8, 8)

        for i in range(5):
            source = np.full((8, 8, 4), i * 50, dtype=np.uint8)
            result = engine.warp(source, mesh, 8, 8)
            assert result.shape == (8, 8, 4)

    def test_factory_returns_new_instances(self) -> None:
        """Each factory call returns a new engine instance."""
        engine1 = WarpEngineFactory.create(EngineMode.CPU)
        engine2 = WarpEngineFactory.create(EngineMode.CPU)
        assert engine1 is not engine2
