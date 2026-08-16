"""Tests for the Qt-free output content model."""

from __future__ import annotations

import pytest

from projectionai.hardware.patterns import PatternKind
from projectionai.infrastructure.renderer.output_content import (
    OutputContent,
    OutputContentKind,
)


def test_black_content() -> None:
    content = OutputContent.black()
    assert content.kind is OutputContentKind.BLACK
    assert content.pattern_kind is None


def test_freeze_content() -> None:
    content = OutputContent.freeze()
    assert content.kind is OutputContentKind.FREEZE
    assert content.pattern_kind is None


def test_pattern_content() -> None:
    content = OutputContent.pattern(PatternKind.RED)
    assert content.kind is OutputContentKind.PATTERN
    assert content.pattern_kind is PatternKind.RED


def test_pattern_content_requires_pattern() -> None:
    with pytest.raises(ValueError, match="requires a pattern"):
        OutputContent(OutputContentKind.PATTERN, None)


def test_non_pattern_content_rejects_pattern() -> None:
    with pytest.raises(ValueError, match="Only PATTERN"):
        OutputContent(OutputContentKind.BLACK, PatternKind.RED)


def test_equality() -> None:
    assert OutputContent.black() == OutputContent.black()
    assert OutputContent.freeze() == OutputContent.freeze()
    assert OutputContent.pattern(PatternKind.RED) == OutputContent.pattern(
        PatternKind.RED
    )
    assert OutputContent.pattern(PatternKind.RED) != OutputContent.pattern(
        PatternKind.BLUE
    )
    assert OutputContent.black() != OutputContent.freeze()
    assert OutputContent.black() != OutputContent.pattern(PatternKind.BLACK)


def test_kind_is_str_enum() -> None:
    assert str(OutputContentKind.BLACK) == "black"
    assert str(OutputContentKind.FREEZE) == "freeze"
    assert str(OutputContentKind.PATTERN) == "pattern"


def test_content_is_immutable() -> None:
    content = OutputContent.pattern(PatternKind.RED)
    with pytest.raises(AttributeError, match="cannot assign"):
        content.kind = OutputContentKind.BLACK  # type: ignore[misc]
