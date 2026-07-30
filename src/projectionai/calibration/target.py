"""Calibration target — patterns projected or displayed for calibration.

A calibration target is a known pattern (checkerboard, ArUco grid, etc.)
that the camera observes to establish point correspondences between the
projector, surface, and camera.

Different calibration methods use different target types but they share
the same data interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from projectionai.calibration.types import CalibrationMethod, Vec2


@dataclass
class CalibrationTarget:
    """Description of a calibration target pattern.

    The target defines the known geometry of a calibration pattern:
    - ``checkerboard``: inner corners at known intersections
    - ``aruco``: dictionary-based markers with known IDs and positions
    - ``circles``: asymmetric or symmetric circle grid
    - ``structured_light``: projected phase-shifted patterns

    Attributes:
        method: Which calibration method this target is for.
        pattern_type: Human-readable pattern name.
        rows: Number of internal corner rows (checkerboard/circles).
        cols: Number of internal corner columns (checkerboard/circles).
        square_size_mm: Physical size of each square/dot in millimetres.
        marker_size_mm: Physical size of ArUco/QR markers in millimetres.
        marker_dict: ArUco dictionary name (e.g. ``"DICT_6X6_250"``).
        marker_ids: Specific marker IDs to use.
        world_points: Known 2D target-local points (Z implicitly zero).
        image_points: Observed 2D points (populated during calibration).
        metadata: Method-specific configuration.
    """

    method: CalibrationMethod = CalibrationMethod.MANUAL
    pattern_type: str = "checkerboard"

    # Grid dimensions
    rows: int = 9
    cols: int = 6

    # Physical dimensions
    square_size_mm: float = 30.0
    marker_size_mm: float = 0.0

    # ArUco / marker specific
    marker_dict: str = ""
    marker_ids: list[int] = field(default_factory=list)

    # Computed point sets
    world_points: list[Vec2] = field(default_factory=list)
    image_points: list[Vec2] = field(default_factory=list)

    # Optional: screen-space target for projector-only calibration
    screen_points: list[Vec2] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_world_points(self) -> list[Vec2]:
        """Generate known world points based on pattern type.

        For checkerboard: returns grid of inner corner positions
        in target-local coordinates (Z=0 plane).
        """
        points: list[Vec2] = []
        if self.pattern_type == "checkerboard":
            s = self.square_size_mm
            for row in range(self.rows):
                for col in range(self.cols):
                    points.append(Vec2(x=col * s, y=row * s))
        elif self.pattern_type == "circles":
            s = self.square_size_mm
            for row in range(self.rows):
                for col in range(self.cols):
                    offset_x = (col * s) + (0.0 if row % 2 == 0 else s * 0.5)
                    points.append(Vec2(x=offset_x, y=row * s))
        return points

    @property
    def point_count(self) -> int:
        """Number of feature points in the target."""
        return len(self.world_points)

    @property
    def physical_width(self) -> float:
        """Physical width of the target in mm."""
        return self.cols * self.square_size_mm

    @property
    def physical_height(self) -> float:
        """Physical height of the target in mm."""
        return self.rows * self.square_size_mm
