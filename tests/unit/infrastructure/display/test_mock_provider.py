"""Tests for MockDisplayProvider topology handling."""

from __future__ import annotations

from projectionai.infrastructure.display.mock_provider import (
    MockDisplayProvider,
    default_displays,
)


def test_empty_list_stays_empty() -> None:
    provider = MockDisplayProvider([])

    assert provider._displays == {}


def test_none_falls_back_to_defaults() -> None:
    provider = MockDisplayProvider()

    defaults = default_displays()
    assert list(provider._displays) == [d.display_id for d in defaults]
    assert list(provider._displays.values()) == defaults


def test_provided_displays_mapped_by_id() -> None:
    defaults = default_displays()
    subset = defaults[:1]
    provider = MockDisplayProvider(subset)

    assert list(provider._displays) == [defaults[0].display_id]
    assert provider._displays[defaults[0].display_id] is defaults[0]
