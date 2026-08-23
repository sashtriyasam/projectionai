"""Output content — Qt-free description of what an output window displays.

The hardware subsystem describes output *state* (live, blackout, freeze...)
while the renderer shows *content*. This module defines the immutable,
Qt-free content model consumed by :class:`GLOutputWindow`; the UI layer
maps session state onto content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from projectionai.hardware.patterns import PatternKind


class OutputContentKind(StrEnum):
    """What the output window should display."""

    PATTERN = "pattern"  # a named test pattern or solid colour
    BLACK = "black"  # pure black (blackout)
    FREEZE = "freeze"  # hold the last shown frame
    PROJECTION = "projection"  # warped content via ProjectionPass


@dataclass(frozen=True)
class OutputContent:
    """Immutable content descriptor for the projector output window.

    ``pattern_kind`` is only meaningful when ``kind`` is ``PATTERN``;
    ``warp_mesh`` and ``source_texture`` are only meaningful when ``kind`` is ``PROJECTION``.
    The invariant is enforced at construction time.
    """

    kind: OutputContentKind
    pattern_kind: PatternKind | None = None
    warp_mesh: Any = None  # WarpMesh from domain.warp_mesh
    source_texture: Any = None  # Texture from renderer.texture

    def __post_init__(self) -> None:
        if self.kind is OutputContentKind.PATTERN and self.pattern_kind is None:
            raise ValueError("OutputContent.pattern(...) requires a pattern")
        if self.kind is not OutputContentKind.PATTERN and self.pattern_kind is not None:
            raise ValueError("Only PATTERN content may carry a pattern")
        if self.kind is OutputContentKind.PROJECTION and self.warp_mesh is None:
            raise ValueError("OutputContent.projection(...) requires a warp_mesh")
        if self.kind is not OutputContentKind.PROJECTION and self.warp_mesh is not None:
            raise ValueError("Only PROJECTION content may carry a warp_mesh")

    @classmethod
    def pattern(cls, pattern: PatternKind) -> OutputContent:
        """Display the named test pattern / solid colour."""
        return cls(OutputContentKind.PATTERN, pattern_kind=pattern)

    @classmethod
    def black(cls) -> OutputContent:
        """Display pure black (blackout)."""
        return cls(OutputContentKind.BLACK)

    @classmethod
    def freeze(cls) -> OutputContent:
        """Hold the last displayed frame."""
        return cls(OutputContentKind.FREEZE)

    @classmethod
    def projection(cls, warp_mesh: Any, source_texture: Any) -> OutputContent:
        """Display warped content via ProjectionPass.

        Args:
            warp_mesh: WarpMesh instance (vertices, content_uvs, indices, version)
            source_texture: Texture instance to warp
        """
        return cls(
            OutputContentKind.PROJECTION,
            warp_mesh=warp_mesh,
            source_texture=source_texture,
        )
