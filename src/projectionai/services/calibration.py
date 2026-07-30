"""Calibration abstraction.

Calibration aligns the virtual 3D model with the physical object so
that projected content lands on the correct surfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from projectionai.domain.calibration import CalibrationPoint, CalibrationResult
from projectionai.domain.geometry import Mesh

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationGuide:
    """Visual guide rendered during manual calibration."""

    points: tuple[CalibrationPoint, ...]
    instructions: str = ""
    step: int = 0
    total_steps: int = 0


# ---------------------------------------------------------------------------
# Calibrator — abstract interface
# ---------------------------------------------------------------------------


class Calibrator(ABC):
    """Abstract calibrator.

    Subclasses implement specific calibration strategies:
    - Manual: user clicks corresponding points.
    - Automatic: structured light / ICP-based registration.
    - Hybrid: automatic first, manual refinement.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Set up calibration resources."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release resources."""

    @abstractmethod
    async def start_calibration(
        self,
        reference_mesh: Mesh | None = None,
    ) -> CalibrationGuide:
        """Begin the calibration process.

        Returns a *CalibrationGuide* with initial instructions
        and guide points for the user.
        """

    @abstractmethod
    async def add_correspondence(
        self,
        image_point: tuple[float, float],
        model_point: tuple[float, float, float],
        confidence: float = 1.0,
    ) -> CalibrationGuide:
        """Add a 2D-3D correspondence point for manual calibration.

        Returns an updated guide (next point to click, or completion).
        """

    @abstractmethod
    async def compute_calibration(self) -> CalibrationResult:
        """Compute the final calibration from collected correspondences."""

    @abstractmethod
    async def auto_calibrate(
        self,
        source_mesh: Mesh,
        target_mesh: Mesh,
        max_iterations: int = 100,
    ) -> CalibrationResult:
        """Run automatic (ICP / feature-based) calibration.

        Returns the computed transform.
        """

    @abstractmethod
    async def refine_calibration(
        self,
        current: CalibrationResult,
        observations: tuple[CalibrationPoint, ...],
    ) -> CalibrationResult:
        """Refine an existing calibration with new observations."""
