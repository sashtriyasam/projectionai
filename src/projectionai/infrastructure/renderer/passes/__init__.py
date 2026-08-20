"""Render passes — each pass is a single pipeline stage.

Available passes:
- BackgroundPass  — gradient or solid-colour background
- GridPass        — reference grid on the ground plane
- ScenePass       — main scene geometry
- OverlayPass     — 2D overlays (text, HUD, statistics)
- SelectionPass   — selection highlight rendering
- DebugPass       — bounding boxes, normals, debug info
- PatternPass     — fullscreen texture (test patterns / solids / blackout)
"""

from __future__ import annotations

from projectionai.infrastructure.renderer.passes.background import BackgroundPass
from projectionai.infrastructure.renderer.passes.debug import DebugPass
from projectionai.infrastructure.renderer.passes.grid import GridPass
from projectionai.infrastructure.renderer.passes.overlay import OverlayPass
from projectionai.infrastructure.renderer.passes.pattern import PatternPass
from projectionai.infrastructure.renderer.passes.scene import ScenePass
from projectionai.infrastructure.renderer.passes.selection import SelectionPass

__all__ = [
    "BackgroundPass",
    "DebugPass",
    "GridPass",
    "OverlayPass",
    "PatternPass",
    "ScenePass",
    "SelectionPass",
]
