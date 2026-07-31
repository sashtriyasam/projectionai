"""Tests for calibration history."""

from __future__ import annotations

import pytest

from projectionai.calibration.history import CalibrationHistory
from projectionai.calibration.types import (
    CalibrationData,
    CalibrationMethod,
    CalibrationResult,
)


def _make_result(
    quality: float = 0.8, method: str = "manual", confidence: float = 0.9
) -> CalibrationResult:
    return CalibrationResult(
        success=True,
        data=CalibrationData(
            method=CalibrationMethod(method),
            confidence=confidence,
        ),
        quality_score=quality,
    )


class TestCalibrationHistory:
    def test_empty_initial_state(self) -> None:
        history = CalibrationHistory()
        assert history.count == 0
        assert history.active_entry_id == ""
        assert history.get_active() is None
        assert history.best_entry is None
        assert history.latest_entry is None

    def test_add_entry(self) -> None:
        history = CalibrationHistory()
        result = _make_result()
        entry = history.add_entry(result)
        assert history.count == 1
        assert entry.id == history.active_entry_id
        assert history.latest_entry is entry

    def test_get_entry_by_id(self) -> None:
        history = CalibrationHistory()
        result = _make_result()
        entry = history.add_entry(result)
        assert history.get_entry(entry.id) is entry
        assert history.get_entry("nonexistent") is None

    def test_get_active_returns_most_recent(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result(quality=0.5))
        e2 = history.add_entry(_make_result(quality=0.9))
        active = history.get_active()
        assert active is not None
        assert active.id == e2.id

    def test_active_entry_not_found_returns_none(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result())
        history.active_entry_id = "ghost"
        active = history.get_active()
        assert active is None

    def test_filter_by_method(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result(method="aruco"))
        history.add_entry(_make_result(method="manual"))
        history.add_entry(_make_result(method="aruco"))
        aruco_entries = history.get_by_method(CalibrationMethod.ARUCO)
        assert len(aruco_entries) == 2

    def test_filter_by_quality(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result(quality=0.3))
        history.add_entry(_make_result(quality=0.6))
        history.add_entry(_make_result(quality=0.9))
        good = history.get_by_quality(min_score=0.5)
        assert len(good) == 2

    def test_remove_entry(self) -> None:
        history = CalibrationHistory()
        e1 = history.add_entry(_make_result())
        history.add_entry(_make_result())
        assert history.remove_entry(e1.id)
        assert history.count == 1
        assert history.get_entry(e1.id) is None

    def test_remove_nonexistent(self) -> None:
        history = CalibrationHistory()
        assert not history.remove_entry("ghost")

    def test_remove_updates_active(self) -> None:
        history = CalibrationHistory()
        e1 = history.add_entry(_make_result())
        e2 = history.add_entry(_make_result())
        history.remove_entry(e2.id)
        assert history.active_entry_id == e1.id

    def test_remove_last_entry_clears_active(self) -> None:
        history = CalibrationHistory()
        e1 = history.add_entry(_make_result())
        history.remove_entry(e1.id)
        assert history.active_entry_id == ""

    def test_clear(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result())
        history.add_entry(_make_result())
        history.clear()
        assert history.count == 0
        assert history.active_entry_id == ""

    def test_best_entry(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result(quality=0.5))
        e2 = history.add_entry(_make_result(quality=0.9))
        best = history.best_entry
        assert best is not None
        assert best.id == e2.id

    def test_latest_entry(self) -> None:
        history = CalibrationHistory()
        history.add_entry(_make_result())
        e2 = history.add_entry(_make_result())
        assert history.latest_entry is not None
        assert history.latest_entry.id == e2.id

    def test_max_entries_enforced(self) -> None:
        history = CalibrationHistory(max_entries=3)
        for _ in range(5):
            history.add_entry(_make_result())
        assert history.count == 3

    def test_entry_has_method(self) -> None:
        history = CalibrationHistory()
        entry = history.add_entry(_make_result(method="aruco"))
        assert entry.method == CalibrationMethod.ARUCO

    def test_entry_duration(self) -> None:
        result = _make_result()
        if result.data is not None:
            result.data.duration_ms = 1234.0
        history = CalibrationHistory()
        entry = history.add_entry(result)
        assert entry.duration_ms == 1234.0

    def test_stored_snapshot_unchanged_after_mutation(self) -> None:
        """Regression: mutating the original result after add_entry must
        not affect the deep-copied snapshot stored in history."""
        history = CalibrationHistory()
        result = _make_result(quality=0.8, confidence=0.9)
        entry = history.add_entry(result)

        # Mutate every mutable field on the original
        result.quality_score = 0.0
        result.success = False
        result.validation_errors.append("mutated")
        if result.data is not None:
            result.data.duration_ms = 999.0
            result.data.custom["mutated"] = True
            result.data.residuals.append(42.0)

        # The stored entry must reflect the pre-mutation snapshot
        assert entry.result.quality_score == 0.8
        assert entry.result.success is True
        assert entry.result.validation_errors == []
        if entry.result.data is not None:
            assert entry.result.data.duration_ms == pytest.approx(0.0)
            assert "mutated" not in entry.result.data.custom
            assert 42.0 not in entry.result.data.residuals
