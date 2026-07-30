"""Material and texture models.

Represents the visual properties of a surface and the content
projected onto it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class ContentType(Enum):
    """Type of projection content."""

    IMAGE = auto()
    VIDEO = auto()
    ANIMATION = auto()
    TEXT = auto()
    GENERATIVE = auto()  # Real-time generated content


@dataclass(frozen=True)
class ProjectedContent:
    """Content mapped to a surface for projection."""

    id: str
    name: str
    content_type: ContentType = ContentType.IMAGE

    # Source paths
    source_path: str | None = None  # Original source file
    processed_path: str | None = None  # Warped / processed file

    # Media properties
    width: int = 1920
    height: int = 1080
    duration_seconds: float | None = None  # None for still images
    loop: bool = True

    # Mapping
    target_surface_id: str = ""
    blend_mode: str = "normal"
    opacity: float = 1.0

    # AI generation parameters (if AI-generated)
    prompt: str = ""
    provider: str = ""
    generation_params: dict[str, object] = field(default_factory=dict)

    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Material:
    """Surface material properties affecting projection appearance."""

    surface_albedo: tuple[float, float, float] = (0.5, 0.5, 0.5)
    surface_roughness: float = 0.5
    surface_color_correction: tuple[float, float, float] = (1.0, 1.0, 1.0)
