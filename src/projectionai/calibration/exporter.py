"""Calibration exporter — serialises calibration data to various formats.

The exporter converts calibration results into exchange formats for
integration with external tools, rendering pipelines, and storage.

Supported formats:
- ``raw``: Full Python dataclass serialisation (JSON-compatible dict).
- ``projection_mapping``: Warp mesh + projector parameters for the
  rendering pipeline.
- ``open_cv``: Camera matrix + distortion coefficients for OpenCV.
- ``custom``: User-defined format via plugin.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any

from projectionai.calibration.types import CalibrationResult

_logger = logging.getLogger(__name__)


class ExportError(RuntimeError):
    """Raised when export fails."""


class CalibrationExporter(ABC):
    """Base class for calibration exporters.

    Subclass to implement a new export format.
    """

    @abstractmethod
    def export(self, result: CalibrationResult, path: str | Path | None = None) -> Any:
        """Export calibration data.

        Args:
            result: The calibration result to export.
            path: Optional file path to write to.

        Returns:
            The exported data (dict for formats, or path for file-based).
        """
        ...


# ---------------------------------------------------------------------------
# Raw JSON exporter
# ---------------------------------------------------------------------------


class RawJsonExporter(CalibrationExporter):
    """Export calibration data as a raw JSON-compatible dict or file."""

    def __init__(self, indent: int = 2) -> None:
        self.indent = indent

    def export(
        self, result: CalibrationResult, path: str | Path | None = None
    ) -> dict[str, Any] | Path:
        """Export as a JSON-compatible dictionary.

        Args:
            result: The calibration result.
            path: Optional file path. Writes to file if provided.

        Returns:
            The serialised dict, or the ``Path`` if written to file.
        """
        try:
            data = self._to_dict(result)
        except Exception as exc:
            raise ExportError(f"Failed to serialise calibration data: {exc}") from exc

        if path is not None:
            path_obj = Path(path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(
                json.dumps(data, indent=self.indent, default=str),
                encoding="utf-8",
            )
            _logger.info("Exported calibration to %s", path_obj)
            return path_obj

        return data

    @staticmethod
    def _to_dict(result: Any) -> dict[str, Any]:
        if hasattr(result, "projector_intrinsics") and hasattr(
            result, "calibration_id"
        ):
            return result.to_dict()  # type: ignore[no-any-return]
        base: dict[str, Any] = {
            "success": result.success,
            "quality_score": result.quality_score,
            "error_message": result.error_message,
            "validation_errors": list(result.validation_errors),
            "validation_warnings": list(result.validation_warnings),
        }
        if result.data is not None:
            raw = asdict(result.data)
            raw["method"] = result.data.method.value
            base["data"] = raw
        return base


# ---------------------------------------------------------------------------
# Projection mapping exporter
# ---------------------------------------------------------------------------


class ProjectionMappingExporter(CalibrationExporter):
    """Export calibration as projection mapping parameters.

    Produces the warp mesh, projector transform, and surface parameters
    needed by the rendering pipeline to apply the calibration.
    """

    def export(
        self, result: CalibrationResult, path: str | Path | None = None
    ) -> dict[str, Any]:
        """Export as projection mapping configuration.

        Returns:
            Dict with keys: ``"projector_pose"``, ``"warp_mesh"``,
            ``"surface_pose"``, ``"confidence"``.
        """
        if result.data is None:
            msg = "No calibration data to export"
            raise ExportError(msg)

        data = result.data

        mapping: dict[str, Any] = {
            "projector_pose": data.projector_pose,
            "camera_pose": data.camera_pose,
            "surface_pose": data.surface_pose,
            "warp_mesh": data.warp_mesh,
            "control_points": {
                k: [{"x": p.x, "y": p.y} for p in pts]
                for k, pts in data.control_points.items()
            },
            "confidence": data.confidence,
            "reprojection_error": data.reprojection_error,
            "method": data.method.value,
        }

        if path is not None:
            path_obj = Path(path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(
                json.dumps(mapping, indent=2, default=str),
                encoding="utf-8",
            )
            _logger.info("Exported projection mapping to %s", path_obj)

        return mapping


# ---------------------------------------------------------------------------
# OpenCV exporter
# ---------------------------------------------------------------------------


class OpenCvExporter(CalibrationExporter):
    """Export camera intrinsics in OpenCV-compatible format.

    Produces the camera matrix and distortion coefficients for use with
    ``cv2.calibrateCamera``, ``cv2.undistort``, etc.
    """

    def export(
        self, result: CalibrationResult, path: str | Path | None = None
    ) -> dict[str, Any]:
        """Export as OpenCV-format camera parameters.

        Returns:
            Dict with keys: ``"camera_matrix"``, ``"distortion_coeffs"``,
            ``"image_width"``, ``"image_height"``.
        """
        if result.data is None:
            msg = "No calibration data to export"
            raise ExportError(msg)

        # Extract camera data from the result
        camera_data = result.data.camera_pose
        if not camera_data:
            # Return empty skeleton
            opencv: dict[str, Any] = {
                "camera_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                "distortion_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
                "image_width": 1920,
                "image_height": 1080,
            }
        else:
            # Use the first available camera pose
            pose_id = next(iter(camera_data))
            pose_dict = camera_data[pose_id]
            opencv = {
                "camera_matrix": pose_dict.get("camera_matrix", []),
                "distortion_coeffs": pose_dict.get("distortion_coeffs", []),
                "image_width": pose_dict.get("width", 1920),
                "image_height": pose_dict.get("height", 1080),
            }

        if path is not None:
            path_obj = Path(path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(
                json.dumps(opencv, indent=2, default=str),
                encoding="utf-8",
            )

        return opencv


# ---------------------------------------------------------------------------
# Exporter registry
# ---------------------------------------------------------------------------


class ExporterRegistry:
    """Registry of named exporters.

    Allows users to register custom exporters and select one by name.
    """

    def __init__(self) -> None:
        self._exporters: dict[str, CalibrationExporter] = {
            "raw": RawJsonExporter(),
            "projection_mapping": ProjectionMappingExporter(),
            "open_cv": OpenCvExporter(),
        }

    def register(self, name: str, exporter: CalibrationExporter) -> None:
        """Register a custom exporter."""
        self._exporters[name] = exporter

    def get(self, name: str) -> CalibrationExporter | None:
        """Get an exporter by name."""
        return self._exporters.get(name)

    def export(
        self,
        name: str,
        result: CalibrationResult,
        path: str | Path | None = None,
    ) -> Any:
        """Export using a named exporter.

        Raises:
            ExportError: If the exporter is not found.
        """
        exporter = self.get(name)
        if exporter is None:
            msg = f"Unknown export format: {name!r}"
            raise ExportError(msg)
        return exporter.export(result, path=path)

    @property
    def names(self) -> list[str]:
        """Return sorted list of registered exporter names."""
        return sorted(self._exporters)
