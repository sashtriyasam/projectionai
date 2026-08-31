"""Calibration persistence — save/load calibration assets with integrity.

Provides atomic, checksummed persistence for CalibrationResult, WarpMesh,
and ProjectionMapping.  All domain objects use their existing ``to_dict()``
/ ``from_dict()`` methods — no duplicate models.

File layout on disk::

    .calibration/
    ├── manifest.json       # Schema version, checksums, metadata
    ├── calibration.json    # CalibrationResult.to_dict()
    ├── warp_mesh.json      # WarpMesh.to_dict() (optional)
    └── projection.json     # ProjectionMapping.to_dict() (optional)

Design constraints
------------------
- **No second CalibrationResult/WarpMesh model** — reuse domain objects.
- **No silent overwrite** — caller must confirm before overwriting valid data.
- **No silent corrupt load** — raise ``IntegrityError`` on checksum mismatch.
- **No recalculation** — load exactly what was saved.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projectionai.calibration._persistence_utils import (
    FileLock,
    atomic_write_json,
    compute_checksum,
    verify_checksum,
)
from projectionai.domain.calibration_session import (
    CalibrationResult as CanonicalCalibrationResult,
)
from projectionai.domain.projection import ProjectionMapping
from projectionai.domain.warp_mesh import WarpMesh

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

SCHEMA_VERSION: int = 1
"""Bump when the on-disk format changes incompatibly."""

# File names inside the .calibration/ directory
MANIFEST_FILE = "manifest.json"
CALIBRATION_FILE = "calibration.json"
WARP_MESH_FILE = "warp_mesh.json"
PROJECTION_FILE = "projection.json"
_LOCK_FILE = ".lock"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PersistenceError(RuntimeError):
    """Base error for calibration persistence failures."""


class IntegrityError(PersistenceError):
    """Raised when stored data fails checksum verification."""


class CompatibilityError(PersistenceError):
    """Raised when stored data is incompatible with current hardware."""


class SchemaVersionError(PersistenceError):
    """Raised when the stored schema version is too new to read."""


# ---------------------------------------------------------------------------
# Bundle (what load() returns)
# ---------------------------------------------------------------------------


@dataclass
class CalibrationPersistenceBundle:
    """Everything that was loaded from a ``.calibration/`` directory."""

    manifest: dict[str, Any]
    calibration: CanonicalCalibrationResult
    warp_mesh: WarpMesh | None = None
    projection: ProjectionMapping | None = None


# ---------------------------------------------------------------------------
# Core persistence
# ---------------------------------------------------------------------------


class CalibrationPersistence:
    """Save and load calibration assets with integrity verification.

    Usage::

        persistence = CalibrationPersistence()
        persistence.save(
            directory=Path("my_project.calibration"),
            calibration_result=result,
            warp_mesh=mesh,
            projection_mapping=projection,
        )
        bundle = persistence.load(Path("my_project.calibration"))
    """

    # -- Save ----------------------------------------------------------------

    def save(
        self,
        directory: Path,
        *,
        calibration_result: CanonicalCalibrationResult,
        warp_mesh: WarpMesh | None = None,
        projection_mapping: ProjectionMapping | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Persist calibration assets to *directory*.

        Parameters
        ----------
        directory:
            Target ``.calibration/`` directory (created if absent).
        calibration_result:
            The canonical calibration result to save.
        warp_mesh:
            Optional warp mesh to save alongside the calibration.
        projection_mapping:
            Optional projection mapping to save alongside the calibration.
        overwrite:
            If ``False`` and a valid manifest already exists, raise
            ``PersistenceError``.  Set ``True`` to allow overwriting.

        Returns
        -------
        Path to the manifest file.

        Raises
        ------
        PersistenceError
            If *overwrite* is ``False`` and valid data already exists.
        """
        directory = Path(directory)
        manifest_path = directory / MANIFEST_FILE

        # Single-writer lock for concurrent safety
        with FileLock(directory / _LOCK_FILE):
            # Guard: don't silently overwrite (inside lock for atomicity)
            if not overwrite and manifest_path.exists():
                try:
                    existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if existing.get("schema_version") is not None:
                        raise PersistenceError(
                            f"Valid calibration data already exists in {directory}. "
                            "Pass overwrite=True to replace it."
                        )
                except (json.JSONDecodeError, OSError):
                    pass  # Corrupt manifest — safe to overwrite

            # Serialise domain objects
            cal_dict = calibration_result.to_dict()
            checksums: dict[str, str] = {
                "calibration": compute_checksum(cal_dict),
            }

            # Write each file atomically, collect checksums
            atomic_write_json(directory / CALIBRATION_FILE, cal_dict)

            if warp_mesh is not None:
                wm_dict = warp_mesh.to_dict()
                checksums["warp_mesh"] = compute_checksum(wm_dict)
                atomic_write_json(directory / WARP_MESH_FILE, wm_dict)

            if projection_mapping is not None:
                pm_dict = projection_mapping.to_dict()
                checksums["projection"] = compute_checksum(pm_dict)
                atomic_write_json(directory / PROJECTION_FILE, pm_dict)

            # Write manifest last (atomic)
            now = time.time()
            manifest: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "created_at": now,
                "updated_at": now,
                "checksums": checksums,
                "projector_id": calibration_result.projector_id,
                "camera_id": calibration_result.camera_id,
                "surface_id": calibration_result.surface_id,
                "calibration_id": calibration_result.calibration_id,
                "sequence_id": calibration_result.sequence_id,
                "method": calibration_result.method.value,
                "has_warp_mesh": warp_mesh is not None,
                "has_projection": projection_mapping is not None,
            }
            atomic_write_json(manifest_path, manifest)

        _logger.info(
            "Calibration persisted to %s (id=%s)",
            directory,
            calibration_result.calibration_id,
        )
        return manifest_path

    # -- Load ----------------------------------------------------------------

    def load(self, directory: Path) -> CalibrationPersistenceBundle:
        """Load calibration assets from *directory*.

        Parameters
        ----------
        directory:
            Path to the ``.calibration/`` directory.

        Returns
        -------
        A ``CalibrationPersistenceBundle`` with all loaded objects.

        Raises
        ------
        FileNotFoundError
            If *directory* or the manifest is missing.
        SchemaVersionError
            If the stored schema version is newer than ``SCHEMA_VERSION``.
        IntegrityError
            If any checksum fails verification.
        """
        directory = Path(directory)
        manifest_path = directory / MANIFEST_FILE

        if not manifest_path.exists():
            raise FileNotFoundError(f"No manifest found in {directory}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Schema version check
        stored_version = manifest.get("schema_version", 0)
        if stored_version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Stored schema version {stored_version} is newer than "
                f"supported version {SCHEMA_VERSION}. "
                "Please upgrade ProjectionAI to load this calibration."
            )

        # Load and verify calibration
        cal_path = directory / CALIBRATION_FILE
        if not cal_path.exists():
            raise FileNotFoundError(f"Calibration file missing: {cal_path}")
        cal_dict = json.loads(cal_path.read_text(encoding="utf-8"))

        expected_cal_cs = manifest.get("checksums", {}).get("calibration", "")
        if stored_version >= 1 and not expected_cal_cs:
            raise IntegrityError(
                f"Schema version {stored_version} requires checksums but "
                f"calibration checksum missing in manifest."
            )
        if expected_cal_cs and not verify_checksum(cal_dict, expected_cal_cs):
            raise IntegrityError(
                f"Calibration checksum mismatch in {cal_path}. Data may be corrupted."
            )

        calibration = CanonicalCalibrationResult.from_dict(cal_dict)

        # Load and verify warp mesh (optional)
        warp_mesh: WarpMesh | None = None
        if manifest.get("has_warp_mesh", False):
            wm_path = directory / WARP_MESH_FILE
            if wm_path.exists():
                wm_dict = json.loads(wm_path.read_text(encoding="utf-8"))
                expected_wm_cs = manifest.get("checksums", {}).get("warp_mesh", "")
                if expected_wm_cs and not verify_checksum(wm_dict, expected_wm_cs):
                    raise IntegrityError(
                        f"WarpMesh checksum mismatch in {wm_path}. "
                        "Data may be corrupted."
                    )
                warp_mesh = WarpMesh.from_dict(wm_dict)

        # Load and verify projection mapping (optional)
        projection: ProjectionMapping | None = None
        if manifest.get("has_projection", False):
            pm_path = directory / PROJECTION_FILE
            if pm_path.exists():
                pm_dict = json.loads(pm_path.read_text(encoding="utf-8"))
                expected_pm_cs = manifest.get("checksums", {}).get("projection", "")
                if expected_pm_cs and not verify_checksum(pm_dict, expected_pm_cs):
                    raise IntegrityError(
                        f"ProjectionMapping checksum mismatch in {pm_path}. "
                        "Data may be corrupted."
                    )
                projection = ProjectionMapping.from_dict(pm_dict)

        _logger.info(
            "Calibration loaded from %s (id=%s)",
            directory,
            calibration.calibration_id,
        )

        return CalibrationPersistenceBundle(
            manifest=manifest,
            calibration=calibration,
            warp_mesh=warp_mesh,
            projection=projection,
        )

    # -- Utilities -----------------------------------------------------------

    def exists(self, directory: Path) -> bool:
        """Return ``True`` if *directory* contains a valid manifest."""
        manifest_path = Path(directory) / MANIFEST_FILE
        if not manifest_path.exists():
            return False
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return data.get("schema_version") is not None
        except (json.JSONDecodeError, OSError):
            return False

    def get_manifest(self, directory: Path) -> dict[str, Any] | None:
        """Return the manifest dict, or ``None`` if missing/corrupt."""
        manifest_path = Path(directory) / MANIFEST_FILE
        if not manifest_path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, OSError):
            return None
