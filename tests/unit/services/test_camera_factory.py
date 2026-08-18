"""Tests for CameraProviderFactory built-in provider registration."""

from __future__ import annotations

import sys

import pytest

from projectionai.infrastructure.camera.mock_camera import MockCameraProvider
from projectionai.services.camera import CameraProviderFactory


def test_create_mock_registers_builtins_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create() works with an empty registry — built-ins load on demand."""
    monkeypatch.setattr(CameraProviderFactory, "_registry", {})
    assert "opencv" not in CameraProviderFactory.available()

    provider = CameraProviderFactory.create("mock")

    assert isinstance(provider, MockCameraProvider)
    assert "mock" in CameraProviderFactory.available()
    assert "opencv" not in CameraProviderFactory.available()


def test_create_mock_does_not_import_opencv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requesting the mock provider must never load the OpenCV module."""
    monkeypatch.delitem(
        sys.modules,
        "projectionai.infrastructure.camera.opencv_camera",
        raising=False,
    )
    monkeypatch.setattr(CameraProviderFactory, "_registry", {})

    CameraProviderFactory.create("mock")

    assert "projectionai.infrastructure.camera.opencv_camera" not in sys.modules


def test_create_opencv_registers_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default runtime provider is creatable without prior imports."""
    from projectionai.infrastructure.camera.opencv_camera import (
        OpenCVCameraProvider,
    )

    monkeypatch.setattr(CameraProviderFactory, "_registry", {})

    provider = CameraProviderFactory.create("opencv")

    assert isinstance(provider, OpenCVCameraProvider)


def test_create_unknown_key_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Genuinely unknown keys still raise after built-ins are ensured."""
    monkeypatch.setattr(CameraProviderFactory, "_registry", {})

    with pytest.raises(ValueError, match="Unknown camera provider: 'bogus'"):
        CameraProviderFactory.create("bogus")
