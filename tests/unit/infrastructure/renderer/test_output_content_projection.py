"""Tests for OutputContent PROJECTION variant.

Verifies the PROJECTION kind, factory method, invariants, and
interaction with existing kinds (PATTERN, BLACK, FREEZE).
"""

from __future__ import annotations

import pytest

from projectionai.hardware.patterns import PatternKind
from projectionai.infrastructure.renderer.output_content import (
    OutputContent,
    OutputContentKind,
)

# ---------------------------------------------------------------------------
# OutputContentKind.PROJECTION exists
# ---------------------------------------------------------------------------


def test_projection_kind_value() -> None:
    assert OutputContentKind.PROJECTION.value == "projection"


def test_all_four_kinds_exist() -> None:
    kinds = list(OutputContentKind)
    assert len(kinds) == 4
    assert OutputContentKind.PATTERN in kinds
    assert OutputContentKind.BLACK in kinds
    assert OutputContentKind.FREEZE in kinds
    assert OutputContentKind.PROJECTION in kinds


# ---------------------------------------------------------------------------
# OutputContent.projection() factory
# ---------------------------------------------------------------------------


def test_projection_factory_basic() -> None:
    mesh = object()
    tex = object()
    content = OutputContent.projection(warp_mesh=mesh, source_texture=tex)
    assert content.kind is OutputContentKind.PROJECTION
    assert content.warp_mesh is mesh
    assert content.source_texture is tex
    assert content.pattern_kind is None


def test_projection_factory_requires_warp_mesh() -> None:
    """PROJECTION without warp_mesh raises ValueError."""
    with pytest.raises(ValueError, match="requires a warp_mesh"):
        OutputContent.projection(warp_mesh=None, source_texture=object())


# ---------------------------------------------------------------------------
# Invariants: only PROJECTION may carry warp_mesh
# ---------------------------------------------------------------------------


def test_pattern_cannot_carry_warp_mesh() -> None:
    with pytest.raises(ValueError, match="Only PROJECTION"):
        OutputContent(
            kind=OutputContentKind.PATTERN,
            pattern_kind=PatternKind.RED,
            warp_mesh=object(),
        )


def test_black_cannot_carry_warp_mesh() -> None:
    with pytest.raises(ValueError, match="Only PROJECTION"):
        OutputContent(
            kind=OutputContentKind.BLACK,
            warp_mesh=object(),
        )


def test_freeze_cannot_carry_warp_mesh() -> None:
    with pytest.raises(ValueError, match="Only PROJECTION"):
        OutputContent(
            kind=OutputContentKind.FREEZE,
            warp_mesh=object(),
        )


def test_projection_must_have_warp_mesh() -> None:
    """PROJECTION kind without warp_mesh raises."""
    with pytest.raises(ValueError, match="requires a warp_mesh"):
        OutputContent(
            kind=OutputContentKind.PROJECTION,
            warp_mesh=None,
        )


# ---------------------------------------------------------------------------
# Invariants: PATTERN invariants unchanged
# ---------------------------------------------------------------------------


def test_pattern_requires_pattern_kind() -> None:
    with pytest.raises(ValueError, match="requires a pattern"):
        OutputContent(OutputContentKind.PATTERN)


def test_non_pattern_rejects_pattern_kind() -> None:
    with pytest.raises(ValueError, match="Only PATTERN"):
        OutputContent(OutputContentKind.BLACK, pattern_kind=PatternKind.RED)


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------


def test_projection_equality() -> None:
    mesh = object()
    tex = object()
    a = OutputContent.projection(warp_mesh=mesh, source_texture=tex)
    b = OutputContent.projection(warp_mesh=mesh, source_texture=tex)
    assert a == b


def test_projection_inequality_different_mesh() -> None:
    tex = object()
    a = OutputContent.projection(warp_mesh=object(), source_texture=tex)
    b = OutputContent.projection(warp_mesh=object(), source_texture=tex)
    assert a != b


def test_projection_not_equal_to_other_kinds() -> None:
    proj = OutputContent.projection(warp_mesh=object(), source_texture=object())
    assert proj != OutputContent.black()
    assert proj != OutputContent.freeze()
    assert proj != OutputContent.pattern(PatternKind.RED)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_projection_content_is_immutable() -> None:
    content = OutputContent.projection(warp_mesh=object(), source_texture=object())
    with pytest.raises(AttributeError, match="cannot assign"):
        content.kind = OutputContentKind.BLACK  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Source texture can be None (mesh required, texture optional)
# ---------------------------------------------------------------------------


def test_projection_with_none_source_texture() -> None:
    """source_texture is not validated at construction — it can be None."""
    content = OutputContent.projection(warp_mesh=object(), source_texture=None)
    assert content.source_texture is None
    assert content.kind is OutputContentKind.PROJECTION
