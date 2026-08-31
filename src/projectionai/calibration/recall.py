"""Calibration recall — load persisted calibrations with compatibility checks.

Wraps ``CalibrationPersistence`` and adds hardware compatibility
verification: the loaded calibration must match the currently connected
projector, camera, and surface.

Usage::

    from projectionai.calibration.recall import CalibrationRecall

    recall = CalibrationRecall()
    result = recall.recall(
        directory=Path("my_project.calibration"),
        expected_projector_id="proj_001",
        expected_camera_id="cam_001",
        expected_surface_id="surf_001",
    )
    # result.calibration is a verified CanonicalCalibrationResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from projectionai.calibration.persistence import (
    CalibrationPersistence,
    CalibrationPersistenceBundle,
    CompatibilityError,
)
from projectionai.domain.calibration_session import (
    CalibrationResult as CanonicalCalibrationResult,
)
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.warp_mesh import WarpMesh

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recall result
# ---------------------------------------------------------------------------


@dataclass
class RecallResult:
    """Result of a recall operation with validation details."""

    calibration: CanonicalCalibrationResult
    warp_mesh: WarpMesh | None = None
    projection: ProjectionMapping | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CalibrationRecall
# ---------------------------------------------------------------------------


class CalibrationRecall:
    """Load persisted calibrations with integrity + compatibility checks.

    This is the recommended entry point for loading calibrations.  It
    performs three layers of validation:

    1. **Integrity** — checksums match (done by ``CalibrationPersistence``).
    2. **Compatibility** — projector/camera/surface IDs match expectations.
    3. **Reconstruction** — domain objects reconstruct without error.
    """

    def __init__(self) -> None:
        self._persistence = CalibrationPersistence()

    def recall(
        self,
        directory: Path,
        *,
        expected_projector_id: str | None = None,
        expected_camera_id: str | None = None,
        expected_surface_id: str | None = None,
    ) -> RecallResult:
        """Load and validate a persisted calibration.

        Parameters
        ----------
        directory:
            Path to the ``.calibration/`` directory.
        expected_projector_id:
            If provided, the loaded calibration must match this projector.
        expected_camera_id:
            If provided, the loaded calibration must match this camera.
        expected_surface_id:
            If provided, the loaded calibration must match this surface.

        Returns
        -------
        A ``RecallResult`` with the loaded objects and any warnings.

        Raises
        ------
        FileNotFoundError
            If the directory or manifest is missing.
        SchemaVersionError
            If the stored schema version is unsupported.
        IntegrityError
            If checksums fail or data is corrupted.

        Notes
        -----
        Mismatched hardware IDs are reported through
        :attr:`RecallResult.warnings`, not raised.  Use
        :meth:`recall_strict` if you want a
        :class:`CompatibilityError` on mismatch.
        """
        # Layer 1: Integrity (delegates to CalibrationPersistence.load)
        bundle = self._persistence.load(directory)

        # Layer 2: Compatibility
        warnings = self._check_compatibility(
            bundle,
            expected_projector_id=expected_projector_id,
            expected_camera_id=expected_camera_id,
            expected_surface_id=expected_surface_id,
        )

        _logger.info(
            "Recall complete for %s (id=%s, warnings=%d)",
            directory,
            bundle.calibration.calibration_id,
            len(warnings),
        )

        return RecallResult(
            calibration=bundle.calibration,
            warp_mesh=bundle.warp_mesh,
            projection=bundle.projection,
            manifest=bundle.manifest,
            warnings=warnings,
        )

    def recall_strict(
        self,
        directory: Path,
        *,
        expected_projector_id: str,
        expected_camera_id: str,
        expected_surface_id: str = "",
    ) -> RecallResult:
        """Like ``recall()`` but raises on any compatibility mismatch.

        Raises
        ------
        CompatibilityError
            If any of the expected IDs don't match the stored values.
        """
        result = self.recall(
            directory,
            expected_projector_id=expected_projector_id,
            expected_camera_id=expected_camera_id,
            expected_surface_id=expected_surface_id or None,
        )
        if result.warnings:
            raise CompatibilityError(
                f"Calibration compatibility failures: {'; '.join(result.warnings)}"
            )
        return result

    # -- Internal ------------------------------------------------------------

    def _check_compatibility(
        self,
        bundle: CalibrationPersistenceBundle,
        *,
        expected_projector_id: str | None = None,
        expected_camera_id: str | None = None,
        expected_surface_id: str | None = None,
    ) -> list[str]:
        """Verify hardware ID compatibility. Returns list of warning strings."""
        warnings: list[str] = []
        cal = bundle.calibration

        if (
            expected_projector_id is not None
            and cal.projector_id != expected_projector_id
        ):
            warnings.append(
                f"Projector mismatch: expected {expected_projector_id!r}, "
                f"got {cal.projector_id!r}"
            )

        if expected_camera_id is not None and cal.camera_id != expected_camera_id:
            warnings.append(
                f"Camera mismatch: expected {expected_camera_id!r}, "
                f"got {cal.camera_id!r}"
            )

        if (
            expected_surface_id is not None
            and expected_surface_id
            and cal.surface_id != expected_surface_id
        ):
            warnings.append(
                f"Surface mismatch: expected {expected_surface_id!r}, "
                f"got {cal.surface_id!r}"
            )

        return warnings
