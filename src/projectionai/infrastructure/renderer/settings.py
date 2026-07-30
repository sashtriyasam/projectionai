"""Renderer settings — configuration dataclass for the rendering engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class RendererSettings:
    """Global rendering configuration.

    Controls visual quality, performance, and debug overlays.
    Intended to be toggled at runtime via the UI settings panel.
    """

    # --- Window / Viewport ---
    width: int = 1280
    height: int = 720
    vsync: bool = True
    max_fps: int = 0  # 0 = unlimited

    # --- Quality ---
    msaa_samples: int = 4
    anisotropic_filter: float = 16.0
    resolution_scale: float = 1.0  # 0.5 = half-res rendering

    # --- Rendering mode ---
    render_mode: Literal["solid", "wireframe", "textured"] = "solid"
    wireframe_overlay: bool = False
    show_bounding_boxes: bool = False

    # --- Grid ---
    show_grid: bool = True
    grid_size: int = 20
    grid_subdivisions: int = 10
    grid_color: tuple[float, float, float] = (0.3, 0.3, 0.3)
    grid_axis_color: tuple[float, float, float] = (0.5, 0.5, 0.5)

    # --- Axis gizmo ---
    show_axis_gizmo: bool = True
    gizmo_size: int = 60  # pixels

    # --- Selection ---
    selection_color: tuple[float, float, float, float] = (0.0, 0.6, 1.0, 0.3)
    selection_outline_color: tuple[float, float, float] = (0.0, 0.6, 1.0)

    # --- Background ---
    background_color: tuple[float, float, float] = (0.12, 0.12, 0.15)
    background_gradient: bool = True
    background_top: tuple[float, float, float] = (0.08, 0.08, 0.12)
    background_bottom: tuple[float, float, float] = (0.18, 0.18, 0.22)

    # --- Statistics ---
    show_statistics: bool = False
    show_fps: bool = True

    # --- Near / Far planes (defaults) ---
    near_plane: float = 0.01
    far_plane: float = 1000.0

    # --- Misc ---
    clear_color_on_draw: bool = True
    depth_test_enabled: bool = True
    cull_face_enabled: bool = True

    # --- Debug ---
    debug_pass_enabled: bool = False

    def __post_init__(self) -> None:
        """Validate settings after construction."""
        if self.resolution_scale <= 0:
            self.resolution_scale = 1.0
        if self.msaa_samples not in (0, 1, 2, 4, 8, 16):
            self.msaa_samples = 4
        if self.max_fps < 0:
            self.max_fps = 0

    @property
    def effective_width(self) -> int:
        """Width after resolution scaling."""
        return max(1, int(self.width * self.resolution_scale))

    @property
    def effective_height(self) -> int:
        """Height after resolution scaling."""
        return max(1, int(self.height * self.resolution_scale))
