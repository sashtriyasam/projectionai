"""Calibration importer — loads calibration data from external sources.

The importer reads calibration data from files, clipboard, or external
tools and reconstructs ``CalibrationResult`` objects.

Supports:
- Loading raw JSON exports.
- Importing OpenCV camera calibration results.
- Loading legacy/project-specific calibration formats.
- Future: importing from external calibration tools.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from projectionai.calibration.types import (
    CalibrationData,
    CalibrationMethod,
    CalibrationResult,
)

_logger = logging.getLogger(__name__)


class ImportFailedError(RuntimeError):
    """Raised when import fails."""


class CalibrationImporter(ABC):
    """Base class for calibration importers."""

    @abstractmethod
    def import_data(self, source: Any) -> CalibrationResult:
        """Import calibration data from a source.

        Args:
            source: Path, dict, or other source of calibration data.

        Returns:
            A reconstructed ``CalibrationResult``.
        """
        ...


# ---------------------------------------------------------------------------
# Raw JSON importer
# ---------------------------------------------------------------------------


class RawJsonImporter(CalibrationImporter):
    """Import calibration data from a raw JSON file or dict."""

    def import_data(self, source: str | Path | dict[str, Any]) -> CalibrationResult:
        """Import from a JSON file path, string, or dict.

        Args:
            source: ``Path`` or ``str`` file path, JSON string, or dict.

        Returns:
            The reconstructed ``CalibrationResult``.
        """
        if isinstance(source, dict):
            data = source
        else:
            raw = Path(source).read_text(encoding="utf-8")
            data = json.loads(raw)

        try:
            return self._from_dict(data)
        except Exception as exc:
            raise ImportFailedError(f"Failed to parse calibration data: {exc}") from exc

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> CalibrationResult:
        if "projector_intrinsics" in data and "calibration_id" in data:
            from projectionai.calibration.types import canonical_to_legacy_result
            from projectionai.domain.calibration_session import (
                CalibrationResult as Canonical,
            )

            canonical = Canonical.from_dict(data)
            return canonical_to_legacy_result(canonical)
        cal_data = None
        raw_data = data.get("data")
        if raw_data is not None:
            cal_data = CalibrationData(
                projector_pose=raw_data.get("projector_pose", {}),
                camera_pose=raw_data.get("camera_pose", {}),
                surface_pose=raw_data.get("surface_pose", {}),
                warp_mesh=raw_data.get("warp_mesh", {}),
                control_points=raw_data.get("control_points", {}),
                confidence=raw_data.get("confidence", 0.0),
                reprojection_error=raw_data.get("reprojection_error", 0.0),
                residuals=raw_data.get("residuals", []),
                method=CalibrationMethod(raw_data.get("method") or "manual"),
                timestamp=raw_data.get("timestamp", ""),
                duration_ms=raw_data.get("duration_ms", 0.0),
                num_samples=raw_data.get("num_samples", 0),
                custom=raw_data.get("custom", {}),
            )

        return CalibrationResult(
            success=data.get("success", False),
            data=cal_data,
            validation_errors=data.get("validation_errors", []),
            validation_warnings=data.get("validation_warnings", []),
            quality_score=data.get("quality_score", 0.0),
            error_message=data.get("error_message", ""),
        )


# ---------------------------------------------------------------------------
# Importer registry
# ---------------------------------------------------------------------------


class ImporterRegistry:
    """Registry of named importers."""

    def __init__(self) -> None:
        self._importers: dict[str, CalibrationImporter] = {
            "raw": RawJsonImporter(),
        }

    def register(self, name: str, importer: CalibrationImporter) -> None:
        """Register a custom importer."""
        self._importers[name] = importer

    def get(self, name: str) -> CalibrationImporter | None:
        """Get an importer by name."""
        return self._importers.get(name)

    def import_data(self, name: str, source: Any) -> CalibrationResult:
        """Import using a named importer."""
        importer = self.get(name)
        if importer is None:
            msg = f"Unknown import format: {name!r}"
            raise ImportFailedError(msg)
        return importer.import_data(source)

    @property
    def names(self) -> list[str]:
        """Return sorted list of registered importer names."""
        return sorted(self._importers)
