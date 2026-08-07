"""Tests for DisplayProviderFactory built-in provider registration."""

from __future__ import annotations

import pytest

from projectionai.infrastructure.display.mock_provider import MockDisplayProvider
from projectionai.services.display import DisplayProviderFactory


def test_create_mock_registers_builtins_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """create() works with an empty registry — built-ins load on demand."""
    monkeypatch.setattr(DisplayProviderFactory, "_registry", {})

    provider = DisplayProviderFactory.create("mock")

    assert isinstance(provider, MockDisplayProvider)
    assert "mock" in DisplayProviderFactory.available()
    assert "qt" in DisplayProviderFactory.available()


def test_create_unknown_key_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Genuinely unknown keys still raise after built-ins are ensured."""
    monkeypatch.setattr(DisplayProviderFactory, "_registry", {})

    with pytest.raises(ValueError, match="Unknown display provider: 'bogus'"):
        DisplayProviderFactory.create("bogus")
