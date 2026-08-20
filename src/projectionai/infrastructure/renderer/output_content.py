"""Output content — Qt-free description of what an output window displays.

The hardware subsystem describes output *state* (live, blackout, freeze...)
while the renderer shows *content*. This module defines the immutable,
Qt-free content model consumed by :class:`GLOutputWindow`; the UI layer
maps session state onto content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from projectionai.hardware.patterns import PatternKind


class OutputContentKind(StrEnum):
    """What the output window should display."""

    PATTERN = "pattern"  # a named test pattern or solid colour
    BLACK = "black"  # pure black (blackout)
    FREEZE = "freeze"  # hold the last shown frame


@dataclass(frozen=True)
class OutputContent:
    """Immutable content descriptor for the projector output window.

    ``pattern_kind`` is only meaningful when ``kind`` is ``PATTERN``;
    the invariant is enforced at construction time.
    """

    kind: OutputContentKind
    pattern_kind: PatternKind | None = None

    def __post_init__(self) -> None:
        if self.kind is OutputContentKind.PATTERN and self.pattern_kind is None:
            raise ValueError("OutputContent.pattern(...) requires a pattern")
        if self.kind is not OutputContentKind.PATTERN and self.pattern_kind is not None:
            raise ValueError("Only PATTERN content may carry a pattern")

    @classmethod
    def pattern(cls, pattern: PatternKind) -> OutputContent:
        """Display the named test pattern / solid colour."""
        return cls(OutputContentKind.PATTERN, pattern)

    @classmethod
    def black(cls) -> OutputContent:
        """Display pure black (blackout)."""
        return cls(OutputContentKind.BLACK)

    @classmethod
    def freeze(cls) -> OutputContent:
        """Hold the last displayed frame."""
        return cls(OutputContentKind.FREEZE)
