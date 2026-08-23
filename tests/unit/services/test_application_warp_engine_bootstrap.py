"""Application bootstrap validation for warp engine (Phase 5.10).

Tests the Application._init_warp_engine() lifecycle with mocked dependencies
to verify warp engine selection matches configuration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projectionai.app import Application
from projectionai.core.config import AppConfig
from projectionai.services import EngineMode, WarpEngineFactory
from projectionai.services.warp_engine_cpu import CpuWarpEngine


@pytest.fixture
def mock_config() -> AppConfig:
    """Create a test AppConfig with warp_engine_mode override."""
    return AppConfig(warp_engine_mode=EngineMode.AUTO)


class TestApplicationWarpEngineBootstrap:
    """Test Application warp engine initialization across all modes."""

    def _create_app(self, config: AppConfig) -> Application:
        """Create Application with mocked managers to avoid Qt/database dependencies."""
        app = Application(config)
        app._registry = MagicMock()
        app._registry.initialize_all = AsyncMock()
        app._registry.shutdown_all = AsyncMock()
        app._managers_initialized = True
        app._event_bus = MagicMock()
        app._event_bus.clear = AsyncMock()
        return app

    # Test A: AUTO mode → factory receives EngineMode.AUTO
    async def test_auto_requests_engine_mode_auto(self, mock_config: AppConfig) -> None:
        """AUTO mode should request EngineMode.AUTO from factory."""
        mock_config.warp_engine_mode = EngineMode.AUTO
        mock_engine = MagicMock()
        app = self._create_app(mock_config)

        with patch.object(
            WarpEngineFactory, "create", return_value=mock_engine
        ) as mock_create:
            await app._init_warp_engine()

            mock_create.assert_called_once_with(EngineMode.AUTO)
            assert app._warp_engine is mock_engine

    # Test B: AUTO + native unavailable → CpuWarpEngine
    async def test_auto_native_unavailable_fallbacks_to_cpu(
        self, mock_config: AppConfig
    ) -> None:
        """AUTO mode with native unavailable should fall back to CpuWarpEngine."""
        mock_config.warp_engine_mode = EngineMode.AUTO

        # Patch WarpEngineFactory.create to simulate native unavailable
        with patch.object(
            WarpEngineFactory,
            "create",
            side_effect=[RuntimeError("Native unavailable"), CpuWarpEngine()],
        ) as mock_create:
            app = self._create_app(mock_config)
            await app._init_warp_engine()

            assert app._warp_engine is not None
            assert isinstance(app._warp_engine, CpuWarpEngine)
            # Called twice: first AUTO (native), then fallback CPU
            assert mock_create.call_count == 2
            assert mock_create.call_args_list[0][0][0] == EngineMode.AUTO
            assert mock_create.call_args_list[1][0][0] == EngineMode.CPU

    # Test C: explicit CPU → CpuWarpEngine
    async def test_explicit_cpu_selects_cpu(self, mock_config: AppConfig) -> None:
        """Explicit CPU mode should always select CpuWarpEngine."""
        mock_config.warp_engine_mode = EngineMode.CPU
        app = self._create_app(mock_config)
        await app._init_warp_engine()

        assert app._warp_engine is not None
        assert isinstance(app._warp_engine, CpuWarpEngine)

    # Test D: native construction failure → CPU fallback
    async def test_native_construction_failure_fallbacks(
        self, mock_config: AppConfig
    ) -> None:
        """Native engine construction failure should fall back to CPU."""
        mock_config.warp_engine_mode = EngineMode.AUTO

        with patch.object(
            WarpEngineFactory,
            "create",
            side_effect=[
                RuntimeError("Native warp engine unavailable"),
                CpuWarpEngine(),
            ],
        ):
            app = self._create_app(mock_config)
            await app._init_warp_engine()

            assert app._warp_engine is not None
            assert isinstance(app._warp_engine, CpuWarpEngine)

    # Test E: explicit NATIVE with native unavailable → CPU fallback (configured fallback behavior)
    async def test_explicit_native_unavailable_fallbacks(
        self, mock_config: AppConfig
    ) -> None:
        """Explicit NATIVE mode with native unavailable should fall back to CPU (configured fallback)."""
        mock_config.warp_engine_mode = EngineMode.NATIVE

        with patch.object(
            WarpEngineFactory,
            "create",
            side_effect=[
                RuntimeError("Native warp engine unavailable"),
                CpuWarpEngine(),
            ],
        ):
            app = self._create_app(mock_config)
            await app._init_warp_engine()

            assert app._warp_engine is not None
            assert isinstance(app._warp_engine, CpuWarpEngine)

    # Test F: shutdown cleans up warp engine if it has shutdown
    async def test_shutdown_calls_warp_engine_shutdown_if_exists(
        self, mock_config: AppConfig
    ) -> None:
        """Shutdown should call warp_engine.shutdown() if it exists."""
        mock_config.warp_engine_mode = EngineMode.CPU
        app = self._create_app(mock_config)
        await app._init_warp_engine()

        # Add shutdown method to the engine
        app._warp_engine.shutdown = AsyncMock()

        await app.shutdown()

        app._warp_engine.shutdown.assert_called_once()

    # Test G: warp_engine property raises if not initialized
    def test_warp_engine_property_raises_when_uninitialized(
        self, mock_config: AppConfig
    ) -> None:
        """Accessing warp_engine before initialize() should raise RuntimeError."""
        app = Application(mock_config)

        with pytest.raises(RuntimeError, match="Warp engine not initialized"):
            _ = app.warp_engine

    # Test H: warp_engine property returns engine after initialize
    async def test_warp_engine_property_returns_after_init(
        self, mock_config: AppConfig
    ) -> None:
        """Accessing warp_engine after initialize() should return the engine."""
        mock_config.warp_engine_mode = EngineMode.CPU
        app = self._create_app(mock_config)
        await app._init_warp_engine()

        engine = app.warp_engine
        assert isinstance(engine, CpuWarpEngine)

    # Test I: config override via env var works
    async def test_env_var_override_works(self) -> None:
        """PROJECTIONAI_WARP_ENGINE_MODE env var should control engine selection."""
        import os

        with patch.dict(os.environ, {"PROJECTIONAI_WARP_ENGINE_MODE": "cpu"}):
            config = AppConfig()
            assert config.warp_engine_mode == EngineMode.CPU

        with patch.dict(os.environ, {"PROJECTIONAI_WARP_ENGINE_MODE": "native"}):
            config = AppConfig()
            assert config.warp_engine_mode == EngineMode.NATIVE

        with patch.dict(os.environ, {"PROJECTIONAI_WARP_ENGINE_MODE": "auto"}):
            config = AppConfig()
            assert config.warp_engine_mode == EngineMode.AUTO

    # Test J: initialize() calls _init_warp_engine after _init_calibrator
    async def test_initialize_calls_warp_engine_after_calibrator(
        self, mock_config: AppConfig, tmp_path: object
    ) -> None:
        """Full initialize() should call _init_warp_engine after _init_calibrator."""
        mock_config.data_dir = tmp_path  # type: ignore[assignment]
        call_order: list[str] = []

        # Mock all infrastructure _init_* methods to avoid host services
        mock_inits: dict[str, AsyncMock] = {}
        for name in (
            "_init_storage",
            "_init_ai_service",
            "_init_vision_pipeline",
            "_init_renderer",
            "_init_calibrator",
            "_init_warp_engine",
        ):
            mock = AsyncMock()

            def _make_cb(n: str) -> AsyncMock:
                def cb(**_kw: object) -> None:
                    call_order.append(n)

                cb_mock = AsyncMock(side_effect=cb)
                return cb_mock

            mock.side_effect = _make_cb(name)
            mock_inits[name] = mock

        app = self._create_app(mock_config)
        for name, mock_fn in mock_inits.items():
            setattr(app, name, mock_fn)

        await app.initialize()

        # Verify all infrastructure inits were called
        for name, mock_fn in mock_inits.items():
            mock_fn.assert_called_once()
        # Verify ordering: calibrator before warp_engine
        assert call_order.index("_init_calibrator") < call_order.index(
            "_init_warp_engine"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
