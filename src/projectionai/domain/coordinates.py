"""Coordinate space definitions and transformations for projection mapping.

This module defines the canonical coordinate spaces used throughout the
projection mapping pipeline and the transformation relationships between them.

Coordinate Spaces
=================

1. SURFACE_LOCAL
   - Origin: Surface local origin (typically bottom-left or center)
   - Axes: X right, Y up, Z out (right-handed)
   - Units: Meters
   - UV: [0,1] x [0,1] normalized across surface
   - Used for: Surface geometry definition, UV mapping

2. WORLD
   - Origin: Arbitrary world origin (typically room/floor center)
   - Axes: X right, Y up, Z forward (right-handed)
   - Units: Meters
   - Used for: Scene layout, multi-surface positioning, camera/projector poses

3. CAMERA
   - Origin: Camera optical center
   - Axes: X right, Y down, Z forward (right-handed, OpenCV convention)
   - Units: Meters
   - Used for: Camera calibration, 3D triangulation, ray casting

4. PROJECTOR
   - Origin: Projector optical center
   - Axes: X right, Y down, Z forward (right-handed, matches camera)
   - Units: Meters
   - Used for: Projector calibration, frustum definition, warp computation

5. PROJECTOR_UV
   - Origin: Projector image top-left
   - Axes: U right, V down
   - Units: Normalized [0,1] x [0,1]
   - Used for: Warp mesh UVs, texture sampling in projector space

6. PROJECTOR_PIXEL
   - Origin: Projector image top-left
   - Axes: X right, Y down
   - Units: Pixels (integer coordinates)
   - Used for: Projector output raster, blend masks, crop regions

6. SCREEN (deprecated alias for PROJECTOR_PIXEL)
   - Kept for backward compatibility only

Transform Relationships
=======================

surface_local → world:     SurfacePose.transform (Mat4x4)
world → camera:            CameraExtrinsics.transform.inverse()
world → projector:         ProjectorExtrinsics.transform.inverse()
camera → projector_pixel:  ProjectorCalibrationResult.project_points()
projector_uv → projector_pixel:  (u * width, v * height)
surface_uv → projector_uv: Warp mesh UV coordinates

UV Convention
=============

- Surface UV: [0,1] x [0,1], origin bottom-left, V up (OpenGL texture convention)
- Projector UV: [0,1] x [0,1], origin top-left, V down (image convention)
- The warp mesh stores PROJECTOR_UV coordinates per vertex
- When sampling projector textures: flip V (1 - v) if texture is OpenGL-style
- Projector UV → Pixel uses **corner convention**: UV (0,0)→(0,0), UV (1,1)→(width, height).
  This matches ProjectorIntrinsics.pixel_to_uv/uv_to_pixel in transforms.py.

This convention matches the existing row-flipping in GLOutputWindow._ensure_texture().
"""

from __future__ import annotations

from enum import StrEnum


class CoordinateSpace(StrEnum):
    """Canonical coordinate spaces in the projection mapping pipeline."""

    SURFACE_LOCAL = "surface_local"
    WORLD = "world"
    CAMERA = "camera"
    PROJECTOR = "projector"
    PROJECTOR_UV = "projector_uv"
    PROJECTOR_PIXEL = "projector_pixel"
    SCREEN = "projector_pixel"


class UVConvention(StrEnum):
    """UV coordinate conventions."""

    OPENGL = "opengl"  # Origin bottom-left, V up
    IMAGE = "image"  # Origin top-left, V down
    PROJECTOR = "projector"  # Alias for IMAGE


# Transformation direction constants
# Format: "from_space → to_space"

SURFACE_LOCAL_TO_WORLD = "surface_local → world"
WORLD_TO_CAMERA = "world → camera"
WORLD_TO_PROJECTOR = "world → projector"
CAMERA_TO_PROJECTOR_PIXEL = "camera → projector_pixel"
PROJECTOR_UV_TO_PROJECTOR_PIXEL = "projector_uv → projector_pixel"
SURFACE_UV_TO_PROJECTOR_UV = "surface_uv → projector_uv"


def surface_uv_to_projector_uv(surface_uv: tuple[float, float]) -> tuple[float, float]:
    """Convert surface UV (OpenGL convention) to projector UV (image convention).

    Surface UV: (u, v) where v=0 is bottom, v=1 is top
    Projector UV: (u, v) where v=0 is top, v=1 is bottom

    Args:
        surface_uv: (u, v) in [0,1] x [0,1], OpenGL convention

    Returns:
        (u, 1-v) in [0,1] x [0,1], image/projector convention
    """
    u, v = surface_uv
    return (u, 1.0 - v)


def projector_uv_to_surface_uv(
    projector_uv: tuple[float, float],
) -> tuple[float, float]:
    """Convert projector UV (image convention) to surface UV (OpenGL convention).

    Inverse of surface_uv_to_projector_uv.

    Args:
        projector_uv: (u, v) in [0,1] x [0,1], image convention

    Returns:
        (u, 1-v) in [0,1] x [0,1], OpenGL convention
    """
    return surface_uv_to_projector_uv(projector_uv)  # Self-inverse


def projector_uv_to_pixel(
    uv: tuple[float, float], width: int, height: int
) -> tuple[int, int]:
    """Convert normalized projector UV to pixel coordinates (corner convention).

    Args:
        uv: (u, v) in [0,1] x [0,1]
        width: Projector output width in pixels
        height: Projector output height in pixels

    Returns:
        (x, y) pixel coordinates, origin top-left. Uses corner convention:
        UV (0,0) -> (0,0), UV (1,1) -> (width, height).
    """
    u, v = uv
    if width <= 0 or height <= 0:
        raise ValueError(
            f"width and height must be positive, got width={width}, height={height}"
        )
    x = round(u * width)
    y = round(v * height)
    return (x, y)


def projector_pixel_to_uv(
    pixel: tuple[int, int], width: int, height: int
) -> tuple[float, float]:
    """Convert pixel coordinates to normalized projector UV.

    Args:
        pixel: (x, y) pixel coordinates
        width: Projector output width in pixels
        height: Projector output height in pixels

    Returns:
        (u, v) in [0,1] x [0,1]

    Raises:
        ValueError: If width or height is zero.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"width and height must be > 0, got {width}x{height}")
    x, y = pixel
    return (x / width, y / height)
