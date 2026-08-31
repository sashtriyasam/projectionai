"""Calibration history store — persist CalibrationHistory to disk.

The in-memory ``CalibrationHistory`` (from ``calibration.history``) has no
disk persistence.  This module bridges that gap with atomic writes and
checksummed storage.

File layout::

    .calibration/
    └── history/
        └── entries.json    # List of serialised HistoryEntry dicts

Each entry stores the full ``CalibrationResult`` (canonical) so history
can be restored without re-running calibration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from projectionai.calibration._persistence_utils import (
    FileLock,
    atomic_write_json,
    compute_checksum,
)
from projectionai.calibration.history import CalibrationHistory, HistoryEntry
from projectionai.calibration.types import CalibrationMethod, CalibrationResult

_logger = logging.getLogger(__name__)

HISTORY_DIR = "history"
HISTORY_FILE = "entries.json"
_LOCK_FILE = ".lock"


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialize_entry(entry: HistoryEntry) -> dict[str, Any]:
    """Serialize a HistoryEntry to a JSON-safe dict.

    The legacy ``CalibrationResult`` from ``calibration.types`` is stored
    via its ``to_dict()``-compatible structure.  We also store the
    canonical result if available.
    """
    data: dict[str, Any] = {
        "id": entry.id,
        "session_name": entry.session_name,
        "method": entry.method.value,
        "timestamp": entry.timestamp,
        "duration_ms": entry.duration_ms,
        "notes": entry.notes,
        "tags": list(entry.tags),
    }

    # Store the legacy result
    result = entry.result
    if result.data is not None:
        from dataclasses import asdict

        raw = asdict(result.data)
        raw["method"] = result.data.method.value
        data["result"] = {
            "success": result.success,
            "quality_score": result.quality_score,
            "error_message": result.error_message,
            "validation_errors": list(result.validation_errors),
            "validation_warnings": list(result.validation_warnings),
            "data": raw,
        }
    else:
        data["result"] = {
            "success": result.success,
            "quality_score": result.quality_score,
            "error_message": result.error_message,
            "validation_errors": list(result.validation_errors),
            "validation_warnings": list(result.validation_warnings),
        }

    return data


def _deserialize_entry(data: dict[str, Any]) -> HistoryEntry:
    """Deserialize a dict back into a HistoryEntry."""
    from projectionai.calibration.types import CalibrationData

    result_data = data.get("result", {})
    cal_data = None
    raw_data = result_data.get("data")
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

    result = CalibrationResult(
        success=result_data.get("success", False),
        data=cal_data,
        validation_errors=result_data.get("validation_errors", []),
        validation_warnings=result_data.get("validation_warnings", []),
        quality_score=result_data.get("quality_score", 0.0),
        error_message=result_data.get("error_message", ""),
    )

    return HistoryEntry(
        id=data.get("id", ""),
        result=result,
        session_name=data.get("session_name", ""),
        method=CalibrationMethod(data.get("method", "manual")),
        timestamp=data.get("timestamp", 0.0),
        duration_ms=data.get("duration_ms", 0.0),
        notes=data.get("notes", ""),
        tags=data.get("tags", []),
    )


# ---------------------------------------------------------------------------
# History store
# ---------------------------------------------------------------------------


class CalibrationHistoryStore:
    """Persist ``CalibrationHistory`` to disk with atomic writes.

    Usage::

        store = CalibrationHistoryStore()
        store.save(history, directory=Path("my_project.calibration"))
        restored = store.load(directory=Path("my_project.calibration"))
    """

    def save(
        self,
        history: CalibrationHistory,
        directory: Path,
    ) -> Path:
        """Save calibration history to *directory*/history/entries.json.

        Parameters
        ----------
        history:
            The in-memory calibration history.
        directory:
            The ``.calibration/`` parent directory.

        Returns
        -------
        Path to the written entries file.
        """
        directory = Path(directory)
        history_dir = directory / HISTORY_DIR
        entries_path = history_dir / HISTORY_FILE

        with FileLock(directory / _LOCK_FILE):
            entries_data = [_serialize_entry(e) for e in history.entries]

            checksum = compute_checksum(entries_data)

            payload: dict[str, Any] = {
                "version": 1,
                "checksum": checksum,
                "active_entry_id": history.active_entry_id,
                "max_entries": history.max_entries,
                "entries": entries_data,
            }

            atomic_write_json(entries_path, payload)
        _logger.info(
            "History saved to %s (%d entries)",
            entries_path,
            len(entries_data),
        )
        return entries_path

    def load(self, directory: Path) -> CalibrationHistory:
        """Load calibration history from *directory*/history/entries.json.

        Returns
        -------
        A populated ``CalibrationHistory`` instance.

        Raises
        ------
        FileNotFoundError
            If the history file is missing.
        ValueError
            If the checksum doesn't match (corrupt data).
        """
        directory = Path(directory)
        entries_path = directory / HISTORY_DIR / HISTORY_FILE

        if not entries_path.exists():
            _logger.debug(
                "No history file at %s — returning empty history", entries_path
            )
            return CalibrationHistory()

        payload = json.loads(entries_path.read_text(encoding="utf-8"))

        # Verify checksum
        entries_data = payload.get("entries", [])
        actual_checksum = compute_checksum(entries_data)
        expected_checksum = payload.get("checksum", "")

        if expected_checksum and actual_checksum != expected_checksum:
            raise ValueError(
                f"History checksum mismatch in {entries_path}. Data may be corrupted."
            )

        # Reconstruct history
        history = CalibrationHistory(
            max_entries=payload.get("max_entries", 50),
        )
        history.active_entry_id = payload.get("active_entry_id", "")

        for entry_data in entries_data:
            try:
                entry = _deserialize_entry(entry_data)
                history.entries.append(entry)
            except Exception as exc:
                _logger.warning("Skipping invalid history entry: %s", exc)

        _logger.info(
            "History loaded from %s (%d entries)",
            entries_path,
            len(history.entries),
        )
        return history

    def exists(self, directory: Path) -> bool:
        """Return ``True`` if a history file exists in *directory*."""
        entries_path = Path(directory) / HISTORY_DIR / HISTORY_FILE
        return entries_path.exists()
