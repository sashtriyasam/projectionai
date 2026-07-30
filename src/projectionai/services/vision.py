"""Vision pipeline abstraction.

The vision pipeline processes camera input to estimate geometry,
detect surfaces, and compute projection parameters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.geometry import Mesh, PointCloud, Pose
from projectionai.domain.surface import ProjectionSurface

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CameraFrame:
    """A single frame from a camera source."""

    image: NDArray[np.uint8] = field(compare=False)  # (H, W, 3) BGR image
    timestamp: float  # Monotonic timestamp
    camera_id: str = "default"


@dataclass(frozen=True)
class ScanResult:
    """Result of scanning an object / scene."""

    point_cloud: PointCloud | None = None
    mesh: Mesh | None = None
    surfaces: tuple[ProjectionSurface, ...] = ()
    pose: Pose | None = None
    confidence: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureMatch:
    """A matched feature between two views."""

    source_point: tuple[float, float]
    target_point: tuple[float, float]
    confidence: float = 1.0


@dataclass(frozen=True)
class CalibrationData:
    """Camera intrinsic parameters and distortion coefficients."""

    camera_matrix: NDArray[np.float64] = field(compare=False)  # 3x3
    distortion_coeffs: NDArray[np.float64] = field(
        compare=False
    )  # (k1, k2, p1, p2, k3, …)
    width: int
    height: int
    focal_length: float
    confidence: float = 1.0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CalibrationData):
            return NotImplemented
        return (
            self.width == other.width
            and self.height == other.height
            and self.focal_length == other.focal_length
            and self.confidence == other.confidence
            and bool(np.array_equal(self.camera_matrix, other.camera_matrix))
            and bool(np.array_equal(self.distortion_coeffs, other.distortion_coeffs))
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Vision pipeline — abstract interface
# ---------------------------------------------------------------------------


class VisionPipeline(ABC):
    """Abstract vision pipeline.

    Implementations process camera frames to produce scan results,
    surface detections, and calibration data.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Set up the pipeline (load models, allocate resources)."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release resources."""

    @abstractmethod
    async def process_frame(self, frame: CameraFrame) -> ScanResult:
        """Process a single camera frame and return the scan result.

        This is the primary entry point for real-time scanning.
        """

    @abstractmethod
    async def detect_surfaces(
        self, frame: CameraFrame
    ) -> tuple[ProjectionSurface, ...]:
        """Detect planar surfaces suitable for projection."""

    @abstractmethod
    async def estimate_pose(
        self, frame: CameraFrame, reference_mesh: Mesh
    ) -> Pose | None:
        """Estimate the camera pose relative to a known reference mesh."""

    @abstractmethod
    async def compute_calibration(
        self,
        frames: tuple[CameraFrame, ...],
        pattern_size: tuple[int, int],
    ) -> CalibrationData:
        """Compute camera intrinsics from a set of calibration pattern images."""


# ---------------------------------------------------------------------------
# Factory type
# ---------------------------------------------------------------------------


class VisionPipelineFactory:
    """Creates vision pipeline instances by type name."""

    _registry: ClassVar[dict[str, type[VisionPipeline]]] = {}

    @classmethod
    def register(cls, name: str, pipeline_cls: type[VisionPipeline]) -> None:
        cls._registry[name] = pipeline_cls

    @classmethod
    def create(cls, name: str, **kwargs: object) -> VisionPipeline:
        if name not in cls._registry:
            msg = f"Unknown vision pipeline: {name!r}. Available: {list(cls._registry)}"
            raise ValueError(msg)
        return cls._registry[name](**kwargs)
