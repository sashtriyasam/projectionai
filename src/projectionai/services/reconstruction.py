"""Reconstruction backends — ray-plane triangulation and projection.

Two implementations share one contract:

- ``ReferenceReconstructionBackend``: NumPy/OpenCV (the correctness oracle).
- ``NativeReconstructionBackend``: C++ kernels behind pybind11
  (``projectionai._reconstruction_native``), zero-copy for contiguous
  float64 inputs.

The reference stays in production until benchmarks prove the native
candidate is better on the measured hardware (Phase 6.6.4).
"""

from __future__ import annotations

import importlib.util
import logging
from abc import ABC, abstractmethod
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from projectionai.domain.calibration_session import (
    CorrespondenceSet,
    ReconstructionResult,
)
from projectionai.infrastructure.projector_calibration.estimators import (
    sample_correspondences,
    undistort_points,
)
from projectionai.infrastructure.projector_calibration.estimators import (
    triangulate_plane as _ref_triangulate,
)
from projectionai.services.projector_calibration import (
    CalibratedCamera,
    CorrespondenceMap,
    ProjectorCalibrationError,
    SurfacePlane,
)

_logger = logging.getLogger(__name__)


class ReconstructionError(ProjectorCalibrationError):
    """Raised when reconstruction cannot be computed."""


class BackendMode(StrEnum):
    AUTO = "auto"
    REFERENCE = "reference"
    NATIVE = "native"


class ReconstructionBackend(ABC):
    """Contract shared by reference and native reconstruction backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""

    @abstractmethod
    def triangulate(
        self, normalized: NDArray[np.float64], surface: SurfacePlane
    ) -> NDArray[np.float64]:
        """Intersect normalized camera rays (N,2) with *surface* -> (N,3)."""

    @abstractmethod
    def project(
        self,
        points_camera: NDArray[np.float64],
        intrinsics: NDArray[np.float64],
        pose: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Project camera-frame 3D points into projector pixels -> (N,2)."""

    def reconstruct(
        self,
        correspondences: CorrespondenceSet,
        camera: CalibratedCamera,
        surface: SurfacePlane,
        max_points: int = 20_000,
    ) -> ReconstructionResult:
        """Reconstruct 3D points from a canonical correspondence set.

        Shared flow: strided sampling -> undistortion -> triangulation
        (backend-specific) -> finite filtering -> ReconstructionResult.
        """
        if correspondences.num_correspondences == 0:
            raise ReconstructionError("No valid correspondences to reconstruct")
        cmap = CorrespondenceMap(
            projector_x=correspondences.projector_x,
            projector_y=correspondences.projector_y,
            mask=correspondences.mask,
            image_size=correspondences.image_size,
        )
        camera_pixels, projector_pixels = sample_correspondences(cmap, max_points)
        if len(camera_pixels) < 4:
            raise ReconstructionError(
                f"Only {len(camera_pixels)} correspondences after sampling"
            )
        normalized = undistort_points(camera_pixels, camera)
        points = self.triangulate(normalized, surface)

        finite = np.all(np.isfinite(points), axis=1)
        if np.count_nonzero(finite) < 4:
            raise ReconstructionError(
                "Too few correspondences triangulate to finite 3D points"
            )
        points = points[finite]
        projector_pixels = projector_pixels[finite]

        normals = np.tile(surface.normal, (len(points), 1)).astype(np.float64)
        return ReconstructionResult(
            points_camera=points,
            projector_pixels=projector_pixels,
            sequence_id=correspondences.sequence_id,
            normals=normals,
            method="plane_triangulation",
        )


class ReferenceReconstructionBackend(ReconstructionBackend):
    """NumPy/OpenCV reference — the correctness oracle."""

    @property
    def name(self) -> str:
        return "reference"

    def triangulate(
        self, normalized: NDArray[np.float64], surface: SurfacePlane
    ) -> NDArray[np.float64]:
        return _ref_triangulate(normalized, surface)

    def project(
        self,
        points_camera: NDArray[np.float64],
        intrinsics: NDArray[np.float64],
        pose: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        from projectionai.infrastructure.projector_calibration.estimators import (
            project_points,
        )

        return project_points(points_camera, intrinsics, pose)


class NativeReconstructionBackend(ReconstructionBackend):
    """C++ kernels via ``projectionai._reconstruction_native``.

    Inputs must be C-contiguous float64 — the binding raises instead of
    silently copying (zero-copy contract, no hidden conversions).
    """

    def __init__(self) -> None:
        try:
            import projectionai._reconstruction_native as native  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ReconstructionError(
                "Native reconstruction extension is not built. "
                "Run 'pip install -e .' or use the reference backend."
            ) from exc
        self._native = native

    @property
    def name(self) -> str:
        return "native"

    def _require_contiguous(
        self, arr: NDArray[np.float64], label: str
    ) -> NDArray[np.float64]:
        if not arr.flags.c_contiguous:
            raise ReconstructionError(
                f"{label} must be C-contiguous (zero-copy contract)"
            )
        if arr.dtype != np.float64:
            raise ReconstructionError(f"{label} must be float64, got {arr.dtype}")
        return arr

    def triangulate(
        self, normalized: NDArray[np.float64], surface: SurfacePlane
    ) -> NDArray[np.float64]:
        norm = self._require_contiguous(normalized, "normalized")
        n = self._require_contiguous(
            np.ascontiguousarray(surface.normal), "surface.normal"
        )
        return np.asarray(
            self._native.triangulate_plane(norm, n, float(surface.offset))
        )

    def project(
        self,
        points_camera: NDArray[np.float64],
        intrinsics: NDArray[np.float64],
        pose: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        pts = self._require_contiguous(points_camera, "points_camera")
        k = self._require_contiguous(intrinsics, "intrinsics")
        t = self._require_contiguous(pose, "pose")
        return np.asarray(self._native.project_points(pts, k, t))


class ReconstructionBackendFactory:
    """Backend selection.

    Evidence (Phase 6.6.4 benchmark, 100 iters, offset_cam synthetic case):
    native kernels are ~16x faster per-op (triangulate 0.26->0.02ms,
    projection 0.72->0.04ms at N=20k), but the full reconstruct() is dominated
    by shared OpenCV steps (sampling ~1ms, undistort ~1ms). Total savings are
    <1ms at N<=20k, immaterial versus decode (~370ms) and capture (~200ms) in
    the calibration pipeline. Native at N=20k total is within measurement
    noise (3.11ms vs 2.94ms reference).

    Per the BEST-ONLY standard, a backend becomes the default only when it
    clearly wins end-to-end. It does not here, so REFERENCE is the production
    default. NATIVE is available for explicit opt-in.
    """

    @staticmethod
    def create(mode: BackendMode = BackendMode.REFERENCE) -> ReconstructionBackend:
        if mode == BackendMode.NATIVE:
            return NativeReconstructionBackend()
        if mode == BackendMode.AUTO:
            # AUTO prefers native when built, but REFERENCE is the documented
            # production default given the measured evidence above.
            try:
                return NativeReconstructionBackend()
            except ReconstructionError:
                return ReferenceReconstructionBackend()
        return ReferenceReconstructionBackend()

    @staticmethod
    def is_native_available() -> bool:
        return (
            importlib.util.find_spec("projectionai._reconstruction_native") is not None
        )
