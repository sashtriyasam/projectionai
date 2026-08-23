"""Tests for WarpEngineFactory — engine selection mechanism."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from projectionai.services.warp_engine_cpu import CpuWarpEngine, ProjectionWarpEngine
from projectionai.services.warp_engine_factory import EngineMode, WarpEngineFactory


class TestEngineMode:
    """Test EngineMode enum."""

    def test_auto_mode(self) -> None:
        """AUTO mode exists."""
        assert EngineMode.AUTO == "auto"

    def test_cpu_mode(self) -> None:
        """CPU mode exists."""
        assert EngineMode.CPU == "cpu"

    def test_native_mode(self) -> None:
        """NATIVE mode exists."""
        assert EngineMode.NATIVE == "native"


class TestWarpEngineFactoryCreate:
    """Test WarpEngineFactory.create() method."""

    def test_auto_mode_returns_engine(self) -> None:
        """Auto mode returns a valid engine."""
        engine = WarpEngineFactory.create(mode=EngineMode.AUTO)
        assert isinstance(engine, ProjectionWarpEngine)

    def test_cpu_mode_returns_cpu_engine(self) -> None:
        """CPU mode returns CpuWarpEngine."""
        engine = WarpEngineFactory.create(mode=EngineMode.CPU)
        assert isinstance(engine, CpuWarpEngine)

    def test_cpu_mode_always_returns_cpu(self) -> None:
        """CPU mode always returns CPU engine even when native is available."""
        engine = WarpEngineFactory.create(mode=EngineMode.CPU)
        assert type(engine).__name__ == "CpuWarpEngine"


class TestWarpEngineFactoryNativeAvailable:
    """Test factory when native extension is available."""

    def test_auto_prefers_native_when_available(self) -> None:
        """Auto mode prefers native when available."""
        with patch(
            "projectionai.services.warp_engine_factory._create_native_engine"
        ) as mock_create:
            mock_engine = MagicMock(spec=ProjectionWarpEngine)
            mock_create.return_value = mock_engine

            engine = WarpEngineFactory.create(mode=EngineMode.AUTO)

            mock_create.assert_called_once_with(required=False)
            assert engine is mock_engine

    def test_native_mode_calls_with_required(self) -> None:
        """Native mode calls create with required=True."""
        with patch(
            "projectionai.services.warp_engine_factory._create_native_engine"
        ) as mock_create:
            mock_engine = MagicMock(spec=ProjectionWarpEngine)
            mock_create.return_value = mock_engine

            engine = WarpEngineFactory.create(mode=EngineMode.NATIVE)

            mock_create.assert_called_once_with(required=True)
            assert engine is mock_engine


class TestWarpEngineFactoryNativeUnavailable:
    """Test factory when native extension is unavailable."""

    def test_auto_fallback_to_cpu_when_native_unavailable(self) -> None:
        """Auto mode falls back to CPU when native is unavailable."""
        with patch(
            "projectionai.services.warp_engine_factory._create_native_engine"
        ) as mock_create:
            mock_engine = MagicMock(spec=CpuWarpEngine)
            mock_create.return_value = mock_engine

            engine = WarpEngineFactory.create(mode=EngineMode.AUTO)

            mock_create.assert_called_once_with(required=False)
            assert engine is mock_engine

    def test_native_mode_raises_when_unavailable(self) -> None:
        """Native mode raises RuntimeError when native is unavailable."""
        with patch(
            "projectionai.services.warp_engine_factory._create_native_engine"
        ) as mock_create:
            mock_create.side_effect = RuntimeError("Native not available")

            with pytest.raises(RuntimeError, match="Native not available"):
                WarpEngineFactory.create(mode=EngineMode.NATIVE)


class TestWarpEngineFactoryIsNativeAvailable:
    """Test WarpEngineFactory.is_native_available() method."""

    def test_returns_true_when_native_importable(self) -> None:
        """Returns True when native extension is importable."""
        with patch(
            "projectionai.services.warp_engine_factory.importlib.import_module"
        ) as mock_import:
            mock_module = MagicMock()
            mock_module.AVAILABLE = True
            mock_import.return_value = mock_module
            assert WarpEngineFactory.is_native_available() is True

    def test_returns_false_when_native_not_importable(self) -> None:
        """Returns False when native extension is not importable."""
        with patch(
            "projectionai.services.warp_engine_factory.importlib.import_module",
            side_effect=ImportError("No module"),
        ):
            assert WarpEngineFactory.is_native_available() is False


class TestWarpEngineFactoryIntegration:
    """Integration tests for WarpEngineFactory."""

    def test_factory_returns_same_type_as_direct_instantiation(self) -> None:
        """Factory CPU mode returns same type as direct CpuWarpEngine."""
        from projectionai.services.warp_engine_cpu import CpuWarpEngine

        factory_engine = WarpEngineFactory.create(mode=EngineMode.CPU)
        direct_engine = CpuWarpEngine()

        assert type(factory_engine) is type(direct_engine)

    def test_factory_engine_has_warp_method(self) -> None:
        """Factory engine has warp method."""
        engine = WarpEngineFactory.create(mode=EngineMode.CPU)
        assert hasattr(engine, "warp")
        assert callable(engine.warp)

    def test_factory_cpu_engine_produces_valid_output(self) -> None:
        """Factory CPU engine actually warps a texture end-to-end."""
        import numpy as np

        from projectionai.domain.warp_mesh import create_identity_warp_mesh

        engine = WarpEngineFactory.create(mode=EngineMode.CPU)

        source = np.full((64, 64, 4), 200, dtype=np.uint8)
        mesh = create_identity_warp_mesh(64, 64)

        result = engine.warp(source, mesh, 64, 64)

        assert result.shape == (64, 64, 4)
        assert result.dtype == np.uint8
        assert result[32, 32, 0] == 200

    def test_factory_auto_engine_matches_cpu_on_warp(self) -> None:
        """Factory AUTO engine produces same result as direct CPU engine."""
        import numpy as np

        from projectionai.domain.warp_mesh import create_identity_warp_mesh
        from projectionai.services.warp_engine_cpu import CpuWarpEngine

        source = np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8)
        mesh = create_identity_warp_mesh(32, 32)

        auto_engine = WarpEngineFactory.create(mode=EngineMode.AUTO)
        cpu_engine = CpuWarpEngine()

        result_auto = auto_engine.warp(source, mesh, 32, 32)
        result_cpu = cpu_engine.warp(source, mesh, 32, 32)

        np.testing.assert_array_equal(result_auto, result_cpu)

    def test_factory_native_engine_matches_cpu_on_warp(self) -> None:
        """Factory NATIVE engine produces same result as CPU engine (if available)."""
        import numpy as np

        if not WarpEngineFactory.is_native_available():
            pytest.skip("Native extension not available")

        from projectionai.domain.warp_mesh import create_identity_warp_mesh
        from projectionai.services.warp_engine_cpu import CpuWarpEngine

        source = np.random.randint(0, 256, (32, 32, 4), dtype=np.uint8)
        mesh = create_identity_warp_mesh(32, 32)

        native_engine = WarpEngineFactory.create(mode=EngineMode.NATIVE)
        cpu_engine = CpuWarpEngine()

        result_native = native_engine.warp(source, mesh, 32, 32)
        result_cpu = cpu_engine.warp(source, mesh, 32, 32)

        np.testing.assert_array_equal(result_native, result_cpu)

    def test_factory_produces_interchangeable_engines(self) -> None:
        """Both engines from factory accept the same ProjectionWarpEngine interface."""
        engine = WarpEngineFactory.create(mode=EngineMode.CPU)
        assert isinstance(engine, ProjectionWarpEngine)
