"""Calibration history — persistent record of completed calibrations.

The history stores past calibration results so users can review, compare,
and revert to previous calibrations. Each entry is a snapshot of the
``CalibrationResult`` at the time of completion.

History entries are ordered by completion time (newest first). The history
supports filtering by method and quality score thresholds.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from projectionai.calibration.types import CalibrationMethod, CalibrationResult

_logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    """A single entry in the calibration history.

    Stores the result and metadata about when/how it was produced.
    """

    id: str
    result: CalibrationResult
    session_name: str = ""
    method: CalibrationMethod = CalibrationMethod.MANUAL
    timestamp: float = 0.0
    duration_ms: float = 0.0
    notes: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class CalibrationHistory:
    """Ordered history of past calibration results.

    Entries are stored newest-first. The active (current) calibration
    is tracked separately.
    """

    entries: list[HistoryEntry] = field(default_factory=list)
    active_entry_id: str = ""

    # Capacity limit (None = unlimited)
    max_entries: int | None = 50

    def add_entry(
        self, result: CalibrationResult, session_name: str = ""
    ) -> HistoryEntry:
        """Add a new calibration result to the history.

        Args:
            result: The completed calibration result.
            session_name: Optional name of the session that produced this entry.

        Returns:
            The newly created history entry.
        """
        import time
        from uuid import uuid4

        entry = HistoryEntry(
            id=uuid4().hex,
            result=copy.deepcopy(result),
            session_name=session_name,
            method=(
                result.data.method
                if result.data is not None
                else CalibrationMethod.MANUAL
            ),
            timestamp=time.time(),
            duration_ms=result.data.duration_ms if result.data is not None else 0.0,
        )
        self.entries.insert(0, entry)
        self.active_entry_id = entry.id

        # Enforce capacity limit
        if self.max_entries is not None and len(self.entries) > self.max_entries:
            self.entries = self.entries[: self.max_entries]

        _logger.debug("Added history entry %s (total: %d)", entry.id, len(self.entries))
        return entry

    def get_entry(self, entry_id: str) -> HistoryEntry | None:
        """Get a history entry by ID."""
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def get_active(self) -> HistoryEntry | None:
        """Get the active (most recent) history entry."""
        if not self.entries:
            return None
        if self.active_entry_id:
            return self.get_entry(self.active_entry_id)
        return self.entries[0]

    def get_by_method(self, method: CalibrationMethod) -> list[HistoryEntry]:
        """Filter history entries by calibration method."""
        return [e for e in self.entries if e.method == method]

    def get_by_quality(
        self, min_score: float = 0.0, max_score: float = 1.0
    ) -> list[HistoryEntry]:
        """Filter history entries by quality score range."""
        return [
            e for e in self.entries if min_score <= e.result.quality_score <= max_score
        ]

    def remove_entry(self, entry_id: str) -> bool:
        """Remove a history entry by ID.

        Returns:
            ``True`` if the entry was found and removed.
        """
        for i, entry in enumerate(self.entries):
            if entry.id == entry_id:
                self.entries.pop(i)
                if self.active_entry_id == entry_id:
                    self.active_entry_id = self.entries[0].id if self.entries else ""
                return True
        return False

    def clear(self) -> None:
        """Remove all history entries."""
        self.entries.clear()
        self.active_entry_id = ""

    @property
    def count(self) -> int:
        """Number of history entries."""
        return len(self.entries)

    @property
    def best_entry(self) -> HistoryEntry | None:
        """Return the entry with the highest quality score."""
        if not self.entries:
            return None
        return max(self.entries, key=lambda e: e.result.quality_score)

    @property
    def latest_entry(self) -> HistoryEntry | None:
        """Return the most recently added entry."""
        if not self.entries:
            return None
        return self.entries[0]
