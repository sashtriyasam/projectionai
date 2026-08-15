"""Tests for AppConfig environment overrides (WP1 camera provider).

``AppConfig`` reads ``PROJECTIONAI_*`` environment variables; the
``camera_provider`` field must honor ``PROJECTIONAI_CAMERA_PROVIDER``
and fall back to the ``opencv`` default. ``load_config`` caching and
file-based loading are covered in the existing suite; here we only
pin the env contract that the shell entry point depends on.
"""

from __future__ import annotations

import pytest

from projectionai.core import config as config_module
from projectionai.core.config import AppConfig, load_config, reload_config


class TestCameraProviderEnv:
    def test_default_is_opencv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PROJECTIONAI_CAMERA_PROVIDER", raising=False)
        assert AppConfig().camera_provider == "opencv"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROJECTIONAI_CAMERA_PROVIDER", "mock")
        assert AppConfig().camera_provider == "mock"

    def test_env_override_lowercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROJECTIONAI_CAMERA_PROVIDER", "opencv")
        assert AppConfig().camera_provider == "opencv"


class TestLoadConfigSingleton:
    def test_reload_config_resets_camera_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PROJECTIONAI_CAMERA_PROVIDER", "mock")
        try:
            # Rebuild the singleton from the environment so a cached config
            # from an earlier test cannot leak into this one.
            reload_config()
            config = load_config()
            assert config.camera_provider == "mock"

            monkeypatch.setenv("PROJECTIONAI_CAMERA_PROVIDER", "opencv")
            reload_config()
            assert load_config().camera_provider == "opencv"
        finally:
            # Clear the singleton cache so no state leaks to later tests.
            config_module._config = None
